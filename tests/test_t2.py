import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.llm import LLMOutputError
from app.providers import EmptyProvider
from app.schemas import T1Result
from app.stages.t2_harvester import harvest, model_view, passes_time_gate, usable_rows
from tests.test_t1 import VALID

T1 = T1Result.model_validate(json.loads(VALID.strip("`json\n ")))  # target 2026-10-24, FESTIVAL


def spot(i, category="FESTIVAL", period="2026-10-23 ~ 2026-10-25"):
    """(다른 테스트용) 완성된 Spot 형태의 dict."""
    return {
        "id": f"spot_{i:03d}", "category": category, "title": "t", "subtitle": "s",
        "location": {"address": "a", "lat": 37.88, "lng": 127.73, "region_tag": "춘천"},
        "schedule": {"period": period, "operating_hours": "10:00 ~ 18:00", "live_status": "OPEN_NOW"},
        "attributes": {"vibe_tags": ["#a"], "admission_fee": "무료", "parking_available": True, "indoor_outdoor": "OUTDOOR"},
        "source_url": "http://x", "confidence_score": 0.9, "verification_note": "ok",
    }


def row(title="축제", category="FESTIVAL", start="2026-10-23", end="2026-10-25", **kw):
    base = {"category": category, "title": title, "address": "강원특별자치도 춘천시 1", "lat": 37.88, "lng": 127.73,
            "region_tag": "강원 춘천시", "start_date": start, "end_date": end, "confidence": 0.7,
            "source_url": "https://map.naver.com/p/search/x", "extra": {"url_kind": "map_search"}}
    return {**base, **kw}


def dec(index, **kw):
    base = {"index": index, "subtitle": "요약", "live_status": "OPEN_NOW", "confidence_score": 0.8,
            "verification_note": "확인", "vibe_tags": ["야경"]}
    return {**base, **kw}


class Provider:
    def __init__(self, rows):
        self.rows = rows

    def fetch(self, t1):
        return self.rows


class FakeClient:
    def __init__(self, *payloads):
        self.payloads, self.calls, self.last_user = list(payloads), 0, None
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        self.last_user = kw["messages"][0]["content"]
        block = SimpleNamespace(type="text", text=json.dumps(self.payloads.pop(0), ensure_ascii=False))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_empty_or_unusable_raw_skips_llm():
    c = FakeClient([])
    assert harvest(T1, EmptyProvider(), c) == [] and c.calls == 0
    unusable = [{"raw": 1}, row(lat=None), row(address=""), row(category="UNKNOWN")]
    assert usable_rows(unusable) == [] and harvest(T1, Provider(unusable), c) == [] and c.calls == 0


def test_spot_built_from_raw_not_from_model():
    # 모델이 좌표·제목을 바꿔 보내도 무시된다 (Decision에 없는 필드)
    d = dec(0, lat=1.0, lng=2.0, title="가짜 제목", address="가짜 주소")
    (s,) = harvest(T1, Provider([row("소양강 축제", lat=37.89, lng=127.72)]), FakeClient([d]))
    assert (s.title, s.location.lat, s.location.lng) == ("소양강 축제", 37.89, 127.72)
    assert s.location.address == "강원특별자치도 춘천시 1" and s.location.region_tag == "강원 춘천시"
    assert s.schedule.period == "2026-10-23 ~ 2026-10-25" and s.attributes.vibe_tags == ["#야경"]
    assert s.attributes.parking_available is None and s.attributes.indoor_outdoor.value == "OUTDOOR"
    assert s.schedule.operating_hours == "정보 없음" and s.id == "spot_001"


def test_source_url_fallback_to_map_search_and_period_labels():
    no_url = row("카페 오픈", start=None, end=None, source_url=None, extra={"unverified": True})
    (s,) = harvest(T1.model_copy(update={"requested_categories": ["FESTIVAL"]}), Provider([no_url]), FakeClient([dec(0)]))
    assert s.source_url.startswith("https://map.naver.com/p/search/") and s.schedule.period == "일정 미확인"
    (s2,) = harvest(T1, Provider([row(start=None, end=None)]), FakeClient([dec(0)]))
    assert s2.schedule.period == "상시"


def test_filters_time_gate_and_category_and_renumbers():
    rows = [row("진행 중"), row("작년 축제", start="2025-10-23", end="2025-10-25"), row("영화관", category="MOVIE")]
    # 모델이 실수로 셋 다 채택해도 코드가 기간·카테고리로 걸러낸다
    out = harvest(T1, Provider(rows), FakeClient([dec(0), dec(1), dec(2)]))
    assert [(s.id, s.title) for s in out] == [("spot_001", "진행 중")]


def test_movie_defaults_and_no_invented_showtimes():
    t1 = T1.model_copy(update={"requested_categories": ["MOVIE"]})
    r = row("롯데시네마", category="MOVIE", start=None, end=None, extra={"showtimes_available": False})
    (s,) = harvest(t1, Provider([r]), FakeClient([dec(0)]))
    assert s.schedule.movie_showtimes is None and s.attributes.indoor_outdoor.value == "INDOOR"


def test_invalid_index_rejected_after_retry():
    bad = [dec(5)]
    with pytest.raises(LLMOutputError):
        harvest(T1, Provider([row()]), FakeClient(bad, bad))
    dup = [dec(0), dec(0)]
    with pytest.raises(LLMOutputError):
        harvest(T1, Provider([row()]), FakeClient(dup, dup))


def test_model_view_hides_coords_and_url_but_flags_official():
    v = model_view(3, row(source_url="https://chuncheon.go.kr", extra={}))
    assert v["index"] == 3 and v["official_url"] is True
    assert "lat" not in v and "lng" not in v and "source_url" not in v
    assert model_view(0, row())["official_url"] is False  # 지도 검색 링크는 공식 아님


def test_place_id_flows_from_raw_to_spot_but_not_to_the_model():
    r = row("축제", place_id="11111111-2222-3333-4444-555555555555")
    (s,) = harvest(T1, Provider([r]), FakeClient([dec(0)]))
    assert s.place_id == "11111111-2222-3333-4444-555555555555"  # 좋아요·댓글이 붙는 안정적인 키
    assert "place_id" not in model_view(0, r)  # 모델 입력에는 불필요
    (s2,) = harvest(T1, Provider([row("축제")]), FakeClient([dec(0)]))
    assert s2.place_id is None  # 실시간 수집(DB 없음)은 키가 없다 → 화면에서 좋아요·댓글 비활성


def test_model_view_hides_image_url():
    v = model_view(0, row(extra={"image": "https://tong.visitkorea.or.kr/a.jpg", "sources": ["tourapi"]}))
    assert "image" not in v["extra"] and v["extra"]["sources"] == ["tourapi"]


def test_prompt_input_is_compact():
    c = FakeClient([dec(0)])
    harvest(T1, Provider([row()]), c)
    assert "37.88" not in c.last_user.split("[Raw Data]")[1]  # 좌표는 모델 입력에 없다


def test_open_ended_period_passes():
    (s,) = harvest(T1, Provider([row(start=None, end=None)]), FakeClient([dec(0)]))
    assert passes_time_gate(s, date(2026, 10, 24))
