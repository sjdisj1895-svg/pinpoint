"""Connector B: 전국문화축제표준데이터(파일 데이터) + TourAPI 축제 병합(Upsert/중복 제거).

이 데이터셋은 data.go.kr에서 CSV로 내려받는 파일 데이터다. 내려받은 파일을 MOIS_FESTIVAL_FILE 경로에 두면
읽어서 사용한다 (인코딩은 UTF-8/CP949 자동 판별, 컬럼명은 한글·영문 모두 허용).
"""
from __future__ import annotations

import csv
import io
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from app.connectors.models import RawSpot, norm_title, parse_date, region_tag_from_address, to_float
from app.schemas import Category
from app.stages.t3_curator import haversine_km

SAME_PLACE_KM = 5.0
FUZZY_TITLE = 0.85
SOURCE_PRIORITY = {"tourapi": 2, "mois": 1}

# 표준 컬럼명(영문 API형/한글 CSV형)별 별칭
ALIASES = {
    "title": ("fstvlNm", "축제명"),
    "venue": ("opar", "개최장소"),
    "content": ("fstvlCo", "축제내용"),
    "start": ("fstvlStartDate", "축제시작일자"),
    "end": ("fstvlEndDate", "축제종료일자"),
    "host": ("mnnstNm", "주관기관명", "auspcInsttNm", "주최기관명"),
    "tel": ("phoneNumber", "전화번호"),
    "homepage": ("homepageUrl", "홈페이지주소"),
    "road": ("rdnmadr", "소재지도로명주소"),
    "lot": ("lnmadr", "소재지지번주소"),
    "lat": ("latitude", "위도"),
    "lng": ("longitude", "경도"),
    "inst": ("insttCode", "제공기관코드"),
    "ref": ("referenceDate", "데이터기준일자"),
}


def _get(row: dict, field: str):
    for k in ALIASES[field]:
        v = row.get(k)
        if v not in (None, "") and str(v).strip():
            return str(v).strip()
    return None


def read_rows(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: UTF-8/CP949로 읽을 수 없는 파일")


class MoisFestivalFile:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._cache: tuple[float, list[dict]] | None = None

    def exists(self) -> bool:
        return self.path.is_file()

    def _rows(self) -> list[dict]:
        mtime = self.path.stat().st_mtime
        if not self._cache or self._cache[0] != mtime:  # 파일이 바뀌면 다시 읽는다
            self._cache = (mtime, read_rows(self.path))
        return self._cache[1]

    @staticmethod
    def convert(it: dict) -> RawSpot | None:
        title = _get(it, "title")
        if not title:
            return None
        addr = _get(it, "road") or _get(it, "lot")
        homepage = _get(it, "homepage")
        content = _get(it, "content")
        return RawSpot(
            source="mois", source_id=f"{_get(it, 'inst') or ''}:{norm_title(title)}", category=Category.FESTIVAL,
            title=title, subtitle=content[:80] if content else None, address=addr,
            lat=to_float(_get(it, "lat")), lng=to_float(_get(it, "lng")), region_tag=region_tag_from_address(addr),
            start_date=parse_date(_get(it, "start")), end_date=parse_date(_get(it, "end")),
            indoor_outdoor="OUTDOOR", source_url=homepage if homepage and homepage.startswith("http") else None,
            confidence=0.75 if homepage else 0.65,  # 지자체 공공데이터
            extra={"venue": _get(it, "venue"), "host": _get(it, "host"), "tel": _get(it, "tel"),
                   "reference_date": _get(it, "ref")},
        )

    def fetch_festivals(self, target: date, lat: float, lng: float, radius_km: float, region_name: str = "") -> list[RawSpot]:
        out: list[RawSpot] = []
        for row in self._rows():
            s = self.convert(row)
            if not s or not s.start_date or not s.end_date or not (s.start_date <= target <= s.end_date):
                continue
            if s.has_coords:
                if haversine_km(lat, lng, s.lat, s.lng) > radius_km:
                    continue
            elif not (region_name and region_name in (s.address or "")):
                continue  # 좌표가 없으면 주소에 요청 지역명(예: 춘천시)이 있을 때만 남겨 병합 단계에서 좌표 보완 기회를 준다
            out.append(s)
        return out


def _overlap(a: RawSpot, b: RawSpot) -> bool:
    if not (a.start_date and a.end_date and b.start_date and b.end_date):
        return False
    return a.start_date <= b.end_date and b.start_date <= a.end_date


def _same_festival(a: RawSpot, b: RawSpot) -> bool:
    if not _overlap(a, b):
        return False
    na, nb = norm_title(a.title), norm_title(b.title)
    if not na or not nb:
        return False
    near = (not a.has_coords or not b.has_coords) or haversine_km(a.lat, a.lng, b.lat, b.lng) <= SAME_PLACE_KM
    if not near:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= FUZZY_TITLE


def _merge_pair(base: RawSpot, other: RawSpot) -> RawSpot:
    """base(우선순위 높은 쪽)의 빈 필드를 other로 채우고 출처/신뢰도를 합산."""
    data = base.model_dump()
    for f in ("subtitle", "address", "lat", "lng", "operating_hours", "source_url"):
        if data[f] in (None, ""):
            data[f] = getattr(other, f)
    if not data["region_tag"]:
        data["region_tag"] = other.region_tag
    sources = dict(base.extra.get("sources") or {base.source: base.source_id})
    sources.update(other.extra.get("sources") or {other.source: other.source_id})
    data["extra"] = {**other.extra, **base.extra, "sources": sources}
    data["confidence"] = min(0.95, max(base.confidence, other.confidence) + 0.1)  # 복수 출처 교차 확인
    return RawSpot.model_validate(data)


def merge_festivals(*groups: list[RawSpot]) -> list[RawSpot]:
    """여러 소스의 축제를 중복 제거하며 병합(Upsert). 소스 우선순위가 높은 항목을 기준으로 삼는다."""
    spots = sorted((s for g in groups for s in g), key=lambda s: -SOURCE_PRIORITY.get(s.source, 0))
    merged: list[RawSpot] = []
    for s in spots:
        for i, m in enumerate(merged):
            if _same_festival(m, s):
                merged[i] = _merge_pair(m, s)
                break
        else:
            merged.append(s)
    return merged
