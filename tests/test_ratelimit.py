import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.llm as llm_mod
import app.main as main
import app.pipeline as pipeline_mod
from app.ratelimit import WINDOW_SECONDS, RateLimiter, client_ip
from tests.test_t1 import VALID


def test_limiter_blocks_after_limit_and_recovers_after_window():
    rl = RateLimiter()
    assert all(rl.allow("a", 3, now=i) for i in range(3))
    assert rl.allow("a", 3, now=3) is False
    assert rl.allow("b", 3, now=3) is True  # 다른 IP는 별개
    assert rl.allow("a", 3, now=WINDOW_SECONDS + 1) is True  # 윈도가 지나면 다시 허용
    assert rl.allow("a", 0, now=0) is True  # 0이면 제한 없음


def test_client_ip_prefers_forwarded_header():
    req = SimpleNamespace(headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"}, client=SimpleNamespace(host="9.9.9.9"))
    assert client_ip(req) == "1.2.3.4"
    assert client_ip(SimpleNamespace(headers={}, client=SimpleNamespace(host="9.9.9.9"))) == "9.9.9.9"
    assert client_ip(SimpleNamespace(headers={}, client=None)) == "unknown"


class FakeAnthropic:
    def __init__(self, *a, **k):
        self.messages = self

    def create(self, **kw):
        block = SimpleNamespace(type="text", text=VALID)
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_llm_routes_are_rate_limited_per_ip(monkeypatch):
    monkeypatch.setattr(llm_mod.anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setenv("RATE_LIMIT", "2")
    c = TestClient(main.app)
    h1, h2 = {"x-forwarded-for": "1.1.1.1"}, {"x-forwarded-for": "2.2.2.2"}
    assert [c.post("/parse", json={"text": "춘천"}, headers=h1).status_code for _ in range(3)] == [200, 200, 429]
    assert "너무 많아요" in c.post("/parse", json={"text": "춘천"}, headers=h1).json()["detail"]
    assert c.post("/parse", json={"text": "춘천"}, headers=h2).status_code == 200  # 다른 IP는 영향 없음


def test_non_llm_routes_are_not_limited(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT", "1")
    monkeypatch.setattr(main, "get_store", lambda: None)
    c = TestClient(main.app)
    assert [c.get("/spots/search", params={"lat": 37, "lng": 127}).status_code for _ in range(3)] == [503, 503, 503]


def test_invalid_rate_limit_env_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(llm_mod.anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setenv("RATE_LIMIT", "abc")
    c = TestClient(main.app)
    assert c.post("/parse", json={"text": "춘천"}).status_code == 200
