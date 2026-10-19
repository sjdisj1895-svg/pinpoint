import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    """개발자의 .env(API_KEY 등)가 테스트에 섞여 실제 호출이 나가지 않게 기본 백엔드를 고정한다."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    for k in ("API_KEY", "API_BASE", "API_MODEL", "API_MAX_TOKENS", "RATE_LIMIT"):
        monkeypatch.delenv(k, raising=False)
    from app.ratelimit import limiter

    limiter.reset()  # 테스트 사이에 요청 횟수가 이어지지 않게
