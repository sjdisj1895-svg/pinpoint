"""4개 커넥터를 병렬 실행·병합해 RawSpot 목록을 만든다. 일부 소스가 실패해도 나머지 결과는 반환한다."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import anthropic
import httpx

from app.config import Settings
from app.connectors.kakao import KakaoLocal
from app.connectors.kobis_kakao import KobisClient, find_theaters
from app.connectors.models import RawSpot
from app.connectors.mois import MoisFestivalFile, merge_festivals
from app.connectors.naver_events import NaverSearch, harvest_events
from app.connectors.tourapi import TourApiConnector
from app.schemas import Category


PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class HarvestResult:
    spots: list[RawSpot] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)  # 소스별 수집 건수
    errors: dict[str, str] = field(default_factory=dict)  # 실패한 소스
    skipped: dict[str, str] = field(default_factory=dict)  # 키 미설정 등으로 건너뜀
    dropped_no_coords: int = 0


class Harvester:
    def __init__(self, settings: Settings, http: httpx.Client | None = None, llm: anthropic.Anthropic | None = None):
        self.s, self.http, self.llm = settings, http or httpx.Client(), llm

    def harvest(
        self, *, lat: float, lng: float, radius_km: float, target: date, region_name: str,
        categories: set[Category] | None = None,
    ) -> HarvestResult:
        cats = categories or set(Category)
        s, res = self.s, HarvestResult()
        kakao = KakaoLocal(s.kakao_rest_key, self.http) if s.kakao_rest_key else None
        tasks: dict[str, Callable[[], list[RawSpot]]] = {}

        def need(name: str, ok: bool, why: str) -> bool:
            if not ok:
                res.skipped[name] = why
            return ok

        if Category.FESTIVAL in cats:
            if need("tourapi_festival", bool(s.data_go_key), "DATA_GO_KR_KEY 미설정"):
                t = TourApiConnector(s.data_go_key, self.http, s.tourapi_version)
                tasks["tourapi_festival"] = lambda: t.search_festivals(target, lat, lng, radius_km)
            mois_path = Path(s.mois_festival_file)
            if not mois_path.is_absolute():
                mois_path = PROJECT_ROOT / mois_path
            m = MoisFestivalFile(mois_path)
            if need("mois", m.exists(), f"파일 없음: {s.mois_festival_file} (data.go.kr 전국문화축제표준데이터 CSV)"):
                tasks["mois"] = lambda: m.fetch_festivals(target, lat, lng, radius_km, region_name)
        if Category.TRAVEL_SPOT in cats and need("tourapi_nearby", bool(s.data_go_key), "DATA_GO_KR_KEY 미설정"):
            t2 = TourApiConnector(s.data_go_key, self.http, s.tourapi_version)
            tasks["tourapi_nearby"] = lambda: t2.nearby_spots(lat, lng, radius_km)
        if Category.MOVIE in cats and need("kobis_kakao", bool(s.kobis_key and kakao), "KOBIS_KEY/KAKAO_REST_KEY 미설정"):
            k = KobisClient(s.kobis_key, self.http)
            tasks["kobis_kakao"] = lambda: find_theaters(k, kakao, lat, lng, radius_km, target)
        wants_events = bool(cats & {Category.FLEA_MARKET, Category.NEW_OPEN})
        if wants_events and need("naver", bool(s.naver_client_id and s.naver_client_secret and kakao),
                                 "NAVER_CLIENT_ID/SECRET 또는 KAKAO_REST_KEY 미설정"):
            n = NaverSearch(s.naver_client_id, s.naver_client_secret, self.http, s.naver_api_mode)
            tasks["naver"] = lambda: harvest_events(n, kakao, region_name, lat, lng, radius_km, date.today(),
                                                    self.llm, categories=cats)

        results: dict[str, list[RawSpot]] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
            futures = {name: pool.submit(fn) for name, fn in tasks.items()}
            for name, fut in futures.items():
                try:
                    results[name] = fut.result()
                    res.counts[name] = len(results[name])
                except Exception as e:  # 한 소스의 실패가 전체를 막지 않게 한다
                    res.errors[name] = f"{type(e).__name__}: {e}"[:300]

        festivals = merge_festivals(results.get("tourapi_festival", []), results.get("mois", []))
        others = [sp for name, lst in results.items() if name not in ("tourapi_festival", "mois") for sp in lst]
        best: dict[str, RawSpot] = {}
        for sp in [*festivals, *others]:
            if sp.category not in cats:
                continue
            if not sp.has_coords:  # 마커를 찍을 수 없는 항목은 제외 (T2 위치 정확도 규칙)
                res.dropped_no_coords += 1
                continue
            key = sp.dedupe_key()
            if key not in best or sp.confidence > best[key].confidence:
                best[key] = sp
        res.spots = list(best.values())
        return res
