"""T5: 다이내믹 리라우팅 & 피드백 매니저."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import anthropic

from app.llm import ask_json
from app.schemas import (
    IndoorOutdoor, LiveStatus, RerouteRequest, RerouteResponse, Spot, T5Raw, Transport, Trigger, Weather,
)
from app.stages.t1_intent import extract_json
from app.stages.t3_curator import MAX_LEG_KM, haversine_km

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "t5_system.md").read_text(encoding="utf-8")
BAD_WEATHER = {Weather.RAIN, Weather.HEAT}


def _missed_movie(spot: Spot, now: str) -> bool:
    times = spot.schedule.movie_showtimes
    return bool(times) and max(times) < now  # "HH:MM" 문자열 비교


def _dist(req: RerouteRequest, s: Spot) -> float:
    return round(haversine_km(req.location.lat, req.location.lng, s.location.lat, s.location.lng), 2)


def candidate_pool(req: RerouteRequest, now: str) -> list[tuple[Spot, float]]:
    """사용자 위치 반경 내, 닫혔거나 상영이 모두 끝난 곳을 뺀 후보와 사용자와의 거리."""
    pool = []
    for s in req.spots:
        d = _dist(req, s)
        if d <= req.radius_km and s.schedule.live_status != LiveStatus.CLOSED and not _missed_movie(s, now):
            pool.append((s, d))
    return pool


def _validate(raw: T5Raw, req: RerouteRequest, pool_ids: set[str], by_id: dict[str, Spot]) -> None:
    original = {s.spot_id for s in req.course.stops} if req.course else set()
    allowed = pool_ids | original

    ids = [p.spot_id for p in raw.pin_list]
    ids += [r.added_spot_id for r in raw.replacements if r.added_spot_id]
    ids += [s.spot_id for s in raw.course.stops] if raw.course else []
    unknown = sorted({i for i in ids if i not in by_id})
    if unknown:
        raise ValueError(f"입력에 없는 spot_id: {unknown}")

    if raw.course:
        stop_ids = [s.spot_id for s in raw.course.stops]
        if len(set(stop_ids)) != len(stop_ids):
            raise ValueError("코스에 같은 스팟이 중복됨")
        out_of_range = sorted(set(stop_ids) - allowed)
        if out_of_range:
            raise ValueError(f"반경 밖이거나 이용 불가한 스팟이 코스에 포함됨: {out_of_range}")
        if raw.trigger == Trigger.WEATHER or req.weather in BAD_WEATHER:
            outdoor = [i for i in stop_ids if by_id[i].attributes.indoor_outdoor != IndoorOutdoor.INDOOR]
            if outdoor:
                raise ValueError(f"악천후인데 실내가 아닌 스팟이 코스에 있음: {outdoor}")


def _annotate_legs(raw: T5Raw, by_id: dict[str, Spot], transport: Transport) -> None:
    course = raw.course
    if not course:
        return
    limit = MAX_LEG_KM["CAR" if transport == Transport.CAR else "WALK"]
    course.stops.sort(key=lambda s: s.order)
    prev = None
    for stop in course.stops:
        loc = by_id[stop.spot_id].location
        if prev is not None:
            stop.distance_from_prev_km = round(haversine_km(prev.lat, prev.lng, loc.lat, loc.lng), 2)
            if stop.distance_from_prev_km > limit:
                raise ValueError(f"스팟 간 이동 거리 초과: {stop.spot_id} ({stop.distance_from_prev_km}km > {limit}km)")
        prev = loc


def build_markers(raw: T5Raw, by_id: dict[str, Spot]) -> dict:
    """GeoJSON FeatureCollection. 좌표 순서는 GeoJSON 규격대로 [lng, lat]."""
    order = {s.spot_id: s.order for s in raw.course.stops} if raw.course else {}
    scores = {p.spot_id: p.score for p in raw.pin_list}
    features = []
    for sid in dict.fromkeys([*scores, *order]):
        s = by_id[sid]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s.location.lng, s.location.lat]},
            "properties": {
                "id": sid, "title": s.title, "category": s.category.value,
                "live_status": s.schedule.live_status.value, "indoor_outdoor": s.attributes.indoor_outdoor.value,
                "score": scores.get(sid), "course_order": order.get(sid),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def build_route(raw: T5Raw, by_id: dict[str, Spot]) -> dict | None:
    if not raw.course:
        return None
    stops = raw.course.stops
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[by_id[s.spot_id].location.lng, by_id[s.spot_id].location.lat] for s in stops],
        },
        "properties": {
            "course_id": raw.course.course_id,
            "legs": [
                {"from": a.spot_id, "to": b.spot_id, "distance_km": b.distance_from_prev_km}
                for a, b in zip(stops, stops[1:])
            ],
        },
    }


def reroute(req: RerouteRequest, client: anthropic.Anthropic | None = None) -> RerouteResponse:
    now = req.now or datetime.now().strftime("%H:%M")
    pool = candidate_pool(req, now)
    pool_ids = {s.id for s, _ in pool}
    original_ids = {s.spot_id for s in req.course.stops} if req.course else set()
    by_id = {s.id: s for s in req.spots}

    # 모델에 보여 줄 스팟: 후보 풀 + 현재 코스 스팟(반경 밖이어도)
    shown = list(pool) + [(s, _dist(req, s)) for s in req.spots if s.id in original_ids and s.id not in pool_ids]

    user = (
        f"[현재 시각] {now}\n[사용자 위치] {req.location.model_dump_json()}\n"
        f"[날씨] {req.weather.value if req.weather else '미제공'}\n[사용자 피드백] {req.feedback}\n\n"
        f"[T1 user_persona]\n{req.t1.user_persona.model_dump_json()}\n\n"
        f"[현재 코스]\n{req.course.model_dump_json(exclude_none=True) if req.course else '없음'}\n\n"
        "[후보 스팟]\n"
        + json.dumps(
            [{**s.model_dump(mode="json", exclude_none=True), "distance_from_user_km": d} for s, d in shown],
            ensure_ascii=False,
        )
    )

    def validate(text: str) -> T5Raw:
        raw = T5Raw.model_validate(extract_json(text))
        _validate(raw, req, pool_ids, by_id)
        _annotate_legs(raw, by_id, req.t1.user_persona.transport)
        return raw

    raw = ask_json(SYSTEM_PROMPT, user, validate, client, max_tokens=16000)

    patch = raw.persona_patch.model_dump(exclude={"preference_notes"})
    persona = req.t1.user_persona.model_copy(update={k: v for k, v in patch.items() if v is not None})
    return RerouteResponse(
        trigger=raw.trigger, summary=raw.summary, persona=persona,
        preference_notes=raw.persona_patch.preference_notes, replacements=raw.replacements,
        course=raw.course, pin_list=raw.pin_list,
        markers=build_markers(raw, by_id), route=build_route(raw, by_id),
    )
