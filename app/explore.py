"""둘러보기: 권역(예: 경남)의 진행 중 스팟을 DB에서 모아 보여 준다. LLM을 쓰지 않아 빠르고 비용이 없다.

권역의 시·군 중심 좌표(scripts/regions.json)마다 반경 검색을 하고 합쳐서 중복을 제거한다.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
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
_cache: dict[tuple, tuple[float, dict]] = {}


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


def explore(store: SpotStore, province: str, target: date, categories: set[str] | None = None, limit: int = 300) -> dict:
    key = (province, target.isoformat(), tuple(sorted(categories or ())), limit)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    regions = province_regions(province)
    if not regions:
        raise KeyError(province)
    # 오늘 기준 진행 중인 항목 + (행사류는) 앞으로 열릴 항목을 위해 미래 기준일들도 조회해 합친다
    queries = [(r, target, categories) for r in regions]
    future_cats = EVENT_CATS if categories is None else EVENT_CATS & categories
    if future_cats:
        queries += [(r, target + timedelta(days=off), future_cats) for off in FUTURE_OFFSETS for r in regions]

    def run(q: tuple) -> list[dict]:
        r, day, cats = q
        local = store.for_thread() if hasattr(store, "for_thread") else store  # 클라이언트는 스레드별로
        return local.search(r["lat"], r["lng"], RADIUS_KM, day, cats, PER_CENTER_LIMIT)

    rows: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(run, queries):  # 입력 순서대로 합쳐 오늘 기준 결과가 우선한다
            for row in result:
                rows.setdefault(str(row["id"]), row)
    spots = [s for row in rows.values() if (s := row_to_spot(row, target)) and s.location.region_tag.startswith(province)]
    # 수가 적은 행사·영화관·신상 매장은 모두 보여 주고, 많은 여행지만 한도에 맞춰 줄인다
    events = [s for s in spots if s.category != Category.TRAVEL_SPOT]
    travel = [s for s in spots if s.category == Category.TRAVEL_SPOT]
    # 사진이 있고 신뢰도 높은 항목을 앞에 (카드 목록의 첫인상)
    rank = lambda s: (s.image_url is None, -s.confidence_score, s.title)  # noqa: E731
    chosen = sorted(events, key=rank)[:limit]
    chosen += sorted(travel, key=rank)[: max(0, limit - len(chosen))]
    chosen.sort(key=rank)
    out = {
        "province": province,
        "center": {"lat": sum(r["lat"] for r in regions) / len(regions), "lng": sum(r["lng"] for r in regions) / len(regions)},
        "count": len(chosen),
        "spots": [s.model_dump(mode="json", exclude_none=True) for s in chosen],
    }
    _cache[key] = (time.time(), out)
    return out
