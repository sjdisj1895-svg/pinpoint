"""Connector A: 한국관광공사 TourAPI 4.0 (KorService). 축제(searchFestival) + 위치기반 관광지(locationBasedList)."""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

import httpx

from app.connectors.models import (
    RawSpot, data_go_items, get_json, parse_date, region_tag_from_address, to_float,
)
from app.schemas import Category
from app.stages.t3_curator import haversine_km

# contentTypeId -> 카테고리 (15 행사/공연/축제 · 12 관광지 · 14 문화시설)
CONTENT_TYPE = {12: Category.TRAVEL_SPOT, 14: Category.TRAVEL_SPOT, 15: Category.FESTIVAL}
FESTIVAL_LOOKBACK_DAYS = 90  # searchFestival은 '시작일 이후' 행사를 주므로 진행 중인 행사를 잡기 위해 과거로 넓힌다
PAGE_SIZE = 100
MAX_PAGES = 10


class TourApiConnector:
    def __init__(self, service_key: str, client: httpx.Client, version: str = "2"):
        # 서비스 버전: KorService2(searchFestival2/locationBasedList2)가 현행. 구버전은 version="1"
        self.key, self.client, self.v = service_key, client, version
        self.base = f"https://apis.data.go.kr/B551011/KorService{version}"

    def _params(self, **kw) -> dict:
        return {"serviceKey": self.key, "MobileOS": "ETC", "MobileApp": "PinPlay", "_type": "json", **kw}

    def _convert(self, it: dict, category: Category, confidence: float) -> RawSpot | None:
        title = (it.get("title") or "").strip()
        if not title:
            return None
        addr = " ".join(p for p in [it.get("addr1"), it.get("addr2")] if p).strip()
        return RawSpot(
            source="tourapi", source_id=str(it.get("contentid", "")), category=category, title=title,
            address=addr or None, lat=to_float(it.get("mapy")), lng=to_float(it.get("mapx")),  # mapx=경도, mapy=위도
            region_tag=region_tag_from_address(addr),
            start_date=parse_date(it.get("eventstartdate")), end_date=parse_date(it.get("eventenddate")),
            indoor_outdoor="OUTDOOR" if category == Category.FESTIVAL else None,
            # 상세 URL을 알 수 없어 지도 검색 링크로 대체(공식 페이지 아님)
            source_url=f"https://map.naver.com/p/search/{quote(title)}",
            confidence=confidence,
            extra={"contenttypeid": it.get("contenttypeid"), "tel": it.get("tel"), "image": it.get("firstimage"),
                   "url_kind": "map_search", "modified": it.get("modifiedtime"), "dist_m": to_float(it.get("dist"))},
        )

    def search_festivals(self, target: date, lat: float, lng: float, radius_km: float) -> list[RawSpot]:
        """target 시점에 진행 중이고 (lat,lng) 반경 내에 있는 축제."""
        start_from = (target - timedelta(days=FESTIVAL_LOOKBACK_DAYS)).strftime("%Y%m%d")
        out: list[RawSpot] = []
        for page in range(1, MAX_PAGES + 1):
            items = data_go_items(get_json(self.client, f"{self.base}/searchFestival{self.v}", params=self._params(
                eventStartDate=start_from, numOfRows=PAGE_SIZE, pageNo=page, arrange="A")))
            for it in items:
                s = self._convert(it, Category.FESTIVAL, 0.7)
                if not s or not s.start_date or not s.end_date or not (s.start_date <= target <= s.end_date):
                    continue
                if s.has_coords and haversine_km(lat, lng, s.lat, s.lng) > radius_km:
                    continue
                out.append(s)
            if len(items) < PAGE_SIZE:
                break
        return out

    def nearby_spots(
        self, lat: float, lng: float, radius_km: float, content_types: tuple[int, ...] = (12, 14)
    ) -> list[RawSpot]:
        """위치기반 관광지/문화시설 (반경 최대 20km, 거리순)."""
        out: list[RawSpot] = []
        for ct in content_types:
            items = data_go_items(get_json(self.client, f"{self.base}/locationBasedList{self.v}", params=self._params(
                mapX=lng, mapY=lat, radius=int(min(radius_km, 20) * 1000), contentTypeId=ct,
                numOfRows=PAGE_SIZE, pageNo=1, arrange="E")))
            out += [s for it in items if (s := self._convert(it, CONTENT_TYPE[ct], 0.6))]
        return out
