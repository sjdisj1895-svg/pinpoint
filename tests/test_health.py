import base64
import json
import time

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings
from app.health import jwt_claims, llm_report, project_ref, supabase_report

URL = "https://abcdefghijkl.supabase.co"


def make_jwt(**claims) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64(claims)}.signature"


def test_project_ref_and_jwt_claims():
    assert project_ref(URL) == "abcdefghijkl" and project_ref("https://example.com") is None
    assert jwt_claims(make_jwt(role="anon"))["role"] == "anon"
    assert jwt_claims("not-a-jwt") is None and jwt_claims("a.b.c") is None


def test_service_role_jwt_is_recognised():
    r = supabase_report(Settings(supabase_url=URL, supabase_service_key=make_jwt(role="service_role", ref="abcdefghijkl", exp=time.time() + 999)))
    assert r["key_kind"] == "jwt" and r["jwt_role"] == "service_role"
    assert r["jwt_ref_matches_url"] is True and r["jwt_expired"] is False and r["url_looks_valid"] is True


def test_wrong_keys_are_flagged():
    anon = supabase_report(Settings(supabase_url=URL, supabase_service_key=make_jwt(role="anon", ref="abcdefghijkl")))
    assert anon["jwt_role"] == "anon"  # 서비스 키 대신 공개용 키를 넣은 경우를 알아낸다
    other = supabase_report(Settings(supabase_url=URL, supabase_service_key=make_jwt(role="service_role", ref="zzzzzzzzzzzz")))
    assert other["jwt_ref_matches_url"] is False  # 다른 프로젝트의 키
    assert "공개용" in supabase_report(Settings(supabase_url=URL, supabase_service_key="sb_publishable_x"))["key_kind"]
    assert "unknown" in supabase_report(Settings(supabase_url=URL, supabase_service_key="eyJ-truncated"))["key_kind"]
    assert supabase_report(Settings(supabase_url=URL, supabase_service_key="  " + make_jwt(role="service_role") + '"'))["key_has_space_or_quote"]
    assert supabase_report(Settings())["key_kind"] == "none"
    assert supabase_report(Settings(supabase_url="http://x.com", supabase_service_key="k"))["url_looks_valid"] is False


def test_llm_report_hides_key_and_path(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    for k, v in {"API_KEY": "SECRET-KEY", "API_BASE": "https://gw.example.com/api/v2/secretpath", "API_MODEL": "m1"}.items():
        monkeypatch.setenv(k, v)
    r = llm_report()
    assert r == {"provider": "openai-compatible", "api_key_set": True, "api_base_host": "gw.example.com", "api_model": "m1"}
    assert "SECRET" not in json.dumps(r) and "secretpath" not in json.dumps(r)


def test_health_route_never_returns_secret_values(monkeypatch):
    secret_key = make_jwt(role="service_role", ref="abcdefghijkl")
    st = Settings(supabase_url=URL, supabase_service_key=secret_key, admin_token="ADMIN-SECRET", kobis_key="KOBIS-SECRET")

    class Store:
        def search(self, *a, **k):
            return []

    monkeypatch.setattr(main, "get_settings", lambda: st)
    monkeypatch.setattr(main, "get_store", lambda: Store())
    r = TestClient(main.app).get("/api/health")
    body = r.text
    assert r.status_code == 200 and r.json()["db_check"] == "ok" and r.headers["cache-control"] == "no-store"
    assert r.json()["keys_present"]["admin_token"] is True
    for secret in (secret_key, "ADMIN-SECRET", "KOBIS-SECRET", URL):
        assert secret not in body


def test_health_reports_db_failure_kind(monkeypatch):
    class Broken:
        def search(self, *a, **k):
            raise type("APIError", (Exception,), {"code": "401"})("boom with SECRET")

    monkeypatch.setattr(main, "get_store", lambda: Broken())
    body = TestClient(main.app).get("/api/health").json()
    assert body["db_check"] == "실패: APIError 401" and "SECRET" not in json.dumps(body)
