import json
from types import SimpleNamespace

import pytest

from app.llm import LLMOutputError
from app.schemas import Spot, T1Result
from app.stages.t3_curator import curate, haversine_km
from tests.test_t1 import VALID
from tests.test_t2 import spot

T1 = T1Result.model_validate(json.loads(VALID.strip("`json\n ")))  # PUBLIC -> 도보 기준


def mk(i, lat, lng):
    d = spot(i)
    d["location"].update(lat=lat, lng=lng)
    return Spot.model_validate(d)


SPOTS = [mk(1, 37.880, 127.730), mk(2, 37.884, 127.733), mk(3, 37.980, 127.900)]  # 3번은 멀다


def stop(order, sid):
    return {"order": order, "spot_id": sid, "suggested_time": "14:00", "why_for_you": "연인", "tips": []}


def course(cid, sids, score=80):
    return {"course_id": cid, "title": "t", "duration_type": "HALF_DAY", "score": score,
            "why_for_you": "연인", "stops": [stop(i + 1, s) for i, s in enumerate(sids)]}


def pin(sid, score):
    return {"spot_id": sid, "category": "FESTIVAL", "score": score, "why_for_you": "로맨틱", "tips": []}


class FakeClient:
    def __init__(self, payload):
        self.payload, self.messages = payload, self

    def create(self, **kw):
        block = SimpleNamespace(type="text", text=json.dumps(self.payload))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_empty_spots_skips_llm():
    assert curate(T1, [], None).courses == []


def test_far_course_dropped_and_distance_set():
    payload = {"pin_list": [pin("spot_001", 70), pin("spot_002", 90)],
               "courses": [course("c1", ["spot_001", "spot_002"]), course("c2", ["spot_001", "spot_003"], 99)]}
    r = curate(T1, SPOTS, FakeClient(payload))
    assert [c.course_id for c in r.courses] == ["c1"]
    assert r.courses[0].stops[1].distance_from_prev_km < 1.5
    assert [p.spot_id for p in r.pin_list] == ["spot_002", "spot_001"]


def test_unknown_spot_id_rejected():
    payload = {"pin_list": [pin("spot_999", 70)], "courses": []}
    with pytest.raises(LLMOutputError):
        curate(T1, SPOTS, FakeClient(payload))


def test_haversine():
    assert 0.4 < haversine_km(37.880, 127.730, 37.884, 127.733) < 0.6
