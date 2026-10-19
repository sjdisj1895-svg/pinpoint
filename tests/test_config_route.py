import json

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings, load_settings


def test_config_route_returns_only_the_public_kakao_js_key(monkeypatch):
    st = Settings(kakao_js_key="JS-KEY", kakao_rest_key="REST-SECRET", supabase_service_key="SB-SECRET",
                  admin_token="ADMIN-SECRET", naver_client_secret="NAVER-SECRET")
    monkeypatch.setattr(main, "get_settings", lambda: st)
    r = TestClient(main.app).get("/api/config")
    assert r.status_code == 200 and r.json() == {"kakao_js_key": "JS-KEY"}
    assert "max-age" in r.headers["cache-control"]
    body = json.dumps(r.json())
    for secret in ("REST-SECRET", "SB-SECRET", "ADMIN-SECRET", "NAVER-SECRET"):
        assert secret not in body  # 공개 설정에 다른 키가 섞이면 안 된다


def test_config_route_is_null_without_a_key(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings())
    assert TestClient(main.app).get("/config").json() == {"kakao_js_key": None}


def test_kakao_js_key_is_loaded_and_trimmed_from_env():
    assert load_settings({"KAKAO_JS_KEY": "  abc123  "}).kakao_js_key == "abc123"
    assert load_settings({}).kakao_js_key == ""
