import json
from types import SimpleNamespace

import pytest

from app.llm import LLMOutputError
from app.schemas import Course, RerouteRequest, Spot, T1Result
from app.stages.t5_rerouter import candidate_pool, reroute
from tests.test_t1 import VALID
from tests.test_t2 import spot
from tests.test_t3 import course

T1 = T1Result.model_validate(json.loads(VALID.strip("`json\n ")))  # PUBLIC -> 도보 기준


def mk(i, lat, lng, io="OUTDOOR", category="FESTIVAL", **sched):
    d = spot(i, category=category)
    d["location"].update(lat=lat, lng=lng)
    d["attributes"]["indoor_outdoor"] = io
    d["schedule"].update(sched)
    return Spot.model_validate(d)


# 1: 야외(현재 코스), 2: 실내(가까움), 3: 실내(먼 곳), 4: 영화(상영 종료)
SPOTS = [
    mk(1, 37.880, 127.730),
    mk(2, 37.884, 127.733, io="INDOOR"),
    mk(3, 37.980, 127.900, io="INDOOR"),
    mk(4, 37.881, 127.731, io="INDOOR", category="MOVIE", movie_showtimes=["10:00"]),
    mk(5, 37.8845, 127.7335, io="INDOOR"),
]
CURRENT = Course.model_validate(course("course_001", ["spot_001", "spot_002"]))


def req(**kw):
    base = dict(feedback="비 와요", location={"lat": 37.880, "lng": 127.730}, now="15:00", t1=T1,
                spots=[s.model_dump(mode="json") for s in SPOTS], course=CURRENT.model_dump(mode="json"))
    return RerouteRequest.model_validate({**base, **kw})


def raw(stop_ids, trigger="WEATHER", patch=None):
    c = course("course_001", stop_ids)
    return {"trigger": trigger, "summary": "야외 → 실내", "persona_patch": patch or {"preference_notes": []},
            "replacements": [{"removed_spot_id": "spot_001", "added_spot_id": "spot_002", "reason": "우천"}],
            "course": c, "pin_list": [{"spot_id": "spot_002", "category": "FESTIVAL", "score": 90,
                                       "why_for_you": "비", "tips": []}]}


class FakeClient:
    def __init__(self, *payloads):
        self.payloads, self.messages = list(payloads), self

    def create(self, **kw):
        block = SimpleNamespace(type="text", text=json.dumps(self.payloads.pop(0)))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_pool_excludes_far_and_missed_movie():
    ids = {s.id for s, _ in candidate_pool(req(), "15:00")}
    assert ids == {"spot_001", "spot_002", "spot_005"}


def test_indoor_swap_ok_with_geojson_and_route():
    r = reroute(req(weather="RAIN"), FakeClient(raw(["spot_002", "spot_005"])))
    assert [s.spot_id for s in r.course.stops] == ["spot_002", "spot_005"]
    assert r.course.stops[1].distance_from_prev_km < 0.2
    assert r.route["geometry"]["coordinates"][0] == [127.733, 37.884]  # [lng, lat]
    assert r.markers["features"][0]["properties"]["course_order"] == 1


def test_no_viable_course_returns_null_course():
    r = reroute(req(weather="RAIN"), FakeClient({**raw(["spot_002"]), "course": None}))
    assert r.course is None and r.route is None and r.markers["features"]


def test_rain_rejects_outdoor_course_then_fails():
    bad = raw(["spot_001", "spot_002"])
    with pytest.raises(LLMOutputError):
        reroute(req(weather="RAIN"), FakeClient(bad, bad))


def test_far_spot_rejected():
    with pytest.raises(LLMOutputError):
        reroute(req(feedback="다른 곳"), FakeClient(raw(["spot_002", "spot_003"], "FEEDBACK"),
                                                    raw(["spot_002", "spot_003"], "FEEDBACK")))


def test_persona_patch_applied():
    patch = {"activity_level": 1, "vibe_keywords": ["힐링"], "preference_notes": ["주차 편한 곳"]}
    payload = {**raw(["spot_002"]), "course": None, "persona_patch": patch, "trigger": "FEEDBACK"}
    r = reroute(req(feedback="주차 편한 데로"), FakeClient(payload))
    assert r.persona.activity_level == 1 and r.persona.vibe_keywords == ["힐링"]
    assert r.persona.companion == "연인" and r.preference_notes == ["주차 편한 곳"]
