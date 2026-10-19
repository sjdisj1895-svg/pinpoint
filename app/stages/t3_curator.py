"""T3: 하이퍼 로컬 퍼스널 큐레이터 (Pin List + 추천 코스)."""
from __future__ import annotations

import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import anthropic

from app.llm import ask_json
from app.schemas import Spot, T1Result, T3Result, Transport
from app.stages.t1_intent import extract_json

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "t3_system.md").read_text(encoding="utf-8")
# 도보 15분(≈1.25km) / 자차 20분(≈12km)에 직선거리 오차 여유를 더한 한계값
MAX_LEG_KM = {"WALK": 1.5, "CAR": 12.0}
MAX_COURSES = 3
MAX_PINS_PER_CATEGORY = 3


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def _check_ids(result: T3Result, spots: dict[str, Spot]) -> None:
    ids = [p.spot_id for p in result.pin_list] + [s.spot_id for c in result.courses for s in c.stops]
    unknown = sorted({i for i in ids if i not in spots})
    if unknown:
        raise ValueError(f"T2 목록에 없는 spot_id: {unknown}")


def _finalize(result: T3Result, spots: dict[str, Spot], transport: Transport) -> T3Result:
    """거리 계산·동선 검증·정렬/개수 제한을 코드로 적용."""
    limit = MAX_LEG_KM["CAR" if transport == Transport.CAR else "WALK"]

    courses = []
    for course in result.courses:
        stops = sorted(course.stops, key=lambda s: s.order)
        prev = None
        for stop in stops:
            loc = spots[stop.spot_id].location
            if prev is not None:
                stop.distance_from_prev_km = round(haversine_km(prev.lat, prev.lng, loc.lat, loc.lng), 2)
            prev = loc
        if len({s.spot_id for s in stops}) == len(stops) and all(
            s.distance_from_prev_km is None or s.distance_from_prev_km <= limit for s in stops
        ):
            course.stops = stops
            courses.append(course)
    courses = sorted(courses, key=lambda c: -c.score)[:MAX_COURSES]

    pins, per_cat = [], {}
    for pin in sorted(result.pin_list, key=lambda p: -p.score):
        if per_cat.get(pin.category, 0) < MAX_PINS_PER_CATEGORY:
            per_cat[pin.category] = per_cat.get(pin.category, 0) + 1
            pins.append(pin)
    return T3Result(pin_list=pins, courses=courses)


def curate(t1: T1Result, spots: list[Spot], client: anthropic.Anthropic | None = None) -> T3Result:
    if not spots:
        return T3Result(pin_list=[], courses=[])
    by_id = {s.id: s for s in spots}
    user = (
        "[T1 사용자 성향]\n" + t1.model_dump_json() + "\n\n"
        "[T2 스팟 목록]\n" + json.dumps([s.model_dump(mode="json", exclude_none=True) for s in spots], ensure_ascii=False)
    )

    def validate(text: str) -> T3Result:
        result = T3Result.model_validate(extract_json(text))
        _check_ids(result, by_id)
        return result

    result = ask_json(SYSTEM_PROMPT, user, validate, client, max_tokens=16000)
    return _finalize(result, by_id, t1.user_persona.transport)
