import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import social_routes
from app.config import Settings
from app.session import make_token, read_token
from app.social import REPORT_HIDE_THRESHOLD, clean_comment
from app.social_routes import SESSION_COOKIE, build_router, safe_return_path

SECRET = "s" * 40
PLACE = str(uuid.uuid4())
H = {"X-PinPlay": "1"}  # CSRF 방어용 커스텀 헤더


class FakeSocial:
    """SocialStore와 같은 규칙(좋아요 토글, 신고 1인 1회, 3건이면 숨김)을 메모리에서 흉내 낸다."""

    def __init__(self, places=()):
        self.places, self.users, self.likes, self.comments, self.reports, self.n = set(places), {}, set(), {}, set(), 0

    def upsert_user(self, kakao_id, nickname):
        self.users[kakao_id] = nickname

    def place_exists(self, pid):
        return pid in self.places

    def toggle_like(self, pid, uid):
        if (pid, uid) in self.likes:
            self.likes.remove((pid, uid))
            liked = False
        else:
            self.likes.add((pid, uid))
            liked = True
        return {"liked": liked, "likes": sum(1 for p, _ in self.likes if p == pid)}

    def summary(self, ids, uid):
        return {
            i: {"likes": sum(1 for p, _ in self.likes if p == i),
                "comments": sum(1 for c in self.comments.values() if c["place"] == i and not c["hidden"]),
                "liked": uid is not None and (i, uid) in self.likes}
            for i in ids
        }

    def _view(self, cid, me):
        c = self.comments[cid]
        return {"id": cid, "body": c["body"], "created_at": c["at"], "nickname": self.users.get(c["uid"], "?"), "mine": c["uid"] == me}

    def list_comments(self, pid, me, limit=20, before=None):
        rows = sorted((k for k, c in self.comments.items() if c["place"] == pid and not c["hidden"]),
                      key=lambda k: self.comments[k]["at"], reverse=True)
        if before:
            rows = [k for k in rows if self.comments[k]["at"] < before]
        return [self._view(k, me) for k in rows[:limit]]

    def add_comment(self, pid, uid, body):
        self.n += 1
        cid = str(uuid.uuid4())
        self.comments[cid] = {"place": pid, "uid": uid, "body": body, "hidden": False, "at": f"2026-10-20T10:00:{self.n:02d}+00:00"}
        return self._view(cid, uid)

    def delete_comment(self, cid, uid):
        if cid in self.comments and self.comments[cid]["uid"] == uid:
            del self.comments[cid]
            return True
        return False

    def comment_author(self, cid):
        return self.comments[cid]["uid"] if cid in self.comments else None

    def report_comment(self, cid, uid):
        new = (cid, uid) not in self.reports
        self.reports.add((cid, uid))
        n = sum(1 for c, _ in self.reports if c == cid)
        if n >= REPORT_HIDE_THRESHOLD:
            self.comments[cid]["hidden"] = True
        return {"reported": new, "hidden": self.comments[cid]["hidden"]}

    def admin_reports(self):
        return [{"id": k, "body": c["body"]} for k, c in self.comments.items() if any(r[0] == k for r in self.reports)]

    def admin_delete(self, cid):
        return self.comments.pop(cid, None) is not None


def make(settings=None, store=None, http=None):
    st = store if store is not None else FakeSocial({PLACE})
    s = settings or Settings(kakao_rest_key="REST", session_secret=SECRET, supabase_url="https://x.supabase.co",
                             supabase_service_key="k", admin_token="ADMIN")
    app = FastAPI()
    app.include_router(build_router(lambda: s, lambda: st, http or (lambda: httpx.Client())), prefix="/api")
    return TestClient(app, follow_redirects=False), st


def login_as(client, uid=1, nick="민수"):
    client.cookies.set(SESSION_COOKIE, make_token(SECRET, {"sub": uid, "nick": nick}, 3600))
    return client


# ---------- 안전한 경로 / 입력 정리 ----------
@pytest.mark.parametrize("path,expected", [
    ("/", "/"), ("/?map=leaflet", "/?map=leaflet"), ("/a/b", "/a/b"), (None, "/"), ("", "/"),
    ("//evil.com", "/"), ("https://evil.com", "/"), ("/\\evil.com", "/"), ("evil.com", "/"), ("/a\nSet-Cookie: x=1", "/"),
])
def test_return_path_cannot_redirect_off_site(path, expected):
    assert safe_return_path(path) == expected


def test_clean_comment():
    assert clean_comment("  안녕\x00하세요\x07  ") == "안녕하세요"
    assert clean_comment("a\n\n\n\n\nb") == "a\n\nb"  # 과도한 빈 줄 축소
    assert clean_comment("a\r\nb") == "a\nb"
    assert clean_comment("   \n  ") == ""


# ---------- 로그인 ----------
class TestLogin:
    def test_redirects_to_kakao_with_signed_state_and_nonce_cookie(self):
        c, _ = make()
        r = c.get("/api/auth/kakao/login", params={"return": "/?sample"}, headers={"host": "site.kr"})
        u = urlparse(r.headers["location"])
        q = parse_qs(u.query)
        assert r.status_code == 302 and u.netloc == "kauth.kakao.com"
        assert q["client_id"] == ["REST"] and q["redirect_uri"] == ["http://site.kr/api/auth/kakao/callback"]
        state = read_token(SECRET, q["state"][0])
        assert state["r"] == "/?sample" and state["n"]
        cookie = r.headers["set-cookie"]
        assert "pp_oauth=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert state["n"] in cookie  # state 안의 nonce와 쿠키의 nonce가 같다

    def test_site_url_setting_and_forwarded_proto_decide_redirect_uri_and_secure_cookie(self):
        c, _ = make()
        r = c.get("/api/auth/kakao/login", headers={"host": "p.vercel.app", "x-forwarded-proto": "https"})
        assert parse_qs(urlparse(r.headers["location"]).query)["redirect_uri"] == ["https://p.vercel.app/api/auth/kakao/callback"]
        assert "Secure" in r.headers["set-cookie"]
        s = Settings(kakao_rest_key="REST", session_secret=SECRET, supabase_url="u", supabase_service_key="k", site_url="https://fixed.kr")
        c2, _ = make(settings=s)
        r2 = c2.get("/api/auth/kakao/login", headers={"host": "evil.com"})
        assert parse_qs(urlparse(r2.headers["location"]).query)["redirect_uri"] == ["https://fixed.kr/api/auth/kakao/callback"]

    def test_open_redirect_target_is_ignored(self):
        c, _ = make()
        r = c.get("/api/auth/kakao/login", params={"return": "//evil.com"})
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        assert read_token(SECRET, state)["r"] == "/"

    def test_disabled_without_configuration(self):
        c, _ = make(settings=Settings())
        assert c.get("/api/auth/kakao/login").status_code == 503
        assert c.get("/api/auth/me").json() == {"social": False, "user": None}

    def _start(self, c):
        r = c.get("/api/auth/kakao/login", params={"return": "/?x=1"})
        return parse_qs(urlparse(r.headers["location"]).query)["state"][0]

    def _kakao(self, ok=True):
        def handler(req):
            if req.url.host == "kauth.kakao.com":
                return httpx.Response(200, json={"access_token": "AT"}) if ok else httpx.Response(400, json={"error_code": "KOE320"})
            return httpx.Response(200, json={"id": 777, "kakao_account": {"profile": {"nickname": "카카오닉"}}})

        return lambda: httpx.Client(transport=httpx.MockTransport(handler))

    def test_callback_logs_in_and_sets_an_httponly_session_cookie(self):
        c, st = make(http=self._kakao())
        state = self._start(c)
        r = c.get("/api/auth/kakao/callback", params={"code": "C", "state": state})
        assert r.status_code == 302 and r.headers["location"] == "/?x=1"
        cookies = r.headers.get_list("set-cookie")
        session = next(x for x in cookies if x.startswith("pp_session="))
        assert "HttpOnly" in session and "SameSite=lax" in session
        assert st.users == {777: "카카오닉"}
        assert c.get("/api/auth/me").json() == {"social": True, "user": {"id": 777, "nickname": "카카오닉"}}

    def test_callback_rejects_forged_expired_or_foreign_state(self):
        c, _ = make(http=self._kakao())
        state = self._start(c)
        assert c.get("/api/auth/kakao/callback", params={"code": "C", "state": "garbage"}).status_code == 400
        assert c.get("/api/auth/kakao/callback", params={"code": "C"}).status_code == 400
        other, _ = make(http=self._kakao())  # nonce 쿠키가 없는 다른 브라우저(로그인 CSRF)
        assert other.get("/api/auth/kakao/callback", params={"code": "C", "state": state}).status_code == 400
        expired = make_token(SECRET, {"n": "x", "r": "/"}, 60, now=1000)
        c.cookies.set("pp_oauth", "x")
        assert c.get("/api/auth/kakao/callback", params={"code": "C", "state": expired}).status_code == 400

    def test_user_cancelling_returns_without_a_session(self):
        c, st = make(http=self._kakao())
        r = c.get("/api/auth/kakao/callback", params={"error": "access_denied", "state": self._start(c)})
        assert r.status_code == 302 and not any(x.startswith("pp_session=") for x in r.headers.get_list("set-cookie"))
        assert st.users == {}

    def test_kakao_failure_is_reported_without_a_session(self):
        c, _ = make(http=self._kakao(ok=False))
        r = c.get("/api/auth/kakao/callback", params={"code": "C", "state": self._start(c)})
        assert r.status_code == 502 and "만료" in r.json()["detail"]
        assert c.get("/api/auth/me").json()["user"] is None

    def test_me_ignores_tampered_cookie_and_logout_clears_it(self):
        c, _ = make()
        c.cookies.set(SESSION_COOKIE, make_token("z" * 40, {"sub": 1, "nick": "해커"}, 3600))  # 다른 비밀 키로 서명한 위조
        assert c.get("/api/auth/me").json()["user"] is None
        login_as(c, 5, "정상")
        assert c.get("/api/auth/me").json()["user"] == {"id": 5, "nickname": "정상"}
        assert c.post("/api/auth/logout").status_code == 403  # 헤더 없이는 거절
        r = c.post("/api/auth/logout", headers=H)
        assert r.status_code == 200 and "pp_session=" in r.headers["set-cookie"]


# ---------- 좋아요 ----------
class TestLikes:
    def test_requires_csrf_header_then_login(self):
        c, _ = make()
        assert c.post(f"/api/social/likes/{PLACE}").status_code == 403
        assert c.post(f"/api/social/likes/{PLACE}", headers=H).status_code == 401

    def test_toggle(self):
        c, _ = make()
        login_as(c, 1)
        assert c.post(f"/api/social/likes/{PLACE}", headers=H).json() == {"liked": True, "likes": 1}
        assert c.post(f"/api/social/likes/{PLACE}", headers=H).json() == {"liked": False, "likes": 0}
        c.post(f"/api/social/likes/{PLACE}", headers=H)
        login_as(c, 2)
        assert c.post(f"/api/social/likes/{PLACE}", headers=H).json() == {"liked": True, "likes": 2}

    def test_unknown_place_and_bad_id(self):
        c, _ = make()
        login_as(c)
        assert c.post(f"/api/social/likes/{uuid.uuid4()}", headers=H).status_code == 404
        assert c.post("/api/social/likes/not-a-uuid", headers=H).status_code == 422

    def test_summary_shows_my_like_only_when_logged_in(self):
        c, _ = make()
        login_as(c, 1)
        c.post(f"/api/social/likes/{PLACE}", headers=H)
        c.post(f"/api/social/comments/{PLACE}", json={"body": "좋아요"}, headers=H)
        mine = c.get("/api/social/summary", params={"ids": PLACE}).json()
        assert mine == {PLACE: {"likes": 1, "comments": 1, "liked": True}}
        anon, _ = make(store=c.app.router.routes and None)  # 새 앱·새 저장소 (비로그인)
        anon.cookies.clear()
        assert anon.get("/api/social/summary", params={"ids": PLACE}).json() == {PLACE: {"likes": 0, "comments": 0, "liked": False}}

    def test_summary_validates_ids_and_limits_the_request_size(self):
        c, _ = make()
        assert c.get("/api/social/summary", params={"ids": "nope"}).status_code == 422
        limit = social_routes.MAX_SUMMARY_IDS
        exactly = ",".join(str(uuid.uuid4()) for _ in range(limit))
        assert len(c.get("/api/social/summary", params={"ids": exactly}).json()) == limit
        too_many = exactly + "," + ",".join(str(uuid.uuid4()) for _ in range(20))
        assert c.get("/api/social/summary", params={"ids": too_many}).status_code == 422  # 너무 긴 요청은 거절
        dup = f"{PLACE},{PLACE},{PLACE}"
        assert list(c.get("/api/social/summary", params={"ids": dup}).json()) == [PLACE]  # 중복은 합친다
        assert c.get("/api/social/summary").json() == {}

    def test_summary_is_empty_when_social_is_disabled(self):
        c, _ = make(settings=Settings())
        assert c.get("/api/social/summary", params={"ids": PLACE}).json() == {}


# ---------- 댓글 ----------
class TestComments:
    def post(self, c, body, place=PLACE):
        return c.post(f"/api/social/comments/{place}", json={"body": body}, headers=H)

    def test_login_and_csrf_required(self):
        c, _ = make()
        assert c.post(f"/api/social/comments/{PLACE}", json={"body": "x"}).status_code == 403
        assert self.post(c, "x").status_code == 401

    def test_add_and_list_with_mine_flag(self):
        c, st = make()
        st.upsert_user(1, "민수")  # 실제로는 로그인 콜백이 users에 등록한다 (닉네임은 users 테이블에서 읽는다)
        st.upsert_user(2, "영희")
        login_as(c, 1, "민수")
        r = self.post(c, "  좋은 곳이에요 \x00 ")
        assert r.status_code == 201 and r.json()["body"] == "좋은 곳이에요" and r.json()["nickname"] == "민수" and r.json()["mine"]
        login_as(c, 2, "영희")
        listed = c.get(f"/api/social/comments/{PLACE}").json()["comments"]
        assert [x["body"] for x in listed] == ["좋은 곳이에요"] and listed[0]["mine"] is False

    def test_validation(self):
        c, _ = make()
        login_as(c)
        assert self.post(c, "").status_code == 422
        assert self.post(c, "   \n ").status_code == 422
        assert self.post(c, "가" * 301).status_code == 422
        assert self.post(c, "가" * 300).status_code == 201
        assert c.post(f"/api/social/comments/{PLACE}", json={}, headers=H).status_code == 422
        assert self.post(c, "x", place=str(uuid.uuid4())).status_code == 404

    def test_pagination_newest_first(self):
        c, _ = make()
        login_as(c)
        for i in range(5):
            self.post(c, f"댓글{i}")
        first = c.get(f"/api/social/comments/{PLACE}", params={"limit": 2}).json()
        assert [x["body"] for x in first["comments"]] == ["댓글4", "댓글3"] and first["next_before"]
        nxt = c.get(f"/api/social/comments/{PLACE}", params={"limit": 2, "before": first["next_before"]}).json()
        assert [x["body"] for x in nxt["comments"]] == ["댓글2", "댓글1"]
        assert c.get(f"/api/social/comments/{PLACE}", params={"before": "not-a-date"}).status_code == 422

    def test_delete_only_own(self):
        c, st = make()
        login_as(c, 1)
        cid = self.post(c, "내 댓글").json()["id"]
        login_as(c, 2)
        assert c.delete(f"/api/social/comments/{cid}", headers=H).status_code == 404  # 남의 댓글
        assert c.delete(f"/api/social/comments/{cid}").status_code == 403  # CSRF 헤더 없음
        login_as(c, 1)
        assert c.delete(f"/api/social/comments/{cid}", headers=H).json() == {"deleted": True}
        assert st.comments == {}

    def test_rate_limit(self):
        c, _ = make()
        login_as(c)
        codes = [self.post(c, f"c{i}").status_code for i in range(social_routes.LIMITS["comment"] + 1)]
        assert codes[:-1] == [201] * social_routes.LIMITS["comment"] and codes[-1] == 429
        login_as(c, 99)  # 다른 사용자는 영향 없음
        assert self.post(c, "다른 사람").status_code == 201


# ---------- 신고 · 관리자 ----------
class TestReportsAndAdmin:
    def setup(self):
        c, st = make()
        login_as(c, 1, "작성자")
        cid = c.post(f"/api/social/comments/{PLACE}", json={"body": "문제 댓글"}, headers=H).json()["id"]
        return c, st, cid

    def test_cannot_report_own_or_missing(self):
        c, _, cid = self.setup()
        assert c.post(f"/api/social/comments/{cid}/report", headers=H).status_code == 400
        login_as(c, 2)
        assert c.post(f"/api/social/comments/{uuid.uuid4()}/report", headers=H).status_code == 404
        assert c.post(f"/api/social/comments/{cid}/report").status_code == 403

    def test_hides_after_threshold_and_counts_each_person_once(self):
        c, st, cid = self.setup()
        login_as(c, 2)
        assert c.post(f"/api/social/comments/{cid}/report", headers=H).json() == {"reported": True, "hidden": False}
        assert c.post(f"/api/social/comments/{cid}/report", headers=H).json() == {"reported": False, "hidden": False}  # 같은 사람 중복
        for uid in range(3, 2 + REPORT_HIDE_THRESHOLD):
            login_as(c, uid)
            last = c.post(f"/api/social/comments/{cid}/report", headers=H).json()
        assert last["hidden"] is True
        assert c.get(f"/api/social/comments/{PLACE}").json()["comments"] == []  # 숨김 처리된 댓글은 목록에서 빠진다
        assert c.get("/api/social/summary", params={"ids": PLACE}).json()[PLACE]["comments"] == 0

    def test_admin_requires_token_and_can_delete(self):
        c, st, cid = self.setup()
        login_as(c, 2)
        c.post(f"/api/social/comments/{cid}/report", headers=H)
        assert c.get("/api/admin/reports").status_code == 401
        assert c.get("/api/admin/reports", headers={"X-Admin-Token": "wrong"}).status_code == 401
        listed = c.get("/api/admin/reports", headers={"X-Admin-Token": "ADMIN"}).json()["comments"]
        assert [x["id"] for x in listed] == [cid]
        assert c.delete(f"/api/admin/comments/{cid}", headers={"X-Admin-Token": "ADMIN"}).json() == {"deleted": True}
        assert c.delete(f"/api/admin/comments/{cid}", headers={"X-Admin-Token": "ADMIN"}).status_code == 404

    def test_admin_is_disabled_without_a_token(self):
        s = Settings(kakao_rest_key="R", session_secret=SECRET, supabase_url="u", supabase_service_key="k")
        c, _ = make(settings=s)
        assert c.get("/api/admin/reports", headers={"X-Admin-Token": "anything"}).status_code == 503


def test_database_errors_become_502_without_leaking_details():
    class Broken(FakeSocial):
        def place_exists(self, pid):
            raise RuntimeError("SECRET connection string postgres://user:pw@host")

    c, _ = make(store=Broken())
    login_as(c)
    r = c.post(f"/api/social/likes/{PLACE}", headers=H)
    assert r.status_code == 502 and "RuntimeError" in r.json()["detail"]
    assert "SECRET" not in r.text and "postgres" not in r.text
