"""단계 공통 LLM 호출: JSON 응답을 검증하고, 실패 시 오류를 알려 1회 재시도.

백엔드 선택 (LLM_PROVIDER=auto|anthropic|openai, 기본 auto):
- openai: OpenAI 호환 API. API_KEY, API_BASE, API_MODEL이 모두 있으면 auto에서도 이쪽을 쓴다.
- anthropic: Claude (ANTHROPIC_API_KEY, PINPLAY_MODEL).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Protocol, TypeVar

import anthropic
from pydantic import ValidationError

DEFAULT_MODEL = "claude-opus-5-5"
MAX_ATTEMPTS = 2
T = TypeVar("T")


class LLMOutputError(RuntimeError):
    """모델 출력이 거절/잘림/스키마 불일치로 쓸 수 없음."""


class LLMServiceError(RuntimeError):
    """LLM API 호출 자체의 실패. kind: rate_limit | auth | connection | status"""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status


class Backend(Protocol):
    def complete(self, system: str, messages: list[dict], max_tokens: int, model: str | None) -> str:
        """대화를 보내고 응답 텍스트를 반환. 거절/잘림은 LLMOutputError, API 실패는 LLMServiceError."""


class AnthropicBackend:
    def __init__(self, client: Any | None = None):
        self._client = client

    def complete(self, system: str, messages: list[dict], max_tokens: int, model: str | None) -> str:
        client = self._client or anthropic.Anthropic()
        try:
            response = client.messages.create(
                model=model or os.environ.get("PINPLAY_MODEL", DEFAULT_MODEL),
                max_tokens=max_tokens,
                system=system,
                output_config={"effort": "low"},
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            raise LLMServiceError("rate_limit", str(e), 429) from e
        except anthropic.AuthenticationError as e:
            raise LLMServiceError("auth", "인증 실패", 401) from e
        except anthropic.APIConnectionError as e:
            raise LLMServiceError("connection", "LLM API 연결 실패") from e
        except anthropic.APIStatusError as e:
            raise LLMServiceError("status", f"LLM API 오류 ({e.status_code})", e.status_code) from e
        if response.stop_reason == "refusal":
            raise LLMOutputError("모델이 요청을 거절했습니다.")
        return "".join(b.text for b in response.content if b.type == "text")


class OpenAICompatBackend:
    """OpenAI 호환 /chat/completions. 모델은 API_MODEL로 고정(단계별 model 힌트는 무시)."""

    def __init__(
        self, api_key: str, base_url: str, model: str, max_tokens: int | None = None, client: Any | None = None,
        stream: bool = True, effort: str | None = None,
    ):
        if client is None:
            import openai

            client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._client, self.model, self.max_tokens, self.stream = client, model, max_tokens, stream
        # Claude 계열을 중계하는 서비스는 추론 강도를 받아 응답이 훨씬 빠르다 (측정: 61초 → 11초).
        # 서비스가 이 파라미터를 거부(400)하면 한 번 빼고 재시도한다.
        self.effort = effort

    def _call(self, msgs: list[dict], kwargs: dict[str, Any]) -> tuple[str, str | None, bool]:
        """(텍스트, finish_reason, 거절 여부). 스트리밍이면 조각을 이어 붙인다 — 긴 응답이 게이트웨이의 무응답 제한(504)에 걸리지 않게 한다."""
        create = self._client.chat.completions.create
        if not self.stream:
            ch = create(model=self.model, messages=msgs, **kwargs).choices[0]
            return ch.message.content or "", ch.finish_reason, bool(getattr(ch.message, "refusal", None))
        parts: list[str] = []
        finish, refused = None, False
        for chunk in create(model=self.model, messages=msgs, stream=True, **kwargs):
            if not chunk.choices:
                continue
            ch = chunk.choices[0]
            if getattr(ch.delta, "content", None):
                parts.append(ch.delta.content)
            refused = refused or bool(getattr(ch.delta, "refusal", None))
            finish = ch.finish_reason or finish
        return "".join(parts), finish, refused

    def complete(self, system: str, messages: list[dict], max_tokens: int, model: str | None) -> str:
        import openai

        msgs = [{"role": "system", "content": system}, *messages]
        while True:
            kwargs: dict[str, Any] = {}
            if self.max_tokens:  # 서비스마다 파라미터/기본값이 달라 지정했을 때만 보낸다 (API_MAX_TOKENS)
                kwargs["max_tokens"] = self.max_tokens
            if self.effort:
                kwargs["extra_body"] = {"output_config": {"effort": self.effort}}
            try:
                text, finish, refused = self._call(msgs, kwargs)
                break
            except openai.BadRequestError as e:
                if self.effort:  # 이 서비스가 effort를 모르는 경우: 빼고 다시 시도
                    self.effort = None
                    continue
                raise LLMServiceError("status", f"LLM API 오류 ({e.status_code})", e.status_code) from e
            except openai.RateLimitError as e:
                raise LLMServiceError("rate_limit", str(e), 429) from e
            except openai.AuthenticationError as e:
                raise LLMServiceError("auth", "인증 실패", 401) from e
            except openai.APIConnectionError as e:
                raise LLMServiceError("connection", "LLM API 연결 실패") from e
            except openai.APIStatusError as e:
                raise LLMServiceError("status", f"LLM API 오류 ({e.status_code})", e.status_code) from e
        if refused or finish == "content_filter":
            raise LLMOutputError("모델이 요청을 거절했습니다.")
        if finish == "length":
            raise LLMOutputError("모델 출력이 길이 제한으로 잘렸습니다. API_MAX_TOKENS를 늘려 보세요.")
        return text


def get_backend() -> Backend:
    provider = os.environ.get("LLM_PROVIDER", "auto").lower()
    key, base, model = os.environ.get("API_KEY"), os.environ.get("API_BASE"), os.environ.get("API_MODEL")
    if provider == "openai" or (provider == "auto" and key and base and model):
        if not (key and base and model):
            raise LLMServiceError("auth", "LLM_PROVIDER=openai는 API_KEY, API_BASE, API_MODEL이 모두 필요합니다.")
        max_tokens = os.environ.get("API_MAX_TOKENS")
        stream = os.environ.get("API_STREAM", "1").strip().lower() not in ("0", "false", "no", "off")
        effort = os.environ.get("API_EFFORT", "low").strip().lower()
        return OpenAICompatBackend(
            key, base, model, int(max_tokens) if max_tokens else None, stream=stream,
            effort=None if effort in ("", "none", "off") else effort)
    return AnthropicBackend()


def ask_json(
    system: str,
    user: str,
    validate: Callable[[str], T],
    client: Any | None = None,  # Anthropic 형태 클라이언트(테스트 주입용). 없으면 환경설정의 백엔드 사용
    max_tokens: int = 4000,
    model: str | None = None,
) -> T:
    """validate(text)는 파싱·검증에 실패하면 ValueError/ValidationError를 던진다."""
    backend: Backend = AnthropicBackend(client) if client is not None else get_backend()
    messages = [{"role": "user", "content": user}]

    last_error: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        text = backend.complete(system, messages, max_tokens, model)
        try:
            return validate(text)
        except (ValueError, ValidationError) as e:
            last_error = e
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"스키마 검증 실패: {e}\n규칙을 지켜 JSON만 다시 출력하세요."},
            ]
    raise LLMOutputError(f"출력 검증 실패: {last_error}")
