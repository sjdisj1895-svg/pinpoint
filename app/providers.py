"""T2에 넣을 Raw Data 공급자."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings
from app.db import SpotStore
from app.harvest import Harvester
from app.schemas import T1Result


class RawDataProvider(Protocol):
    def fetch(self, t1: T1Result) -> list[dict[str, Any]]:
        """T1 조건(지역·카테고리·search_queries)에 맞는 원본 검색/API 결과를 반환."""


class FixtureProvider:
    """개발·테스트용: JSON 파일의 원본 데이터를 그대로 반환."""

    def __init__(self, path: Path):
        self.path = path

    def fetch(self, t1: T1Result) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8"))


class EmptyProvider:
    """데이터 소스 미연동 상태의 기본값."""

    def fetch(self, t1: T1Result) -> list[dict[str, Any]]:
        return []


# T2는 입력 전체를 다시 써서 출력하므로 후보가 많으면 응답이 길어져 느려지고 게이트웨이 시간 제한(504)에 걸린다.
T2_PER_CATEGORY = 8
T2_MAX_ROWS = 24
# T2가 판단에 쓰는 extra 항목만 남긴다 (이미지·수정일 등은 제외)
KEEP_EXTRA = {"sources", "unverified", "dates_confirmed", "url_kind", "showtimes_available", "now_showing_top",
              "chain", "dist_m", "posted_at", "venue", "image"}  # image는 모델에는 보이지 않고 Spot 조립에만 쓴다


def prepare_raw(rows: list[dict[str, Any]], per_category: int = T2_PER_CATEGORY, max_rows: int = T2_MAX_ROWS) -> list[dict]:
    """카테고리별로 신뢰도 높고 가까운 순으로 추리고, T2 판단에 불필요한 필드를 제거한다."""
    def dist(r: dict) -> float:
        return r.get("distance_m") if r.get("distance_m") is not None else (r.get("extra") or {}).get("dist_m") or 0.0

    picked: list[dict] = []
    count: dict[str, int] = {}
    for r in sorted(rows, key=lambda r: (-(r.get("confidence") or 0), dist(r))):
        cat = r.get("category")
        if count.get(cat, 0) >= per_category:
            continue
        count[cat] = count.get(cat, 0) + 1
        slim = {k: v for k, v in r.items() if k not in ("id", "extra", "province") and v not in (None, "", [], {})}
        extra = {k: v for k, v in (r.get("extra") or {}).items() if k in KEEP_EXTRA and v not in (None, "", [])}
        if extra:
            slim["extra"] = extra
        picked.append(slim)
        if len(picked) >= max_rows:
            break
    return picked


class DataLayerProvider:
    """DB(PostGIS) 우선 조회, 비어 있으면 커넥터로 수집해 저장한 뒤 다시 조회(read-through).
    DB가 없으면 수집 결과를 바로 반환한다. 데이터 신선도는 POST /harvest 정기 호출로 유지한다."""

    def __init__(self, harvester: Harvester, store: SpotStore | None):
        self.harvester, self.store = harvester, store

    def _rows(self, t1: T1Result) -> list[dict[str, Any]]:
        r = t1.target_region
        lat, lng = r.center_coords.lat, r.center_coords.lng
        cats = set(t1.requested_categories)
        target = t1.time_context.target_date

        if self.store:
            rows = self.store.search(lat, lng, r.radius_km, target, {c.value for c in cats})
            if rows:
                return rows
        result = self.harvester.harvest(
            lat=lat, lng=lng, radius_km=r.radius_km, target=target, region_name=r.city_district, categories=cats)
        if self.store:
            self.store.upsert(result.spots)
            return self.store.search(lat, lng, r.radius_km, target, {c.value for c in cats})
        return [sp.model_dump(mode="json", exclude_none=True) for sp in result.spots]

    def fetch(self, t1: T1Result) -> list[dict[str, Any]]:
        return prepare_raw(self._rows(t1))


def build_provider(settings: Settings, harvester: Harvester, store: SpotStore | None) -> RawDataProvider:
    if settings.has_store or settings.has_any_connector:
        return DataLayerProvider(harvester, store)
    return EmptyProvider()
