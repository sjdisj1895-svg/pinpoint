"""배포 환경 진단: 설정이 올바른 '형태'인지만 알려 준다. 키·토큰 값은 절대 응답에 싣지 않는다.

Supabase 키가 JWT이면 payload(role, 프로젝트 ref, 만료)는 공개 정보 수준이라 판별에 쓴다
(공개용 anon 키와 서비스 키를 헷갈린 경우를 바로 알아낼 수 있다).
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from urllib.parse import urlparse

from app.config import Settings


def jwt_claims(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data if isinstance(data, dict) else None
    except (ValueError, json.JSONDecodeError):
        return None


def project_ref(url: str) -> str | None:
    host = urlparse(url).hostname or ""
    return host.removesuffix(".supabase.co") if host.endswith(".supabase.co") else None


def supabase_report(s: Settings) -> dict[str, Any]:
    key, url = s.supabase_service_key, s.supabase_url
    out: dict[str, Any] = {
        "url_set": bool(url),
        "url_looks_valid": project_ref(url) is not None and url.startswith("https://"),
        "key_set": bool(key),
        "key_length": len(key),
        "key_has_space_or_quote": bool(key) and (key != key.strip() or any(ch in key for ch in " \"'\n\r\t")),
    }
    if not key:
        out["key_kind"] = "none"
    elif key.startswith("sb_secret_"):
        out["key_kind"] = "sb_secret (서버용 Secret key)"
    elif key.startswith("sb_publishable_"):
        out["key_kind"] = "sb_publishable (공개용: 서버 키로 쓰면 안 됨)"
    elif (claims := jwt_claims(key)) is not None:
        out["key_kind"] = "jwt"
        out["jwt_role"] = claims.get("role")  # service_role 이어야 한다 (anon이면 잘못 붙인 것)
        out["jwt_ref_matches_url"] = (claims.get("ref") == project_ref(url)) if claims.get("ref") and url else None
        exp = claims.get("exp")
        out["jwt_expired"] = (exp < time.time()) if isinstance(exp, (int, float)) else None
    else:
        out["key_kind"] = "unknown (형식을 알 수 없음: 잘렸거나 다른 값일 수 있음)"
    return out


def llm_report() -> dict[str, Any]:
    key, base, model = os.environ.get("API_KEY"), os.environ.get("API_BASE"), os.environ.get("API_MODEL")
    provider = os.environ.get("LLM_PROVIDER", "auto").lower()
    compat = provider == "openai" or (provider == "auto" and bool(key and base and model))
    return {
        "provider": "openai-compatible" if compat else "anthropic",
        "api_key_set": bool(key) if compat else bool(os.environ.get("ANTHROPIC_API_KEY")),
        "api_base_host": urlparse(base).hostname if base else None,  # 주소의 호스트만 (경로·키 제외)
        "api_model": model if compat else os.environ.get("PINPLAY_MODEL", "claude-opus-5-5"),
    }


def keys_present(s: Settings) -> dict[str, bool]:
    return {
        "data_go_kr": bool(s.data_go_key), "kobis": bool(s.kobis_key), "kakao": bool(s.kakao_rest_key),
        "kakao_js": bool(s.kakao_js_key),
        "session_secret_ok": len(s.session_secret) >= 32,  # 좋아요·댓글(로그인)에 필요. 값은 내보내지 않는다
        "social_enabled": s.social_enabled,
        "naver": bool(s.naver_client_id and s.naver_client_secret), "admin_token": bool(s.admin_token),
    }
