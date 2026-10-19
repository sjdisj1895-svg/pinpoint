"""전체 파이프라인(T1→T2→T3) 통합 테스트: Claude와 데이터 공급자만 가짜로 대체."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.llm as llm_mod
import app.main as main
import app.pipeline as pipeline_mod
from tests.test_t1 import VALID
from tests.test_t2 import dec, row

# T2 모델은 판단만 내고, 제목·좌표는 Raw Data에서 온다
RAW_ROWS = [row("A", lat=37.880, lng=127.730), row("B", lat=37.884, lng=127.733)]
T2_OUT = [dec(0), dec(1)]
T3_OUT = {
    "pin_list": [{"spot_id": "spot_001", "category": "FESTIVAL", "score": 90, "why_for_you": "로맨틱", "tips": []}],
    "courses": [{"course_id": "c1", "title": "t", "duration_type": "HALF_DAY", "score": 88, "why_for_you": "연인",
                 "stops": [{"order": i + 1, "spot_id": s, "suggested_time": "14:00", "why_for_you": "연인", "tips": []}
                           for i, s in enumerate(["spot_001", "spot_002"])]}],
}


class FakeAnthropic:
    """system 프롬프트로 단계를 구분해 단계별 고정 응답을 돌려준다."""

    def __init__(self, *a, **k):
        self.messages = self

    def create(self, **kw):
        system = kw["system"]
        if "T1:" in system:
            text = VALID
        elif "T2:" in system:
            text = json.dumps(T2_OUT, ensure_ascii=False)
        elif "T3:" in system:
            text = json.dumps(T3_OUT, ensure_ascii=False)
        else:
            raise AssertionError("알 수 없는 단계")
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


class RawProvider:
    def fetch(self, t1):
        return RAW_ROWS


def test_full_pipeline_via_http(monkeypatch):
    monkeypatch.setattr(llm_mod.anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(pipeline_mod, "provider", RawProvider())
    c = TestClient(main.app)
    for path in ("/pipeline", "/api/pipeline"):  # 루트와 /api 접두사 모두 동작
        r = c.post(path, json={"text": "이번 주말 춘천 데이트"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["t1"]["target_region"]["city_district"] == "춘천시"
        assert [(s["id"], s["title"]) for s in body["t2"]] == [("spot_001", "A"), ("spot_002", "B")]
        course = body["t3"]["courses"][0]
        assert course["stops"][1]["distance_from_prev_km"] < 1.0  # 코드가 계산한 거리


def test_pipeline_without_data_source_returns_empty(monkeypatch):
    monkeypatch.setattr(llm_mod.anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(pipeline_mod, "provider", pipeline_mod.EmptyProvider())
    body = TestClient(main.app).post("/pipeline", json={"text": "춘천"}).json()
    assert body["t2"] == [] and body["t3"] == {"pin_list": [], "courses": []}


def test_invalid_input_rejected():
    c = TestClient(main.app)
    assert c.post("/pipeline", json={"text": ""}).status_code == 422
    assert c.post("/pipeline", json={"text": "x" * 3000}).status_code == 422
