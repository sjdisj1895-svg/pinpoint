"""카카오 로컬 API 클라이언트 (키워드 장소검색 + 주소/장소 지오코딩)."""
from __future__ import annotations

import httpx

from app.connectors.models import get_json, to_float

BASE = "https://dapi.kakao.com/v2/local/search"


class KakaoLocal:
    def __init__(self, rest_key: str, client: httpx.Client):
        self.client = client
        self.headers = {"Authorization": f"KakaoAK {rest_key}"}

    def keyword_search(
        self, query: str, lat: float | None = None, lng: float | None = None, radius_km: float | None = None,
        size: int = 15, page: int = 1,
    ) -> list[dict]:
        params: dict = {"query": query, "size": min(size, 15), "page": page}
        if lat is not None and lng is not None:
            params.update(x=lng, y=lat, sort="distance")
            if radius_km:
                params["radius"] = int(min(radius_km, 20) * 1000)  # 카카오 최대 20km
        return get_json(self.client, f"{BASE}/keyword.json", params=params, headers=self.headers).get("documents", [])

    def geocode(self, query: str) -> tuple[float, float, str] | None:
        """주소 → 장소명 순으로 시도. (lat, lng, 주소) 또는 None."""
        for path in ("address.json", "keyword.json"):
            docs = get_json(self.client, f"{BASE}/{path}", params={"query": query, "size": 1},
                            headers=self.headers).get("documents", [])
            if docs:
                d = docs[0]
                lat, lng = to_float(d.get("y")), to_float(d.get("x"))
                if lat is not None and lng is not None:
                    return lat, lng, d.get("road_address_name") or d.get("address_name") or query
        return None
