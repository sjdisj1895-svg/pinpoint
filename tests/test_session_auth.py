import json

import httpx
import pytest

from app import auth
from app.session import make_token, read_token

SECRET = "x" * 40


class TestSession:
    def test_roundtrip(self):
        t = make_token(SECRET, {"sub": 123, "nick": "민수"}, 60)
        assert read_token(SECRET, t)["sub"] == 123 and read_token(SECRET, t)["nick"] == "민수"

    def test_wrong_secret_or_tampered_payload_is_rejected(self):
        t = make_token(SECRET, {"sub": 1}, 60)
        assert read_token("y" * 40, t) is None
        raw, sig = t.split(".")
        forged = make_token(SECRET, {"sub": 999}, 60).split(".")[0]  # 다른 사용자 payload에 기존 서명을 붙인다
        assert read_token(SECRET, f"{forged}.{sig}") is None

    def test_expiry(self):
        t = make_token(SECRET, {"sub": 1}, 60, now=1000)
        assert read_token(SECRET, t, now=1059) is not None
        assert read_token(SECRET, t, now=1061) is None

    @pytest.mark.parametrize("bad", [None, "", "abc", "a.b.c", "....", "e30.@@@", "!!.!!"])
    def test_garbage_never_raises(self, bad):
        assert read_token(SECRET, bad) is None

    def test_empty_secret_never_validates(self):
        assert read_token("", make_token("", {"sub": 1}, 60)) is None


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestKakaoAuth:
    def test_authorize_url(self):
        from urllib.parse import parse_qs, urlparse

        u = urlparse(auth.authorize_url("RESTKEY", "https://site.kr/api/auth/kakao/callback", "STATE"))
        q = parse_qs(u.query)
        assert u.netloc == "kauth.kakao.com" and u.path == "/oauth/authorize"
        assert q == {"client_id": ["RESTKEY"], "redirect_uri": ["https://site.kr/api/auth/kakao/callback"],
                     "response_type": ["code"], "state": ["STATE"]}

    def test_exchange_and_profile(self):
        seen = {}

        def handler(r: httpx.Request):
            if r.url.host == "kauth.kakao.com":
                seen["form"] = dict(httpx.QueryParams(r.content.decode()))
                return httpx.Response(200, json={"access_token": "AT"})
            seen["auth"] = r.headers["Authorization"]
            return httpx.Response(200, json={"id": 4242, "kakao_account": {"profile": {"nickname": "  경남러버  "}}})

        c = mock_client(handler)
        token = auth.exchange_code(c, "REST", "https://s/cb", "CODE", "CSECRET")
        assert token == "AT" and seen["form"]["grant_type"] == "authorization_code" and seen["form"]["client_secret"] == "CSECRET"
        user = auth.fetch_profile(c, token)
        assert user == auth.KakaoUser(id=4242, nickname="경남러버") and seen["auth"] == "Bearer AT"

    def test_client_secret_is_omitted_when_not_configured(self):
        seen = {}

        def handler(r):
            seen["form"] = dict(httpx.QueryParams(r.content.decode()))
            return httpx.Response(200, json={"access_token": "AT"})

        auth.exchange_code(mock_client(handler), "REST", "https://s/cb", "CODE")
        assert "client_secret" not in seen["form"]

    def test_known_error_codes_become_actionable_messages(self):
        c = mock_client(lambda r: httpx.Response(400, json={"error_code": "KOE006"}))
        with pytest.raises(auth.AuthError, match="Redirect URI"):
            auth.exchange_code(c, "REST", "https://s/cb", "CODE")
        c2 = mock_client(lambda r: httpx.Response(401, json={"error_code": "KOE010"}))
        with pytest.raises(auth.AuthError, match="Client Secret"):
            auth.exchange_code(c2, "REST", "https://s/cb", "CODE")

    def test_errors_never_leak_the_code_or_secret(self):
        c = mock_client(lambda r: httpx.Response(500, text="boom"))
        with pytest.raises(auth.AuthError) as e:
            auth.exchange_code(c, "REST", "https://s/cb", "SECRET-CODE", "SECRET-CS")
        assert "SECRET" not in str(e.value)

    def test_nickname_fallback_and_cleaning(self):
        assert auth.clean_nickname(None) == auth.DEFAULT_NICKNAME
        assert auth.clean_nickname("  \x00\n  ") == auth.DEFAULT_NICKNAME
        assert len(auth.clean_nickname("가" * 50)) == 20
        c = mock_client(lambda r: httpx.Response(200, json={"id": 1, "properties": {"nickname": "옛날방식"}}))
        assert auth.fetch_profile(c, "AT").nickname == "옛날방식"  # kakao_account가 없을 때 properties 사용

    def test_profile_without_numeric_id_is_rejected(self):
        c = mock_client(lambda r: httpx.Response(200, json={"id": "abc"}))
        with pytest.raises(auth.AuthError):
            auth.fetch_profile(c, "AT")

    def test_network_failure_is_an_auth_error(self):
        def boom(r):
            raise httpx.ConnectError("down")

        with pytest.raises(auth.AuthError):
            auth.exchange_code(mock_client(boom), "REST", "https://s/cb", "CODE")
