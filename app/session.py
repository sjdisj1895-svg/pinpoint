"""서명된 토큰(세션 쿠키·로그인 state). 외부 의존성 없이 HMAC-SHA256으로 위·변조를 막는다.

형식: base64url(JSON payload) + "." + base64url(HMAC). payload에 만료(exp)가 들어간다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, raw: str) -> str:
    return _b64(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())


def make_token(secret: str, payload: dict[str, Any], ttl_seconds: int, now: float | None = None) -> str:
    body = {**payload, "exp": int((time.time() if now is None else now) + ttl_seconds)}
    raw = _b64(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())
    return f"{raw}.{_sign(secret, raw)}"


def read_token(secret: str, token: str | None, now: float | None = None) -> dict[str, Any] | None:
    """유효한 토큰이면 payload, 서명이 틀렸거나 만료·손상됐으면 None."""
    if not token or not secret:
        return None
    try:
        raw, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(secret, raw)):  # 타이밍 공격을 피하는 비교
            return None
        data = json.loads(_unb64(raw))
    except (ValueError, TypeError, UnicodeDecodeError):  # JSONDecodeError는 ValueError의 하위 클래스
        return None
    if not isinstance(data, dict) or data.get("exp", 0) < (time.time() if now is None else now):
        return None
    return data
