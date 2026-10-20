import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from app import explore as explore_mod  # noqa: E402
from app import health as health_mod  # noqa: E402
from app import pipeline as pipeline_mod  # noqa: E402  (.env 로드 후 import)
from app.config import Settings, load_settings  # noqa: E402
from app.db import SpotStore  # noqa: E402
from app.harvest import Harvester  # noqa: E402
from app.llm import LLMOutputError, LLMServiceError  # noqa: E402
from app.providers import build_provider  # noqa: E402
from app.ratelimit import limit_llm  # noqa: E402
from app.social import SocialStore  # noqa: E402
from app.social_routes import build_router as build_social_router  # noqa: E402
from app.schemas import Category, ParseRequest, RerouteRequest, RerouteResponse, T1Result  # noqa: E402
from app.stages.t1_intent import parse_intent  # noqa: E402
from app.stages.t5_rerouter import reroute  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 첫 방문자가 6초 가량 기다리지 않도록 경남 둘러보기를 백그라운드에서 미리 불러 둔다 (실패해도 서버는 정상 시작).
    # 서버리스(Vercel)는 인스턴스가 수시로 새로 뜨고 응답 뒤에 백그라운드 작업이 멈출 수 있어 건너뛴다.
    def warm() -> None:
        try:
            store = get_store()
            if store:
                explore_mod.explore(store, "경남", date.today())
        except Exception:  # noqa: BLE001
            pass

    if not os.environ.get("VERCEL"):
        threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="PinPlay", lifespan=lifespan)
api = APIRouter()  # 루트와 /api 양쪽에 노출 (프론트는 /api, 직접 호출은 루트)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@lru_cache
def get_store() -> SpotStore | None:
    s = get_settings()
    return SpotStore.from_settings(s) if s.has_store else None


@lru_cache
def get_harvester() -> Harvester:
    return Harvester(get_settings(), httpx.Client())


@lru_cache
def get_http() -> httpx.Client:
    return httpx.Client()  # 카카오 로그인 서버 통신용 (스레드 간에 공유해도 안전)


def get_social() -> SocialStore | None:
    """좋아요·댓글 저장소. 동시 요청이 같은 DB 연결을 공유하면 소켓 오류가 나므로 스레드별 연결을 쓴다."""
    st = get_store()
    return SocialStore(st.for_thread().client) if st else None


# T2가 쓸 데이터 공급자 (키가 하나도 없으면 EmptyProvider)
pipeline_mod.provider = build_provider(get_settings(), get_harvester(), get_store())


def _call(fn, req):
    try:
        return fn(req)
    except LLMOutputError as e:
        raise HTTPException(422, str(e))
    except LLMServiceError as e:
        if e.kind == "rate_limit":
            raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도하세요.")
        if e.kind == "auth":
            raise HTTPException(500, "LLM 인증 설정을 확인하세요 (ANTHROPIC_API_KEY 또는 API_KEY/API_BASE/API_MODEL).")
        raise HTTPException(502, str(e))


# LLM 비용이 드는 라우트에는 IP별 요청 제한을 건다 (app/ratelimit.py)
@api.post("/parse", response_model=T1Result, dependencies=[Depends(limit_llm)])
def parse(req: ParseRequest):
    return _call(parse_intent, req)


@api.post("/pipeline", dependencies=[Depends(limit_llm)])
def pipeline(req: ParseRequest):
    return _call(pipeline_mod.run_pipeline, req)


@api.post("/reroute", response_model=RerouteResponse, dependencies=[Depends(limit_llm)])
def reroute_endpoint(req: RerouteRequest):
    return _call(reroute, req)


@api.get("/config")
def public_config(response: Response):
    """화면이 필요로 하는 공개 설정. 카카오맵 JavaScript 키는 원래 브라우저에 공개되는 키이므로 이것만 내보낸다
    (다른 키는 절대 포함하지 않는다). 키가 없으면 null이고 화면은 OpenFreeMap으로 동작한다.
    social: 좋아요·댓글(카카오 로그인)에 필요한 설정이 모두 있는지. false면 화면에서 이 기능을 숨긴다."""
    response.headers["Cache-Control"] = "public, max-age=300"
    s = get_settings()
    return {"kakao_js_key": s.kakao_js_key or None, "social": s.social_enabled}


@api.get("/health")
def health(response: Response):
    """배포 설정 진단. 키 값은 싣지 않고 형태(종류·길이·공백 여부 등)와 DB 접속 결과만 알려 준다."""
    s = get_settings()
    report: dict = {"supabase": health_mod.supabase_report(s), "llm": health_mod.llm_report(),
                    "keys_present": health_mod.keys_present(s), "on_vercel": bool(os.environ.get("VERCEL"))}
    store = get_store()
    if not store:
        report["db_check"] = "Supabase 설정 없음"
    else:
        try:
            store.search(35.2, 128.6, 1, date.today(), None, 1)
            report["db_check"] = "ok"
        except Exception as e:  # noqa: BLE001
            logging.getLogger("pinplay").exception("health DB 점검 실패")
            report["db_check"] = f"실패: {type(e).__name__} {getattr(e, 'code', '') or ''}".strip()
    response.headers["Cache-Control"] = "no-store"
    return report


def _db_failure(e: Exception) -> HTTPException:
    """DB 오류를 원인이 보이는 502로 바꾼다. 로그에는 전체를 남기고, 응답에는 오류 종류와 코드만 담는다(키·주소 제외)."""
    logging.getLogger("pinplay").exception("DB 조회 실패")
    code = getattr(e, "code", None)
    msg = str(getattr(e, "message", "") or "")[:80]  # PostgREST 오류 메시지 (예: Invalid API key)
    detail = f"데이터베이스 조회에 실패했어요 ({type(e).__name__}{f': {code}' if code else ''})"
    return HTTPException(502, f"{detail} {msg}".strip())


@api.get("/spots/search")
def spots_search(
    lat: float = Query(ge=33, le=39),
    lng: float = Query(ge=124, le=132),
    radius_km: float = Query(3, gt=0, le=50),
    on: date | None = None,
    categories: str | None = Query(None, description="쉼표 구분, 예: FESTIVAL,MOVIE"),
    limit: int = Query(100, ge=1, le=500),
):
    """DB(PostGIS)의 진행 중 스팟 반경 검색. 공개 라우트이므로 외부 API를 호출하지 않고 저장된 데이터만 조회한다."""
    store = get_store()
    if not store:
        raise HTTPException(503, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY가 설정되지 않았습니다.")
    try:
        cats = {Category(c.strip()).value for c in categories.split(",")} if categories else None
    except ValueError:
        raise HTTPException(422, "알 수 없는 카테고리입니다.")
    try:
        local = store.for_thread() if hasattr(store, "for_thread") else store  # 동시 요청마다 DB 연결을 따로 쓴다
        rows = local.search(lat, lng, radius_km, on or date.today(), cats, limit)
    except Exception as e:  # noqa: BLE001
        raise _db_failure(e)
    return {"count": len(rows), "spots": rows}


@api.get("/explore")
def explore_endpoint(
    response: Response,
    province: str = Query("경남", max_length=10),
    on: date | None = None,
    categories: str | None = Query(None, description="쉼표 구분, 예: FESTIVAL,TRAVEL_SPOT"),
    q: str = Query("", max_length=60, description="키워드 검색(공백으로 나눈 모든 단어가 맞아야 함). 이름·요약·주소·지역·분류에서 찾는다"),
    region: str = Query("", max_length=20, description="시·군 필터, 예: 진주시"),
    limit: int = Query(300, ge=1, le=500),
):
    """권역 둘러보기·내부 검색: DB에 저장된 진행 중 스팟을 AI 없이 바로 반환 (외부 API 호출 없음)."""
    store = get_store()
    if not store:
        raise HTTPException(503, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY가 설정되지 않았습니다.")
    try:
        cats = {Category(c.strip()).value for c in categories.split(",")} if categories else None
    except ValueError:
        raise HTTPException(422, "알 수 없는 카테고리입니다.")
    try:
        result = explore_mod.explore(store, province, on or date.today(), cats, limit, q, region.strip())
    except KeyError:
        raise HTTPException(404, f"지원하지 않는 권역입니다: {province}")
    except Exception as e:  # noqa: BLE001
        raise _db_failure(e)
    # CDN(Vercel Edge)이 15분간 응답을 보관해 함수 호출·DB 조회 없이 바로 돌려준다. 만료 뒤에도 1시간은 오래된 응답을 먼저 주고 뒤에서 갱신한다.
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    return result


class HarvestRequest(BaseModel):
    lat: float = Field(ge=33, le=39)
    lng: float = Field(ge=124, le=132)
    radius_km: float = Field(10, gt=0, le=50)
    region_name: str = Field(min_length=1, max_length=40)  # 네이버 검색어에 쓰는 지역명 (예: 춘천시)
    on: date | None = None
    categories: list[Category] | None = None


@api.post("/harvest")
def harvest(req: HarvestRequest, x_admin_token: str | None = Header(default=None)):
    """수집 실행 → DB upsert. 외부 API 쿼터/LLM 비용이 드는 작업이라 ADMIN_TOKEN으로 보호한다."""
    token = get_settings().admin_token
    if not token:
        raise HTTPException(503, "ADMIN_TOKEN이 설정되지 않아 비활성화되어 있습니다.")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(401, "인증 실패")
    result = get_harvester().harvest(
        lat=req.lat, lng=req.lng, radius_km=req.radius_km, target=req.on or date.today(),
        region_name=req.region_name, categories=set(req.categories) if req.categories else None)
    store = get_store()
    upserted = store.upsert(result.spots) if store else None
    return {"collected": len(result.spots), "upserted": upserted, "counts": result.counts,
            "errors": result.errors, "skipped": result.skipped, "dropped_no_coords": result.dropped_no_coords}


api.include_router(build_social_router(get_settings, get_social, get_http))  # 로그인·좋아요·댓글·신고

app.include_router(api)
app.include_router(api, prefix="/api")

# 빌드된 프론트엔드(npm run build)가 있으면 같은 서버에서 서빙. API 라우트 뒤에 마운트해야 가려지지 않는다.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
