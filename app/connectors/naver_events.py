"""Connector D: 네이버 검색 API + 경량 LLM 파서 → 실시간 플리마켓·팝업스토어·가오픈 매장 추출기.

블로그/뉴스 스니펫은 신뢰할 수 없는 입력이므로 (1) 프롬프트에서 지시 무시를 명시하고, (2) 출력은 스키마로 검증하며,
(3) 원문 URL은 모델이 아니라 코드가 스니펫 index로 연결한다. 결과는 저신뢰(미검증)로 표시된다.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

import anthropic
import httpx
from pydantic import BaseModel, TypeAdapter

from app.connectors.kakao import KakaoLocal
from app.connectors.models import RawSpot, get_json, region_tag_from_address
from app.llm import ask_json
from app.schemas import Category
from app.stages.t3_curator import haversine_km

# 네이버 검색 API는 두 경로로 제공된다. 키를 발급받은 곳에 맞춰 NAVER_API_MODE로 고른다.
#  - hub: 네이버 클라우드 API Hub (X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY)
#  - developers: 네이버 개발자센터 (X-Naver-Client-Id / X-Naver-Client-Secret)
SEARCH_ENDPOINTS = {
    "hub": ("https://naverapihub.apigw.ntruss.com/search/v1/{kind}",
            ("X-NCP-APIGW-API-KEY-ID", "X-NCP-APIGW-API-KEY")),
    "developers": ("https://openapi.naver.com/v1/search/{kind}.json",
                   ("X-Naver-Client-Id", "X-Naver-Client-Secret")),
}
PARSER_PROMPT = (Path(__file__).parent.parent / "prompts" / "t6_event_parser.md").read_text(encoding="utf-8")
DEFAULT_PARSER_MODEL = "claude-haiku-5-5"
RECENT_DAYS = 30
MAX_SNIPPETS = 40
QUERY_SUFFIXES = ("플리마켓", "팝업스토어", "가오픈", "신규 오픈")


class ParsedEvent(BaseModel):
    source_index: int
    category: Literal["FLEA_MARKET", "NEW_OPEN"]
    title: str
    venue: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    operating_hours: str | None = None
    indoor_outdoor: Literal["INDOOR", "OUTDOOR", "BOTH"] | None = None


_EVENTS = TypeAdapter(list[ParsedEvent])


def clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


class NaverSearch:
    def __init__(self, client_id: str, client_secret: str, client: httpx.Client, mode: str = "hub"):
        if mode not in SEARCH_ENDPOINTS:
            raise ValueError(f"NAVER_API_MODE는 {sorted(SEARCH_ENDPOINTS)} 중 하나여야 합니다: {mode!r}")
        self.client = client
        self.url, (id_header, secret_header) = SEARCH_ENDPOINTS[mode]
        self.headers = {id_header: client_id, secret_header: client_secret}

    def search(self, kind: str, query: str, display: int = 20) -> list[dict]:
        """kind: blog | news. 최신순. 반환: {title, description, link, posted(date|None)}"""
        data = get_json(self.client, self.url.format(kind=kind),
                        params={"query": query, "display": display, "sort": "date"}, headers=self.headers)
        out = []
        for it in data.get("items", []):
            posted = None
            try:
                if it.get("postdate"):
                    posted = datetime.strptime(it["postdate"], "%Y%m%d").date()
                elif it.get("pubDate"):
                    posted = parsedate_to_datetime(it["pubDate"]).date()
            except (ValueError, TypeError):
                pass
            out.append({"title": clean(it.get("title", "")), "description": clean(it.get("description", "")),
                        "link": it.get("originallink") or it.get("link", ""), "posted": posted})
        return out


def _extract_array(text: str) -> list:
    import json
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("JSON 배열을 찾을 수 없음")
    return json.loads(text[start : end + 1])


def parse_events(
    snippets: list[dict], today: date, llm: anthropic.Anthropic | None = None, model: str | None = None
) -> list[ParsedEvent]:
    if not snippets:
        return []
    lines = [
        f"[{i}] 제목: {s['title']}\n    내용: {s['description']}\n    게시일: {s['posted'] or '불명'}"
        for i, s in enumerate(snippets)
    ]
    user = f"[오늘 날짜] {today.isoformat()}\n\n[스니펫]\n" + "\n".join(lines)

    def validate(text: str) -> list[ParsedEvent]:
        events = _EVENTS.validate_python(_extract_array(text))
        bad = [e.source_index for e in events if not 0 <= e.source_index < len(snippets)]
        if bad:
            raise ValueError(f"잘못된 source_index: {bad}")
        return events

    model = model or os.environ.get("PINPLAY_PARSER_MODEL", DEFAULT_PARSER_MODEL)
    return ask_json(PARSER_PROMPT, user, validate, llm, max_tokens=8000, model=model)


def harvest_events(
    naver: NaverSearch, kakao: KakaoLocal, region: str, lat: float, lng: float, radius_km: float,
    today: date, llm: anthropic.Anthropic | None = None, parser_model: str | None = None,
    categories: set[Category] | None = None,
) -> list[RawSpot]:
    wanted = categories or {Category.FLEA_MARKET, Category.NEW_OPEN}
    suffixes = [s for s in QUERY_SUFFIXES
                if (s in ("플리마켓", "팝업스토어") and Category.FLEA_MARKET in wanted)
                or (s in ("가오픈", "신규 오픈") and Category.NEW_OPEN in wanted)]

    snippets: dict[str, dict] = {}
    for suffix in suffixes:
        for kind in ("blog", "news"):
            for s in naver.search(kind, f"{region} {suffix}"):
                if s["link"] and s["posted"] and today - s["posted"] <= timedelta(days=RECENT_DAYS):
                    snippets.setdefault(s["link"], s)  # 링크 기준 중복 제거
    batch = sorted(snippets.values(), key=lambda s: s["posted"], reverse=True)[:MAX_SNIPPETS]

    out: list[RawSpot] = []
    for ev in parse_events(batch, today, llm, parser_model):
        snip = batch[ev.source_index]
        if ev.end_date and ev.end_date < today:
            continue  # 이미 끝난 행사
        geo = kakao.geocode(ev.venue) if ev.venue else None
        if not geo or haversine_km(lat, lng, geo[0], geo[1]) > radius_km * 1.5:
            continue  # 위치 확인 불가/엉뚱한 지역
        if len(geo[2].split()) <= 2:
            continue  # '강원특별자치도 춘천시'처럼 시·군 단위뿐이면 정확한 마커를 찍을 수 없다
        category = Category(ev.category)
        out.append(RawSpot(
            source="naver", source_id=hashlib.sha1(f"{snip['link']}|{ev.title}".encode()).hexdigest()[:12],
            category=category, title=ev.title, subtitle=f"{snip['posted']} 게시글 기반 (미검증)",
            address=geo[2], lat=geo[0], lng=geo[1], region_tag=region_tag_from_address(geo[2]),
            start_date=ev.start_date, end_date=ev.end_date, operating_hours=ev.operating_hours,
            indoor_outdoor=ev.indoor_outdoor, source_url=snip["link"],
            confidence=0.5 if ev.start_date and ev.end_date else 0.4,
            extra={"unverified": True, "posted_at": snip["posted"].isoformat(),
                   "dates_confirmed": bool(ev.start_date and ev.end_date), "evidence_title": snip["title"]},
        ))
    return out
