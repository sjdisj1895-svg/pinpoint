import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.explore as explore_mod
import app.main as main
from app.connectors.models import RawSpot
from app.explore import province_regions, row_to_spot
from app.schemas import Category
from app.stages.t2_harvester import build_spot, Decision, image_url_of

TARGET = date(2026, 10, 24)


def db_row(i, title="진주 남강 유등", tag="경남 진주시", start="2026-10-20", end="2026-10-30", lat=35.18, lng=128.1,
           category="FESTIVAL", image="http://tong.visitkorea.or.kr/cms/resource/1/a.jpg", **kw):
    return {"id": f"id-{i}", "category": category, "title": title, "subtitle": None, "address": f"{tag} 1",
            "region_tag": tag, "province": tag.split()[0], "lat": lat, "lng": lng, "start_date": start,
            "end_date": end, "operating_hours": None, "indoor_outdoor": None, "sources": ["tourapi"],
            "source_url": None, "confidence": 0.7, "extra": {"image": image} if image else {}, "distance_m": 100, **kw}


class FakeStore:
    def __init__(self, by_center):
        self.by_center, self.calls = by_center, []

    def search(self, lat, lng, radius_km, target, categories=None, limit=200):
        self.calls.append((lat, lng, radius_km, categories))
        return self.by_center(lat, lng)


def test_regions_json_is_valid_and_gyeongnam_covers_18_cities():
    regions = json.loads(Path(explore_mod.REGIONS).read_text(encoding="utf-8"))
    for r in regions:
        assert 33 <= r["lat"] <= 39 and 124 <= r["lng"] <= 132 and r["province"] and r["region_name"]
    gn = province_regions("경남")
    assert len(gn) == 18 and len({r["region_name"] for r in gn}) == 18
    assert all(34.5 <= r["lat"] <= 35.8 and 127.5 <= r["lng"] <= 129.3 for r in gn)  # 경남 범위


def test_row_to_spot_basics_and_https_image():
    s = row_to_spot(db_row(1), TARGET)
    assert s.id == "id-1" and s.category == Category.FESTIVAL and s.schedule.live_status.value == "OPEN_NOW"
    assert s.image_url == "https://tong.visitkorea.or.kr/cms/resource/1/a.jpg"
    assert s.schedule.period == "2026-10-20 ~ 2026-10-30" and s.source_url.startswith("https://map.naver.com/p/search/")
    assert s.attributes.parking_available is None and "AI 검증 전" in s.verification_note
    assert row_to_spot(db_row(2, start="2026-11-01"), TARGET).schedule.live_status.value == "OPEN_SOON"
    assert row_to_spot(db_row(3, image=None), TARGET).image_url is None
    assert row_to_spot({**db_row(4), "lat": None}, TARGET) is None and row_to_spot({"x": 1}, TARGET) is None


def test_image_url_rejects_non_http_and_keeps_other_hosts():
    assert image_url_of({"extra": {"image": "javascript:alert(1)"}}) is None
    assert image_url_of({"extra": {"image": "http://other.example/a.jpg"}}) == "http://other.example/a.jpg"
    assert image_url_of({}) is None


def test_explore_merges_centers_dedupes_and_filters_province(monkeypatch):
    explore_mod._cache.clear()
    shared = db_row(1)
    other_province = db_row(9, title="부산 축제", tag="부산 해운대구")

    def by_center(lat, lng):  # 모든 중심에서 같은 행이 겹쳐 나온다 + 타 권역 행 1개
        return [shared, other_province, db_row(2, title="사진 없는 곳", image=None)]

    store = FakeStore(by_center)
    out = explore_mod.explore(store, "경남", TARGET)
    n_calls = 18 * (1 + len(explore_mod.FUTURE_OFFSETS))  # 18개 시·군 × (오늘 + 미래 기준일)
    assert len(store.calls) == n_calls and out["count"] == 2  # 중복 제거 + 부산 제외
    assert [s["title"] for s in out["spots"]] == ["진주 남강 유등", "사진 없는 곳"]  # 사진 있는 항목 우선
    assert out["center"]["lat"] == pytest.approx(35.2, abs=0.3)
    explore_mod.explore(store, "경남", TARGET)
    assert len(store.calls) == n_calls  # 두 번째는 캐시
    with pytest.raises(KeyError):
        explore_mod.explore(store, "없는권역", TARGET)


def test_explore_queries_future_dates_only_for_events():
    explore_mod._cache.clear()
    store = FakeStore(lambda lat, lng: [])
    explore_mod.explore(store, "경남", TARGET)
    today = [c for c in store.calls if c[3] is None]
    future = [c for c in store.calls if c[3] is not None]
    assert len(today) == 18 and len(future) == 18 * len(explore_mod.FUTURE_OFFSETS)
    assert all(set(c[3]) == {"FESTIVAL", "FLEA_MARKET"} for c in future)  # 미래 조회는 행사류만
    explore_mod._cache.clear()
    store2 = FakeStore(lambda lat, lng: [])
    explore_mod.explore(store2, "경남", TARGET, categories={"MOVIE"})
    assert len(store2.calls) == 18  # 행사류를 요청하지 않으면 미래 조회도 없다


def test_explore_marks_upcoming_events_as_open_soon():
    explore_mod._cache.clear()
    rows = [db_row(1, title="곧 열릴 축제", start="2026-11-20", end="2026-11-25")]
    out = explore_mod.explore(FakeStore(lambda lat, lng: rows), "경남", TARGET)
    assert out["spots"][0]["schedule"]["live_status"] == "OPEN_SOON"


def test_explore_limit_trims_travel_spots_but_keeps_events_and_movies():
    explore_mod._cache.clear()
    rows = [db_row(i, title=f"관광{i}", category="TRAVEL_SPOT", start=None, end=None) for i in range(1, 8)]
    rows += [db_row(20, title="영화관", category="MOVIE", start=None, end=None, image=None, confidence=0.5),
             db_row(21, title="축제")]
    out = explore_mod.explore(FakeStore(lambda lat, lng: rows), "경남", TARGET, limit=4)
    cats = [s["category"] for s in out["spots"]]
    assert out["count"] == 4 and "MOVIE" in cats and "FESTIVAL" in cats and cats.count("TRAVEL_SPOT") == 2


def test_explore_route(monkeypatch):
    explore_mod._cache.clear()
    api = TestClient(main.app)
    monkeypatch.setattr(main, "get_store", lambda: None)
    assert api.get("/explore").status_code == 503
    monkeypatch.setattr(main, "get_store", lambda: FakeStore(lambda lat, lng: [db_row(1)]))
    r = api.get("/api/explore", params={"province": "경남", "categories": "FESTIVAL"})
    assert r.status_code == 200 and r.json()["count"] == 1
    assert "s-maxage=900" in r.headers["cache-control"]  # CDN 캐시 (서버리스 콜드 스타트 완화)
    assert "cache-control" not in api.get("/explore", params={"province": "없는권역"}).headers  # 오류 응답은 캐시하지 않는다
    assert api.get("/explore", params={"province": "없는권역"}).status_code == 404
    assert api.get("/explore", params={"categories": "BAD"}).status_code == 422


def test_build_spot_carries_image_from_raw_extra():
    row = {"category": "FESTIVAL", "title": "축제", "address": "경남 진주시 1", "lat": 35.1, "lng": 128.1,
           "extra": {"image": "http://tong.visitkorea.or.kr/x.jpg"}}
    d = Decision(index=0, subtitle="s", live_status="OPEN_NOW", confidence_score=0.8, verification_note="n")
    assert build_spot(1, row, d).image_url == "https://tong.visitkorea.or.kr/x.jpg"
