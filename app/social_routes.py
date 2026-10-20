"""로그인(카카오)·좋아요·댓글·신고 라우트. main.py가 build_router()로 붙인다.

보안 원칙
- 로그인 상태는 HttpOnly·SameSite=Lax 쿠키(서명된 토큰). 자바스크립트가 토큰을 읽을 수 없다.
- 상태를 바꾸는 요청(POST/DELETE)은 커스텀 헤더(X-PinPlay)를 요구한다 → 다른 사이트가 우리 쿠키로 요청을 위조(CSRF)할 수 없다.
- 로그인 state는 서명 + 브라우저 쿠키의 nonce와 일치해야 하고, 돌아갈 경로는 같은 사이트 안의 경로만 허용한다.
- 댓글은 길이 제한·제어 문자 제거, 사용자별 요청 제한. 신고 3건이면 자동 숨김, 삭제는 본인과 관리자만.
"""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app import auth
from app.config import Settings
from app.ratelimit import RateLimiter, client_ip
from app.session import make_token, read_token
from app.social import MAX_COMMENT, SocialStore, clean_comment

log = logging.getLogger("pinplay")
SESSION_COOKIE = "pp_session"
OAUTH_COOKIE = "pp_oauth"
SESSION_TTL = 30 * 24 * 3600
OAUTH_TTL = 600
MAX_SUMMARY_IDS = 60
CSRF_HEADER = "x-pinplay"

limiter = RateLimiter()  # 사용자별 요청 제한 (서버리스에서는 인스턴스마다 따로 센다)
LIMITS = {"comment": 10, "like": 60, "report": 20}  # 10분당 횟수


class SessionUser(BaseModel):
    id: int
    nickname: str


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)  # 정리한 뒤 300자 이하인지 다시 확인한다


def safe_return_path(path: str | None) -> str:
    """로그인 뒤 돌아갈 경로. 같은 사이트 안의 경로만 허용해 외부 주소로 보내는 오픈 리다이렉트를 막는다."""
    p = (path or "/").strip()
    if not p.startswith("/") or p.startswith("//") or "\\" in p or "\n" in p or "\r" in p:
        return "/"
    return p


def parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(422, "올바르지 않은 ID입니다.")


def site_base(request: Request, settings: Settings) -> str:
    if settings.site_url:
        return settings.site_url
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def is_https(request: Request, settings: Settings) -> bool:
    return site_base(request, settings).startswith("https://")


def build_router(
    get_settings: Callable[[], Settings],
    get_social: Callable[[], SocialStore | None],
    http: Callable[[], httpx.Client] = lambda: httpx.Client(),
) -> APIRouter:
    router = APIRouter()

    # ---------- 의존성 ----------
    def enabled() -> Settings:
        s = get_settings()
        if not s.social_enabled:
            raise HTTPException(503, "좋아요·댓글 기능이 설정되지 않았습니다.")
        return s

    def current_user(request: Request) -> SessionUser | None:
        s = get_settings()
        data = read_token(s.session_secret, request.cookies.get(SESSION_COOKIE))
        if not data or not isinstance(data.get("sub"), int):
            return None
        return SessionUser(id=data["sub"], nickname=str(data.get("nick") or auth.DEFAULT_NICKNAME))

    def require_user(user: SessionUser | None = Depends(current_user)) -> SessionUser:
        if user is None:
            raise HTTPException(401, "로그인이 필요합니다.")
        return user

    def require_csrf(x_pinplay: str | None = Header(default=None)) -> None:
        if x_pinplay != "1":
            raise HTTPException(403, "잘못된 요청입니다.")

    def store() -> SocialStore:
        st = get_social()
        if st is None:
            raise HTTPException(503, "데이터베이스가 설정되지 않았습니다.")
        return st

    def throttle(kind: str, user: SessionUser) -> None:
        if not limiter.allow(f"{kind}:{user.id}", LIMITS[kind]):
            raise HTTPException(429, "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")

    def db_error(e: Exception) -> HTTPException:
        log.exception("소셜 DB 오류")
        return HTTPException(502, f"처리하지 못했어요 ({type(e).__name__}). 소셜 DB 설정(supabase/social.sql 실행)을 확인하세요.")

    # ---------- 로그인 ----------
    @router.get("/auth/me")
    def me(user: SessionUser | None = Depends(current_user)):
        s = get_settings()
        return {"social": s.social_enabled, "user": user.model_dump() if user else None}

    @router.get("/auth/kakao/login")
    def kakao_login(request: Request, next: str = Query("/", alias="return")):
        s = enabled()
        nonce = secrets.token_urlsafe(16)
        state = make_token(s.session_secret, {"n": nonce, "r": safe_return_path(next)}, OAUTH_TTL)
        redirect_uri = site_base(request, s) + "/api/auth/kakao/callback"
        resp = RedirectResponse(auth.authorize_url(s.kakao_rest_key, redirect_uri, state), status_code=302)
        resp.set_cookie(OAUTH_COOKIE, nonce, max_age=OAUTH_TTL, httponly=True, secure=is_https(request, s), samesite="lax", path="/")
        return resp

    @router.get("/auth/kakao/callback")
    def kakao_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        s = enabled()
        data = read_token(s.session_secret, state)
        nonce = request.cookies.get(OAUTH_COOKIE)
        # state가 서명·만료 검사를 통과하고, 이 브라우저가 로그인을 시작한 것(nonce 일치)이어야 한다
        if not data or not nonce or not secrets.compare_digest(str(data.get("n", "")), nonce):
            raise HTTPException(400, "로그인 요청이 올바르지 않거나 만료되었습니다. 다시 시도해 주세요.")
        back = safe_return_path(data.get("r"))
        if error or not code:  # 사용자가 동의 화면에서 취소한 경우
            resp = RedirectResponse(back, status_code=302)
            resp.delete_cookie(OAUTH_COOKIE, path="/")
            return resp
        client = http()
        try:
            redirect_uri = site_base(request, s) + "/api/auth/kakao/callback"
            token = auth.exchange_code(client, s.kakao_rest_key, redirect_uri, code, s.kakao_client_secret)
            kakao = auth.fetch_profile(client, token)
            store().upsert_user(kakao.id, kakao.nickname)
        except auth.AuthError as e:
            raise HTTPException(502, str(e))
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)
        session = make_token(s.session_secret, {"sub": kakao.id, "nick": kakao.nickname}, SESSION_TTL)
        resp = RedirectResponse(back, status_code=302)
        resp.set_cookie(SESSION_COOKIE, session, max_age=SESSION_TTL, httponly=True, secure=is_https(request, s), samesite="lax", path="/")
        resp.delete_cookie(OAUTH_COOKIE, path="/")
        return resp

    @router.post("/auth/logout", dependencies=[Depends(require_csrf)])
    def logout(response: Response):
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    # ---------- 좋아요 ----------
    @router.get("/social/summary")
    def summary(ids: str = Query("", max_length=60 * 37), user: SessionUser | None = Depends(current_user)):
        """여러 장소의 좋아요 수·댓글 수·내가 눌렀는지. 카드 목록에 한 번에 표시한다. 소셜이 꺼져 있으면 빈 결과."""
        if not get_settings().social_enabled:
            return {}
        place_ids = list(dict.fromkeys(parse_uuid(i) for i in ids.split(",") if i.strip()))[:MAX_SUMMARY_IDS]
        try:
            return store().summary(place_ids, user.id if user else None)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)

    @router.post("/social/likes/{place_id}", dependencies=[Depends(require_csrf)])
    def toggle_like(place_id: str, user: SessionUser = Depends(require_user)):
        enabled()
        pid = parse_uuid(place_id)
        throttle("like", user)
        try:
            st = store()
            if not st.place_exists(pid):
                raise HTTPException(404, "존재하지 않는 장소입니다.")
            return st.toggle_like(pid, user.id)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)

    # ---------- 댓글 ----------
    @router.get("/social/comments/{place_id}")
    def list_comments(
        place_id: str, limit: int = Query(20, ge=1, le=50), before: str | None = Query(None, max_length=40),
        user: SessionUser | None = Depends(current_user),
    ):
        if not get_settings().social_enabled:
            return {"comments": [], "next_before": None}
        pid = parse_uuid(place_id)
        if before:
            try:
                datetime.fromisoformat(before.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(422, "올바르지 않은 날짜입니다.")
        try:
            rows = store().list_comments(pid, user.id if user else None, limit, before)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)
        return {"comments": rows, "next_before": rows[-1]["created_at"] if len(rows) == limit else None}

    @router.post("/social/comments/{place_id}", dependencies=[Depends(require_csrf)], status_code=201)
    def add_comment(place_id: str, body: CommentIn, user: SessionUser = Depends(require_user)):
        enabled()
        pid = parse_uuid(place_id)
        text = clean_comment(body.body)
        if not text:
            raise HTTPException(422, "내용을 입력해 주세요.")
        if len(text) > MAX_COMMENT:
            raise HTTPException(422, f"댓글은 {MAX_COMMENT}자까지 쓸 수 있어요.")
        throttle("comment", user)
        try:
            st = store()
            if not st.place_exists(pid):
                raise HTTPException(404, "존재하지 않는 장소입니다.")
            return st.add_comment(pid, user.id, text)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)

    @router.delete("/social/comments/{comment_id}", dependencies=[Depends(require_csrf)])
    def delete_comment(comment_id: str, user: SessionUser = Depends(require_user)):
        enabled()
        cid = parse_uuid(comment_id)
        try:
            if not store().delete_comment(cid, user.id):
                raise HTTPException(404, "삭제할 수 있는 댓글이 아닙니다.")  # 없거나 남의 댓글
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)
        return {"deleted": True}

    @router.post("/social/comments/{comment_id}/report", dependencies=[Depends(require_csrf)])
    def report_comment(comment_id: str, user: SessionUser = Depends(require_user)):
        enabled()
        cid = parse_uuid(comment_id)
        throttle("report", user)
        try:
            st = store()
            author = st.comment_author(cid)
            if author is None:
                raise HTTPException(404, "존재하지 않는 댓글입니다.")
            if author == user.id:
                raise HTTPException(400, "내 댓글은 신고할 수 없어요. 삭제해 주세요.")
            return st.report_comment(cid, user.id)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)

    # ---------- 관리자 (ADMIN_TOKEN) ----------
    def admin(x_admin_token: str | None = Header(default=None)) -> None:
        token = get_settings().admin_token
        if not token:
            raise HTTPException(503, "ADMIN_TOKEN이 설정되지 않아 비활성화되어 있습니다.")
        if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
            raise HTTPException(401, "인증 실패")

    @router.get("/admin/reports", dependencies=[Depends(admin)])
    def admin_reports():
        """신고가 있는 댓글 (신고 많은 순). 자동 숨김된 것(hidden=true)도 포함."""
        try:
            return {"comments": store().admin_reports()}
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)

    @router.delete("/admin/comments/{comment_id}", dependencies=[Depends(admin)])
    def admin_delete(comment_id: str):
        cid = parse_uuid(comment_id)
        try:
            if not store().admin_delete(cid):
                raise HTTPException(404, "존재하지 않는 댓글입니다.")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise db_error(e)
        return {"deleted": True}

    return router
