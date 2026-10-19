"""T2: 실시간 로컬 이벤트 하베스터 (Raw Data 검증·정규화).

모델은 채택한 항목의 '판단'(요약·상태·신뢰도·확인 메모 등)만 출력하고, 제목·주소·좌표·기간·링크는 Raw Data에서
코드가 채운다. 출력이 짧아 빠르고, 모델이 좌표·주소를 지어낼 수 없다.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import anthropic
from pydantic import BaseModel, Field, TypeAdapter

from app.connectors.models import parse_date, to_float
from app.llm import ask_json
from app.providers import RawDataProvider
from app.schemas import Category, IndoorOutdoor, LiveStatus, Spot, SpotAttributes, SpotLocation, SpotSchedule, T1Result

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "t2_system.md").read_text(encoding="utf-8")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
PERIOD_GATED = {Category.FESTIVAL, Category.FLEA_MARKET}
DEFAULT_INDOOR_OUTDOOR = {Category.MOVIE: IndoorOutdoor.INDOOR, Category.FESTIVAL: IndoorOutdoor.OUTDOOR}
NO_INFO = "정보 없음"


class Decision(BaseModel):
    """모델이 채택한 항목에 대해 내리는 판단."""

    index: int
    subtitle: str
    live_status: LiveStatus
    operating_hours: str = NO_INFO
    admission_fee: str = NO_INFO
    parking_available: bool | None = None
    indoor_outdoor: IndoorOutdoor | None = None
    vibe_tags: list[str] = []
    confidence_score: float = Field(ge=0, le=1)
    verification_note: str


_DECISIONS = TypeAdapter(list[Decision])


def extract_json_array(text: str) -> list:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("JSON 배열을 찾을 수 없음")
    return json.loads(text[start : end + 1])


def passes_time_gate(spot: Spot, target: date) -> bool:
    """모델 판단과 별개로, 기간이 명시된 축제/플리마켓은 코드로 한 번 더 검증."""
    if spot.category not in PERIOD_GATED:
        return True
    dates = _DATE.findall(spot.schedule.period)
    if not dates:
        return True  # 상시/정기 행사는 모델 판단을 신뢰
    start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    return start <= target <= end


def usable_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spot을 만들 수 있는 항목만 남긴다: 제목·카테고리·주소·좌표 필수."""
    out = []
    for r in raw:
        try:
            Category(r.get("category"))
        except ValueError:
            continue
        if r.get("title") and r.get("address") and to_float(r.get("lat")) is not None and to_float(r.get("lng")) is not None:
            out.append(r)
    return out


def _is_http(url: Any) -> bool:
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def model_view(index: int, r: dict[str, Any]) -> dict[str, Any]:
    """모델에 보여 줄 최소 정보. 좌표·ID·URL 본문은 제외하고 official_url 여부만 알린다."""
    extra = {k: v for k, v in (r.get("extra") or {}).items() if k != "image"}  # 사진 URL은 판단에 불필요
    official = _is_http(r.get("source_url")) and extra.get("url_kind") != "map_search"
    view = {
        "index": index, "category": r["category"], "title": r["title"], "address": r["address"],
        "region_tag": r.get("region_tag"), "start_date": r.get("start_date"), "end_date": r.get("end_date"),
        "operating_hours": r.get("operating_hours"), "indoor_outdoor": r.get("indoor_outdoor"),
        "confidence": r.get("confidence"), "official_url": official, "extra": extra or None,
    }
    return {k: v for k, v in view.items() if v not in (None, "", [], {})}


def image_url_of(r: dict[str, Any]) -> str | None:
    """대표 사진 URL. http(s)만 허용하고, 한국관광공사 이미지는 https로 올려 혼합 콘텐츠 경고를 피한다."""
    url = (r.get("extra") or {}).get("image")
    if not _is_http(url):
        return None
    return url.replace("http://tong.visitkorea.or.kr/", "https://tong.visitkorea.or.kr/", 1)


def _period(r: dict[str, Any]) -> str:
    start, end = parse_date(r.get("start_date")), parse_date(r.get("end_date"))
    if start and end:
        return f"{start.isoformat()} ~ {end.isoformat()}"
    return "일정 미확인" if (r.get("extra") or {}).get("unverified") else "상시"


def build_spot(n: int, r: dict[str, Any], d: Decision) -> Spot:
    category = Category(r["category"])
    extra = r.get("extra") or {}
    showtimes = extra.get("showtimes")
    url = r["source_url"] if _is_http(r.get("source_url")) else f"https://map.naver.com/p/search/{quote(r['title'])}"
    tags = [t if t.startswith("#") else f"#{t}" for t in d.vibe_tags]
    try:
        raw_io = IndoorOutdoor(r.get("indoor_outdoor")) if r.get("indoor_outdoor") else None
    except ValueError:
        raw_io = None
    return Spot(
        id=f"spot_{n:03d}", category=category, title=r["title"], subtitle=d.subtitle,
        location=SpotLocation(address=r["address"], lat=to_float(r["lat"]), lng=to_float(r["lng"]),
                              region_tag=r.get("region_tag") or ""),
        schedule=SpotSchedule(
            period=_period(r), operating_hours=d.operating_hours or r.get("operating_hours") or NO_INFO,
            live_status=d.live_status,
            movie_showtimes=showtimes if category == Category.MOVIE and isinstance(showtimes, list) else None),
        attributes=SpotAttributes(
            vibe_tags=tags, admission_fee=d.admission_fee, parking_available=d.parking_available,
            indoor_outdoor=raw_io or d.indoor_outdoor or DEFAULT_INDOOR_OUTDOOR.get(category, IndoorOutdoor.BOTH)),
        source_url=url, image_url=image_url_of(r), confidence_score=d.confidence_score,
        verification_note=d.verification_note,
    )


def harvest(
    t1: T1Result,
    provider: RawDataProvider,
    client: anthropic.Anthropic | None = None,
) -> list[Spot]:
    rows = usable_rows(provider.fetch(t1))
    if not rows:
        return []  # 근거 데이터가 없으면 모델을 호출하지 않는다 (환각 방지)
    user = (
        "[T1 조건]\n" + t1.model_dump_json() + "\n\n"
        "[Raw Data]\n" + json.dumps([model_view(i, r) for i, r in enumerate(rows)], ensure_ascii=False)
    )

    def validate(text: str) -> list[Decision]:
        decisions = _DECISIONS.validate_python(extract_json_array(text))
        idx = [d.index for d in decisions]
        bad = [i for i in idx if not 0 <= i < len(rows)]
        if bad:
            raise ValueError(f"입력에 없는 index: {bad}")
        if len(set(idx)) != len(idx):
            raise ValueError("같은 index가 중복됨")
        return decisions

    decisions = ask_json(SYSTEM_PROMPT, user, validate, client, max_tokens=8000)
    wanted = set(t1.requested_categories)
    spots = [build_spot(n, rows[d.index], d) for n, d in enumerate(sorted(decisions, key=lambda d: d.index), start=1)]
    kept = [s for s in spots if s.category in wanted and passes_time_gate(s, t1.time_context.target_date)]
    for n, s in enumerate(kept, start=1):  # 걸러낸 뒤 id를 연속 번호로 다시 매긴다
        s.id = f"spot_{n:03d}"
    return kept
