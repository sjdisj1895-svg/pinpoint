"""Connector C: KOBIS 박스오피스(상영작 순위) + 카카오 로컬(주변 영화관 좌표) 매칭.

한계: KOBIS 오픈API에는 극장별 상영 회차(시간표)가 없다. 영화관 위치와 '지금 흥행 중인 상영작'까지만
확보되며, 회차(movie_showtimes)는 별도 소스(극장 사이트 등)가 필요하다. extra.showtimes_available=False로 표시한다.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from app.connectors.kakao import KakaoLocal
from app.connectors.models import ConnectorError, RawSpot, get_json, region_tag_from_address, to_float
from app.schemas import Category

BOXOFFICE_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
THEATER_QUERIES = ("영화관", "독립영화관")
CHAINS = ("CGV", "롯데시네마", "메가박스")


class KobisClient:
    def __init__(self, key: str, client: httpx.Client):
        self.key, self.client = key, client

    def daily_boxoffice(self, target: date) -> list[dict]:
        """일별 박스오피스. KOBIS는 전일까지만 제공하므로 target을 어제로 제한한다."""
        day = min(target, date.today() - timedelta(days=1))
        payload = get_json(self.client, BOXOFFICE_URL, params={"key": self.key, "targetDt": day.strftime("%Y%m%d")})
        if "faultInfo" in payload:
            raise ConnectorError(f"KOBIS 오류: {payload['faultInfo'].get('message', '')}")
        return [
            {"rank": int(m.get("rank", 0)), "title": m.get("movieNm", ""), "movie_cd": m.get("movieCd"),
             "open_dt": m.get("openDt")}
            for m in payload.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
        ]


def find_theaters(
    kobis: KobisClient, kakao: KakaoLocal, lat: float, lng: float, radius_km: float, target: date, top_n: int = 10
) -> list[RawSpot]:
    now_showing = [m["title"] for m in kobis.daily_boxoffice(target)[:top_n] if m["title"]]
    seen: dict[str, RawSpot] = {}
    for q in THEATER_QUERIES:
        for d in kakao.keyword_search(q, lat, lng, radius_km):
            cat = d.get("category_name", "")
            if "영화관" not in cat or d.get("id") in seen:
                continue
            addr = d.get("road_address_name") or d.get("address_name")
            name = d.get("place_name", "")
            seen[d["id"]] = RawSpot(
                source="kobis_kakao", source_id=str(d["id"]), category=Category.MOVIE, title=name,
                subtitle="박스오피스 상영작 기준" if now_showing else None,
                address=addr, lat=to_float(d.get("y")), lng=to_float(d.get("x")),
                region_tag=region_tag_from_address(addr), indoor_outdoor="INDOOR",
                source_url=d.get("place_url"),
                confidence=0.5,  # 위치는 확실하나 상영 회차는 미확인
                extra={"now_showing_top": now_showing, "showtimes": None, "showtimes_available": False,
                       "chain": next((c for c in CHAINS if c in name), None), "phone": d.get("phone"),
                       "dist_m": to_float(d.get("distance"))},
            )
    return list(seen.values())
