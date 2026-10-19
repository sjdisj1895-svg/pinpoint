import json
from types import SimpleNamespace

import openai
import pytest

import app.llm as llm
from app.llm import AnthropicBackend, LLMOutputError, LLMServiceError, OpenAICompatBackend, ask_json, get_backend


def reply(text, finish="stop", refusal=None):
    msg = SimpleNamespace(content=text, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)])


class FakeOpenAI:
    def __init__(self, *replies, error=None):
        self.replies, self.error, self.calls = list(replies), error, []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.replies.pop(0)


def backend(fake, **kw):
    kw.setdefault("stream", False)  # 기존 테스트는 비스트리밍 응답 형태를 쓴다
    return OpenAICompatBackend("k", "https://gw.example/v1", "my-model", client=fake, **kw)


def chunk(text=None, finish=None, refusal=None, empty=False):
    if empty:  # 일부 서비스는 usage 등으로 choices가 빈 청크를 보낸다
        return SimpleNamespace(choices=[])
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, refusal=refusal),
                                                    finish_reason=finish)])


def test_openai_backend_streaming_joins_chunks():
    fake = FakeOpenAI([chunk("안"), chunk(empty=True), chunk("녕"), chunk(None, finish="stop")])
    out = backend(fake, stream=True).complete("S", [{"role": "user", "content": "x"}], 1, None)
    assert out == "안녕" and fake.calls[0]["stream"] is True


def test_openai_backend_streaming_truncation_and_refusal():
    with pytest.raises(LLMOutputError, match="API_MAX_TOKENS"):
        backend(FakeOpenAI([chunk("{"), chunk(None, finish="length")]), stream=True).complete("S", [], 1, None)
    with pytest.raises(LLMOutputError):
        backend(FakeOpenAI([chunk(None, refusal="no")]), stream=True).complete("S", [], 1, None)


def test_effort_sent_via_extra_body_and_dropped_if_rejected():
    resp = SimpleNamespace(status_code=400, headers={}, request=SimpleNamespace(method="POST", url="u"), text="")
    err = openai.BadRequestError("unknown param", response=resp, body=None)

    class Rejecting(FakeOpenAI):
        def create(self, **kw):
            self.calls.append(kw)
            if "extra_body" in kw:
                raise err
            return self.replies.pop(0)

    fake = Rejecting(reply("ok"))
    b = backend(fake, effort="low")
    assert b.complete("S", [], 1, None) == "ok"
    assert "extra_body" in fake.calls[0] and fake.calls[0]["extra_body"] == {"output_config": {"effort": "low"}}
    assert "extra_body" not in fake.calls[1] and b.effort is None  # 거부되면 빼고 재시도, 이후에도 보내지 않음


def test_bad_request_without_effort_is_a_service_error():
    resp = SimpleNamespace(status_code=400, headers={}, request=SimpleNamespace(method="POST", url="u"), text="")
    with pytest.raises(LLMServiceError) as e:
        backend(FakeOpenAI(error=openai.BadRequestError("bad", response=resp, body=None))).complete("S", [], 1, None)
    assert e.value.kind == "status" and e.value.status == 400


def test_effort_env(monkeypatch):
    for k, v in {"API_KEY": "k", "API_BASE": "https://gw.example/v1", "API_MODEL": "m", "LLM_PROVIDER": "auto"}.items():
        monkeypatch.setenv(k, v)
    assert get_backend().effort == "low"  # 기본값
    monkeypatch.setenv("API_EFFORT", "high")
    assert get_backend().effort == "high"
    monkeypatch.setenv("API_EFFORT", "")
    assert get_backend().effort is None


def test_stream_env_toggle(monkeypatch):
    for k, v in {"API_KEY": "k", "API_BASE": "https://gw.example/v1", "API_MODEL": "m", "LLM_PROVIDER": "auto"}.items():
        monkeypatch.setenv(k, v)
    assert get_backend().stream is True
    monkeypatch.setenv("API_STREAM", "0")
    assert get_backend().stream is False


def test_get_backend_selection(monkeypatch):
    assert isinstance(get_backend(), AnthropicBackend)  # conftest: LLM_PROVIDER=anthropic
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    assert isinstance(get_backend(), AnthropicBackend)  # 변수가 없으면 Claude
    for k, v in {"API_KEY": "k", "API_BASE": "https://gw.example/v1", "API_MODEL": "m"}.items():
        monkeypatch.setenv(k, v)
    assert isinstance(get_backend(), OpenAICompatBackend)  # 세 변수가 있으면 OpenAI 호환
    monkeypatch.delenv("API_MODEL")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(LLMServiceError):
        get_backend()


def test_openai_backend_request_shape_and_model_override():
    fake = FakeOpenAI(reply("ok"))
    out = backend(fake).complete("SYS", [{"role": "user", "content": "hi"}], 4000, "claude-haiku-5-5")
    call = fake.calls[0]
    assert out == "ok" and call["model"] == "my-model"  # 단계별 Claude 모델 힌트는 무시
    assert call["messages"][0] == {"role": "system", "content": "SYS"} and "max_tokens" not in call


def test_openai_backend_max_tokens_only_when_configured():
    fake = FakeOpenAI(reply("ok"))
    backend(fake, max_tokens=2000).complete("S", [{"role": "user", "content": "x"}], 4000, None)
    assert fake.calls[0]["max_tokens"] == 2000


def test_openai_backend_refusal_and_truncation():
    with pytest.raises(LLMOutputError):
        backend(FakeOpenAI(reply("", refusal="no"))).complete("S", [], 1, None)
    with pytest.raises(LLMOutputError, match="API_MAX_TOKENS"):
        backend(FakeOpenAI(reply("{", finish="length"))).complete("S", [], 1, None)


def test_openai_backend_maps_service_errors():
    req = SimpleNamespace(method="POST", url="https://gw.example/v1")
    resp = lambda code: SimpleNamespace(status_code=code, headers={}, request=req, text="")  # noqa: E731
    cases = [
        (openai.RateLimitError("x", response=resp(429), body=None), "rate_limit"),
        (openai.AuthenticationError("x", response=resp(401), body=None), "auth"),
        (openai.InternalServerError("x", response=resp(500), body=None), "status"),
    ]
    for err, kind in cases:
        with pytest.raises(LLMServiceError) as e:
            backend(FakeOpenAI(error=err)).complete("S", [], 1, None)
        assert e.value.kind == kind


def test_ask_json_retries_with_openai_backend(monkeypatch):
    fake = FakeOpenAI(reply("not json"), reply('{"a": 1}'))
    monkeypatch.setattr(llm, "get_backend", lambda: backend(fake))
    out = ask_json("S", "U", lambda t: json.loads(t))
    assert out == {"a": 1} and len(fake.calls) == 2
    assert "스키마 검증 실패" in fake.calls[1]["messages"][-1]["content"]  # 오류를 알려 재시도


def test_anthropic_path_unchanged_with_injected_client():
    block = SimpleNamespace(type="text", text='{"a": 2}')
    client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(stop_reason="end_turn", content=[block])))
    assert ask_json("S", "U", lambda t: json.loads(t), client) == {"a": 2}
