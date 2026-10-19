"""Supabase(PostGIS) 저장소. 쓰기/검색 모두 RPC(upsert_spots, search_spots_nearby)를 통한다."""
from __future__ import annotations

import threading
from datetime import date
from typing import Any, Callable

from app.config import Settings
from app.connectors.models import RawSpot

CHUNK = 200


class SpotStore:
    def __init__(self, client: Any, factory: Callable[[], Any] | None = None):
        self.client = client
        self._factory = factory
        self._local = threading.local()

    @classmethod
    def from_settings(cls, s: Settings) -> "SpotStore":
        from supabase import create_client

        def make() -> Any:
            return create_client(s.supabase_url, s.supabase_service_key)

        return cls(make(), factory=make)

    def for_thread(self) -> "SpotStore":
        """Supabase 클라이언트는 스레드 간에 공유하면 소켓 오류가 나므로, 병렬 조회에서는 스레드마다 하나씩 쓴다."""
        if not self._factory:
            return self
        if not hasattr(self._local, "store"):
            self._local.store = SpotStore(self._factory())
        return self._local.store

    def upsert(self, spots: list[RawSpot]) -> int:
        rows = [sp.to_row() for sp in spots if sp.has_coords]
        total = 0
        for i in range(0, len(rows), CHUNK):
            res = self.client.rpc("upsert_spots", {"p_rows": rows[i : i + CHUNK]}).execute()
            total += int(res.data or 0)
        return total

    def search(
        self, lat: float, lng: float, radius_km: float, target: date, categories: set[str] | None = None,
        limit: int = 200,
    ) -> list[dict]:
        res = self.client.rpc("search_spots_nearby", {
            "p_lat": lat, "p_lng": lng, "p_radius_m": int(radius_km * 1000), "p_date": target.isoformat(),
            "p_categories": sorted(categories) if categories else None, "p_limit": limit,
        }).execute()
        return res.data or []
