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


def test_filters_run_on_the_cached_pool_without_new_db_queries():
    explore_mod._cache.clear()
    store = FakeStore(lambda lat, lng: [db_row(1)])
    explore_mod.explore(store, "경남", TARGET)
    n = len(store.calls)
    explore_mod.explore(store, "경남", TARGET, q="유등")
    explore_mod.explore(store, "경남", TARGET, region="진주시", categories={"MOVIE"})
    explore_mod.explore(store, "경남", TARGET, q="없는말", limit=5)
    assert len(store.calls) == n  # 검색·지역·분류는 캐시된 목록 위에서 메모리로만 처리


# ---------- 키워드 검색 · 지역 필터 ----------
def pool_of(*rows):
    spots = [row_to_spot(r, TARGET) for r in rows]
    return explore_mod.Pool("경남", {"lat": 35.2, "lng": 128.3}, spots)


def titles(result):
    return [s["title"] for s in result["spots"]]


def test_tokenize_is_lowercase_and_capped():
    assert explore_mod.tokenize("  진주   Night  ") == ["진주", "night"]
    assert explore_mod.tokenize("") == [] and explore_mod.tokenize("   ") == []
    assert len(explore_mod.tokenize("a b c d e f g")) == explore_mod.MAX_TOKENS


def test_keyword_matches_title_address_and_category_words_with_and_semantics():
    pool = pool_of(
        db_row(1, title="진주 남강 유등축제", tag="경남 진주시"),
        db_row(2, title="통영 케이블카", tag="경남 통영시", category="TRAVEL_SPOT", start=None, end=None),
        db_row(3, title="CGV 창원", tag="경남 창원시", category="MOVIE", start=None, end=None),
    )
    assert titles(explore_mod.search_pool(pool, "유등")) == ["진주 남강 유등축제"]  # 이름
    assert titles(explore_mod.search_pool(pool, "통영시")) == ["통영 케이블카"]  # 주소·지역
    assert titles(explore_mod.search_pool(pool, "영화관")) == ["CGV 창원"]  # 분류 이름으로도 찾는다
    assert titles(explore_mod.search_pool(pool, "축제")) == ["진주 남강 유등축제"]
    assert titles(explore_mod.search_pool(pool, "진주 유등")) == ["진주 남강 유등축제"]  # 모든 단어가 맞아야 한다
    assert explore_mod.search_pool(pool, "진주 케이블카")["spots"] == []  # AND: 한쪽만 맞으면 제외
    assert explore_mod.search_pool(pool, "없는검색어")["total"] == 0


def test_keyword_ignores_spaces_and_case():
    pool = pool_of(db_row(1, title="소양강 스카이워크", tag="경남 진주시"), db_row(2, title="Sky Garden", tag="경남 김해시"))
    assert titles(explore_mod.search_pool(pool, "소양강스카이")) == ["소양강 스카이워크"]
    assert titles(explore_mod.search_pool(pool, "스카이 워크")) == ["소양강 스카이워크"]
    assert titles(explore_mod.search_pool(pool, "SKY GARDEN")) == ["Sky Garden"]


def test_title_matches_rank_above_address_matches():
    pool = pool_of(
        db_row(1, title="가야 박물관", tag="경남 진주시", confidence=0.9),  # 이름에 '진주'가 없고 주소에만 있음
        db_row(2, title="진주성", tag="경남 통영시", confidence=0.5),  # 이름에 '진주'
    )
    assert titles(explore_mod.search_pool(pool, "진주")) == ["진주성", "가야 박물관"]


def test_region_filter_and_facets_are_counted_before_the_region_filter():
    pool = pool_of(
        db_row(1, title="축제A", tag="경남 진주시"), db_row(2, title="축제B", tag="경남 진주시"),
        db_row(3, title="축제C", tag="경남 통영시"),
        db_row(4, title="관광D", tag="경남 통영시", category="TRAVEL_SPOT", start=None, end=None),
    )
    all_ = explore_mod.search_pool(pool)
    assert {r["name"]: r["count"] for r in all_["regions"]} == {"진주시": 2, "통영시": 2}
    jinju = explore_mod.search_pool(pool, region="진주시")
    assert titles(jinju) == ["축제A", "축제B"] and jinju["total"] == 2
    assert {r["name"] for r in jinju["regions"]} == {"진주시", "통영시"}  # 다른 지역으로 바로 바꿔 볼 수 있다
    with_q = explore_mod.search_pool(pool, q="축제")  # 키워드를 걸면 지역별 개수도 그 결과 기준
    assert {r["name"]: r["count"] for r in with_q["regions"]} == {"진주시": 2, "통영시": 1}
    assert explore_mod.search_pool(pool, region="없는시")["spots"] == []


def test_category_filter_and_total_before_limit():
    rows = [db_row(i, title=f"관광{i}", category="TRAVEL_SPOT", start=None, end=None) for i in range(1, 8)]
    pool = pool_of(*rows, db_row(20, title="축제", tag="경남 진주시"))
    only_travel = explore_mod.search_pool(pool, categories={"TRAVEL_SPOT"})
    assert only_travel["total"] == 7 and all(s["category"] == "TRAVEL_SPOT" for s in only_travel["spots"])
    limited = explore_mod.search_pool(pool, q="관광", limit=3)
    assert limited["count"] == 3 and limited["total"] == 7  # total은 자르기 전 개수


def test_explore_route_search_params(monkeypatch):
    explore_mod._cache.clear()
    api = TestClient(main.app)
    rows = [db_row(1, title="진주 유등축제", tag="경남 진주시"), db_row(2, title="통영 케이블카", tag="경남 통영시", category="TRAVEL_SPOT", start=None, end=None)]
    monkeypatch.setattr(main, "get_store", lambda: FakeStore(lambda lat, lng: rows))
    r = api.get("/api/explore", params={"q": "케이블카"}).json()
    assert [s["title"] for s in r["spots"]] == ["통영 케이블카"] and r["total"] == 1
    assert {x["name"] for x in r["regions"]} == {"통영시"}
    r2 = api.get("/api/explore", params={"region": "진주시"}).json()
    assert [s["title"] for s in r2["spots"]] == ["진주 유등축제"]
    assert api.get("/api/explore", params={"q": "가" * 61}).status_code == 422  # 너무 긴 검색어는 거절
    assert api.get("/api/explore", params={"region": "x" * 21}).status_code == 422


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


class DbError(Exception):
    """postgrest APIError처럼 code/message를 가진 예외."""

    code, message = "401", "Invalid API key"


def test_db_failures_become_502_with_the_error_kind_not_secrets(monkeypatch):
    explore_mod._cache.clear()

    class Broken:
        def search(self, *a, **k):
            raise DbError("SECRET-URL https://x.supabase.co key=abc")

    monkeypatch.setattr(main, "get_store", lambda: Broken())
    api = TestClient(main.app, raise_server_exceptions=False)
    for path, params in [("/api/explore", {}), ("/api/spots/search", {"lat": 37, "lng": 127})]:
        r = api.get(path, params=params)
        assert r.status_code == 502
        detail = r.json()["detail"]
        assert "DbError" in detail and "401" in detail and "Invalid API key" in detail
        assert "SECRET-URL" not in detail and "supabase.co" not in detail  # 예외 본문은 응답에 싣지 않는다
        assert "cache-control" not in r.headers  # 오류는 CDN에 캐시하지 않는다


def test_build_spot_carries_image_from_raw_extra():
    row = {"category": "FESTIVAL", "title": "축제", "address": "경남 진주시 1", "lat": 35.1, "lng": 128.1,
           "extra": {"image": "http://tong.visitkorea.or.kr/x.jpg"}}
    d = Decision(index=0, subtitle="s", live_status="OPEN_NOW", confidence_score=0.8, verification_note="n")
    assert build_spot(1, row, d).image_url == "https://tong.visitkorea.or.kr/x.jpg"
