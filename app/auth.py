"""카카오 로그인(OAuth 인가 코드 방식): 로그인 주소 만들기, 코드→토큰 교환, 프로필(닉네임) 조회.

토큰 교환과 프로필 조회는 서버에서 하고, 브라우저에는 카카오 액세스 토큰을 절대 보내지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
ME_URL = "https://kapi.kakao.com/v2/user/me"
DEFAULT_NICKNAME = "카카오 사용자"
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

# 자주 만나는 카카오 오류 코드를 사용자에게 보여 줄 안내로 바꾼다 (운영자가 무엇을 고쳐야 하는지 알 수 있게)
KAKAO_ERRORS = {
    "KOE010": "카카오 앱의 Client Secret 설정이 서버(KAKAO_CLIENT_SECRET)와 맞지 않습니다.",
    "KOE320": "로그인 인증 코드가 만료되었거나 이미 사용되었습니다. 다시 로그인해 주세요.",
    "KOE006": "카카오 개발자 콘솔에 이 사이트의 Redirect URI가 등록되지 않았습니다.",
    "KOE101": "카카오 앱 키(REST API 키)가 올바르지 않습니다.",
    "KOE205": "카카오 로그인에서 닉네임 동의항목이 설정되지 않았습니다.",
}


class AuthError(RuntimeError):
    """로그인 실패. 메시지는 사용자에게 그대로 보여 줄 수 있다 (키·토큰은 포함하지 않는다)."""


@dataclass(frozen=True)
class KakaoUser:
    id: int
    nickname: str


def clean_nickname(raw: object) -> str:
    s = _CTRL.sub("", str(raw or "")).strip()[:20]
    return s or DEFAULT_NICKNAME


def authorize_url(rest_key: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode(
        {"client_id": rest_key, "redirect_uri": redirect_uri, "response_type": "code", "state": state}
    )


def _fail(resp: httpx.Response, default: str) -> AuthError:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    code = str(body.get("error_code", ""))
    return AuthError(KAKAO_ERRORS.get(code, f"{default} ({code or resp.status_code})"))


def exchange_code(client: httpx.Client, rest_key: str, redirect_uri: str, code: str, client_secret: str = "") -> str:
    """인가 코드를 카카오 액세스 토큰으로 바꾼다."""
    data = {"grant_type": "authorization_code", "client_id": rest_key, "redirect_uri": redirect_uri, "code": code}
    if client_secret:
        data["client_secret"] = client_secret
    try:
        resp = client.post(TOKEN_URL, data=data, timeout=10)
    except httpx.TransportError as e:
        raise AuthError("카카오 서버에 연결하지 못했습니다.") from e
    if resp.status_code != 200:
        raise _fail(resp, "카카오 로그인에 실패했습니다")
    token = resp.json().get("access_token")
    if not token:
        raise AuthError("카카오 로그인 응답에 액세스 토큰이 없습니다.")
    return token


def fetch_profile(client: httpx.Client, access_token: str) -> KakaoUser:
    try:
        resp = client.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    except httpx.TransportError as e:
        raise AuthError("카카오 서버에 연결하지 못했습니다.") from e
    if resp.status_code != 200:
        raise _fail(resp, "카카오 사용자 정보를 가져오지 못했습니다")
    j = resp.json()
    if not isinstance(j.get("id"), int):
        raise AuthError("카카오 사용자 정보가 올바르지 않습니다.")
    profile = (j.get("kakao_account") or {}).get("profile") or {}
    return KakaoUser(id=j["id"], nickname=clean_nickname(profile.get("nickname") or (j.get("properties") or {}).get("nickname")))
