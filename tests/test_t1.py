from types import SimpleNamespace

import pytest

from app.schemas import ParseRequest
from app.stages.t1_intent import T1ParseError, extract_json, parse_intent

VALID = """```json
{"target_region":{"province":"강원특별자치도","city_district":"춘천시","center_coords":{"lat":37.88,"lng":127.73},"radius_km":10},
"time_context":{"target_date":"2026-10-24","time_window":"AFTERNOON","require_open_now":false},
"user_persona":{"companion":"연인","transport":"PUBLIC","vibe_keywords":["로맨틱"],"activity_level":3,"budget_tier":"MID"},
"requested_categories":["FESTIVAL"],"search_queries":["춘천시 이번주 축제"]}
```"""


class FakeClient:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        block = SimpleNamespace(type="text", text=self.texts.pop(0))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_extract_json_strips_fence():
    assert extract_json(VALID)["target_region"]["city_district"] == "춘천시"


def test_parse_ok():
    r = parse_intent(ParseRequest(text="춘천 데이트"), FakeClient(VALID))
    assert r.user_persona.activity_level == 3


def test_retry_then_ok():
    c = FakeClient("not json", VALID)
    assert parse_intent(ParseRequest(text="x"), c).target_region.radius_km == 10
    assert c.calls == 2


def test_fails_after_retries():
    with pytest.raises(T1ParseError):
        parse_intent(ParseRequest(text="x"), FakeClient("bad", "bad"))
