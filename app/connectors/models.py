"""커넥터 공통 모델/유틸. 모든 소스는 RawSpot으로 정규화된 뒤 병합·저장·T2 입력으로 쓰인다."""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from app.schemas import Category

PROVINCE_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "전남광주통합특별시": "전남광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북", "충청남도": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주",
}
# 소스별 기본 유효기간(종료일이 없는 항목이 영원히 남지 않도록)
DEFAULT_TTL_DAYS = {"tourapi": 30, "mois": 30, "kobis_kakao": 30, "naver": 14}


class ConnectorError(RuntimeError):
    """외부 API 호출 실패. 메시지에 서비스키가 섞이지 않도록 URL 파라미터는 넣지 않는다."""


class RawSpot(BaseModel):
    source: str  # tourapi | mois | kobis_kakao | naver
    source_id: str
    category: Category
    title: str = Field(min_length=1)
    subtitle: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    region_tag: str = ""
    start_date: date | None = None
    end_date: date | None = None
    operating_hours: str | None = None
    indoor_outdoor: str | None = None  # INDOOR | OUTDOOR | BOTH
    source_url: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    extra: dict[str, Any] = {}

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: float | None) -> float | None:
        return v if v is not None and 33.0 <= v <= 39.0 else None

    @field_validator("lng")
    @classmethod
    def _lng(cls, v: float | None) -> float | None:
        return v if v is not None and 124.0 <= v <= 132.0 else None

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None

    def dedupe_key(self) -> str:
        norm = norm_title(self.title)
        if self.category == Category.MOVIE and self.has_coords:
            raw = f"MOVIE|{norm}|{round(self.lat, 3)}|{round(self.lng, 3)}"
        else:
            year = self.start_date.year if self.start_date else ""
            raw = f"{self.category.value}|{norm}|{self.region_tag}|{year}"
        return hashlib.sha1(raw.encode()).hexdigest()

    def expires_at(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        if self.end_date:
            return datetime.combine(self.end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        return now + timedelta(days=DEFAULT_TTL_DAYS.get(self.source, 14))

    def to_row(self) -> dict[str, Any]:
        """Supabase upsert_spots RPC 입력 형식."""
        sources = sorted({self.source, *self.extra.get("sources", {}).keys()})
        return {
            "dedupe_key": self.dedupe_key(), "category": self.category.value, "title": self.title,
            "subtitle": self.subtitle, "address": self.address, "region_tag": self.region_tag,
            "province": self.region_tag.split()[0] if self.region_tag else None,
            "lat": self.lat, "lng": self.lng,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "operating_hours": self.operating_hours, "indoor_outdoor": self.indoor_outdoor,
            "sources": sources, "source_url": self.source_url, "confidence": self.confidence,
            "extra": self.extra, "expires_at": self.expires_at().isoformat(),
        }


def norm_title(title: str) -> str:
    """중복 판별용 정규화: 괄호·회차·연도·주년·공백·특수문자 제거."""
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", title)
    t = re.sub(r"제?\s*\d+\s*(회|차)|20\d{2}\s*년?|\d+\s*주년", "", t)
    return re.sub(r"[^0-9a-z가-힣]", "", t.lower())


def region_tag_from_address(addr: str | None) -> str:
    """'강원특별자치도 춘천시 ...' -> '강원 춘천' (프론트 광역 집계가 첫 토큰을 쓴다)."""
    tokens = (addr or "").split()
    if not tokens:
        return ""
    prov = PROVINCE_SHORT.get(tokens[0], tokens[0])
    return f"{prov} {tokens[1]}" if len(tokens) > 1 else prov


def to_float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_date(v: Any) -> date | None:
    """'20261018', '2026-10-18', '2026.10.18' 등 → date. 숫자 8자리 이상이 아니면 None."""
    digits = re.sub(r"\D", "", str(v or ""))
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date() if len(digits) >= 8 else None
    except ValueError:
        return None


def get_json(
    client: httpx.Client, url: str, *, params: dict | None = None, headers: dict | None = None, retries: int = 2
) -> Any:
    """GET + 재시도(429/5xx/네트워크). 응답이 JSON이 아니면(공공데이터 키 오류는 XML) 명확한 오류로 변환."""
    last: str = ""
    for attempt in range(retries + 1):
        try:
            r = client.get(url, params=params, headers=headers, timeout=10)
        except httpx.TransportError as e:
            last = type(e).__name__
        else:
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                last = f"HTTP {r.status_code}"
            elif r.status_code >= 400:
                raise ConnectorError(f"{url.split('?')[0]} -> HTTP {r.status_code}")
            else:
                try:
                    return r.json()
                except ValueError:
                    raise ConnectorError(f"{url.split('?')[0]} 응답이 JSON이 아님 (인증키 미등록/만료 가능)")
        if attempt < retries:
            time.sleep(0.5 * 2**attempt)
    raise ConnectorError(f"{url.split('?')[0]} 호출 실패: {last}")


def data_go_items(payload: Any) -> list[dict]:
    """공공데이터포털 공통 응답(response.header/body.items)에서 항목 리스트 추출."""
    resp = (payload or {}).get("response") or {}
    code = str((resp.get("header") or {}).get("resultCode", "0000"))
    if code not in ("0000", "00"):
        raise ConnectorError(f"공공데이터 API 오류 {code}: {(resp.get('header') or {}).get('resultMsg', '')}")
    items = (resp.get("body") or {}).get("items")
    if not items:
        return []
    item = items.get("item") if isinstance(items, dict) else items
    if not item:
        return []
    return item if isinstance(item, list) else [item]
