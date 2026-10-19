"""둘러보기: 권역(예: 경남)의 진행 중 스팟을 DB에서 모아 보여 준다. LLM을 쓰지 않아 빠르고 비용이 없다.

권역의 시·군 중심 좌표(scripts/regions.json)마다 반경 검색을 하고 합쳐서 중복을 제거한다.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.connectors.models import parse_date
from app.db import SpotStore
from app.schemas import (
    Category, IndoorOutdoor, LiveStatus, Spot, SpotAttributes, SpotLocation, SpotSchedule,
)
from app.stages.t2_harvester import DEFAULT_INDOOR_OUTDOOR, NO_INFO, _is_http, _period, image_url_of

REGIONS = Path(__file__).parent / "regions.json"  # 앱 패키지 안에 둬서 서버리스 번들에도 포함된다
RADIUS_KM = 25.0
PER_CENTER_LIMIT = 200
EVENT_CATS = {"FESTIVAL", "FLEA_MARKET"}
FUTURE_OFFSETS = (7, 14, 21, 30, 45, 60, 90)  # 개최예정 행사를 찾기 위한 미래 기준일(오늘 +N일)
CACHE_TTL = 900  # 초 (데이터는 정기 수집으로만 바뀐다)
_cache: dict[tuple, tuple[float, "Pool"]] = {}


def province_regions(province: str) -> list[dict[str, Any]]:
    return [r for r in json.loads(REGIONS.read_text(encoding="utf-8")) if r.get("province") == province]


def row_to_spot(row: dict[str, Any], target: date) -> Spot | None:
    """DB 행을 화면용 Spot으로 변환 (AI 검증 전 수집 데이터). 필수 값이 없으면 None."""
    try:
        category = Category(row["category"])
    except (KeyError, ValueError):
        return None
    if not (row.get("title") and row.get("address") and row.get("lat") is not None and row.get("lng") is not None):
        return None
    start = parse_date(row.get("start_date"))
    live = LiveStatus.OPEN_SOON if start and start > target else LiveStatus.OPEN_NOW
    try:
        io = IndoorOutdoor(row["indoor_outdoor"]) if row.get("indoor_outdoor") else None
    except ValueError:
        io = None
    extra = row.get("extra") or {}
    sources = ", ".join(row.get("sources") or []) or "수집 데이터"
    return Spot(
        id=str(row["id"]), category=category, title=row["title"],
        subtitle=row.get("subtitle") or (row.get("region_tag") or ""),
        location=SpotLocation(address=row["address"], lat=row["lat"], lng=row["lng"],
                              region_tag=row.get("region_tag") or ""),
        schedule=SpotSchedule(period=_period(row), operating_hours=row.get("operating_hours") or NO_INFO,
                              live_status=live),
        attributes=SpotAttributes(vibe_tags=[], admission_fee=NO_INFO, parking_available=None,
                                  indoor_outdoor=io or DEFAULT_INDOOR_OUTDOOR.get(category, IndoorOutdoor.BOTH)),
        source_url=row["source_url"] if _is_http(row.get("source_url")) else "https://map.naver.com/p/search/" + quote(row["title"]),
        image_url=image_url_of({"extra": extra}),
        confidence_score=float(row.get("confidence") or 0.5),
        verification_note=f"출처: {sources} (AI 검증 전 수집 데이터)",
    )


@dataclass
class Pool:
    """권역의 진행 중·개최예정 스팟 전체. 검색·필터는 이 목록 위에서 메모리로 하므로 DB를 다시 조회하지 않는다."""

    province: str
    center: dict[str, float]
    spots: list[Spot]


def load_pool(store: SpotStore, province: str, target: date) -> Pool:
    key = (province, target.isoformat())
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    regions = province_regions(province)
    if not regions:
        raise KeyError(province)
    # 오늘 기준 진행 중인 항목 + 앞으로 열릴 행사를 위해 미래 기준일들도 조회해 합친다 (미래는 행사류만)
    queries: list[tuple[dict, date, set[str] | None]] = [(r, target, None) for r in regions]
    queries += [(r, target + timedelta(days=off), EVENT_CATS) for off in FUTURE_OFFSETS for r in regions]

    def run(q: tuple) -> list[dict]:
        r, day, cats = q
        local = store.for_thread() if hasattr(store, "for_thread") else store  # 클라이언트는 스레드별로
        return local.search(r["lat"], r["lng"], RADIUS_KM, day, cats, PER_CENTER_LIMIT)

    rows: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for result in ex.map(run, queries):  # 입력 순서대로 합쳐 오늘 기준 결과가 우선한다
            for row in result:
                rows.setdefault(str(row["id"]), row)
    spots = [s for row in rows.values() if (s := row_to_spot(row, target)) and s.location.region_tag.startswith(province)]
    pool = Pool(
        province=province,
        center={"lat": sum(r["lat"] for r in regions) / len(regions), "lng": sum(r["lng"] for r in regions) / len(regions)},
        spots=spots,
    )
    _cache[key] = (time.time(), pool)
    return pool


# ---------- 키워드 검색 · 지역 필터 ----------
# 사용자가 분류 이름으로도 찾을 수 있게(예: "축제", "영화관", "카페") 분류별 동의어를 검색 대상에 포함한다
CATEGORY_WORDS = {
    Category.FESTIVAL: "지역축제 축제 행사 페스티벌",
    Category.FLEA_MARKET: "플리마켓 팝업 마켓 시장 벼룩시장",
    Category.MOVIE: "상영영화 영화 영화관 극장 시네마",
    Category.TRAVEL_SPOT: "여행지 관광 명소 여행 볼거리",
    Category.NEW_OPEN: "실시간오픈 신상 오픈 가오픈 카페 매장",
}
MAX_TOKENS = 5


def tokenize(q: str) -> list[str]:
    """공백으로 나눈 검색어(소문자). 모든 단어가 맞아야 결과에 나온다(AND). 빈 입력이면 []."""
    return [t for t in q.lower().split() if t][:MAX_TOKENS]


def _compact(s: str) -> str:
    return "".join(s.lower().split())  # '소양강 스카이워크'와 '소양강스카이'가 서로 맞게 공백을 없앤 형태


def match_score(spot: Spot, tokens: list[str]) -> int | None:
    """모든 검색어가 어디선가 맞으면 점수(이름 3 > 요약·태그 2 > 주소·지역·분류 1의 합), 하나라도 없으면 None."""
    title = _compact(spot.title)
    sub = _compact(" ".join([spot.subtitle, *spot.attributes.vibe_tags]))
    place = _compact(f"{spot.location.address} {spot.location.region_tag} {CATEGORY_WORDS[spot.category]}")
    total = 0
    for t in tokens:
        t = _compact(t)
        if t in title:
            total += 3
        elif t in sub:
            total += 2
        elif t in place:
            total += 1
        else:
            return None
    return total


def city_of(spot: Spot) -> str:
    """'경남 진주시' → '진주시' (시·군 단위 지역 필터에 쓰는 이름)"""
    parts = spot.location.region_tag.split()
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


def search_pool(
    pool: Pool, q: str = "", region: str = "", categories: set[str] | None = None, limit: int = 300,
) -> dict:
    tokens = tokenize(q)
    scored: list[tuple[Spot, int]] = []
    for s in pool.spots:
        if categories and s.category.value not in categories:
            continue
        score = match_score(s, tokens) if tokens else 0
        if score is not None:
            scored.append((s, score))

    # 지역 칩에 보여 줄 시·군별 개수는 '지역 필터를 걸기 전' 결과 기준이라, 다른 지역으로 바로 바꿔 볼 수 있다
    counts: dict[str, int] = {}
    for s, _ in scored:
        counts[city_of(s)] = counts.get(city_of(s), 0) + 1
    regions = [{"name": n, "count": c} for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n]

    if region:
        scored = [(s, sc) for s, sc in scored if city_of(s) == region]

    # 사진이 있고 신뢰도 높은 항목을 앞에 (카드 목록의 첫인상)
    rank = lambda s: (s.image_url is None, -s.confidence_score, s.title)  # noqa: E731
    if tokens:
        chosen = [s for s, _ in sorted(scored, key=lambda p: (-p[1], *rank(p[0])))[:limit]]
    else:
        # 수가 적은 행사·영화관·신상 매장은 모두 보여 주고, 많은 여행지만 한도에 맞춰 줄인다
        events = sorted((s for s, _ in scored if s.category != Category.TRAVEL_SPOT), key=rank)[:limit]
        travel = sorted((s for s, _ in scored if s.category == Category.TRAVEL_SPOT), key=rank)
        chosen = sorted(events + travel[: max(0, limit - len(events))], key=rank)
    return {
        "province": pool.province,
        "center": pool.center,
        "count": len(chosen),
        "total": len(scored),  # 한도로 자르기 전 일치 개수
        "regions": regions,
        "spots": [s.model_dump(mode="json", exclude_none=True) for s in chosen],
    }


def explore(
    store: SpotStore, province: str, target: date, categories: set[str] | None = None, limit: int = 300,
    q: str = "", region: str = "",
) -> dict:
    return search_pool(load_pool(store, province, target), q, region, categories, limit)
