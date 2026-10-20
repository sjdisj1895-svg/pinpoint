import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings, load_settings
from app.connectors.models import RawSpot
from app.db import SpotStore
from app.harvest import HarvestResult, Harvester
from app.providers import DataLayerProvider, EmptyProvider, build_provider
from app.schemas import Category, T1Result
from tests.test_t1 import VALID

T1 = T1Result.model_validate(json.loads(VALID.strip("`json\n ")))


def spot(i=1, **kw):
    base = dict(source="tourapi", source_id=str(i), category=Category.FESTIVAL, title=f"축제{i}", lat=37.88,
                lng=127.73, region_tag="강원 춘천", start_date=date(2026, 10, 20), end_date=date(2026, 10, 30))
    return RawSpot(**{**base, **kw})


class FakeRpc:
    def __init__(self, calls, name, params, data):
        self.calls, self.name, self.params, self.data = calls, name, params, data

    def execute(self):
        self.calls.append((self.name, self.params))
        return type("R", (), {"data": self.data[self.name]})()


class FakeSupabase:
    def __init__(self, **data):
        self.calls, self.data = [], {"upsert_spots": 0, "search_spots_nearby": [], **data}

    def rpc(self, name, params):
        return FakeRpc(self.calls, name, params, self.data)


# ---------- 설정 ----------
def test_settings_unquotes_encoded_key():
    s = load_settings({"DATA_GO_KR_KEY": "ab%2Bcd%3D%3D", "SUPABASE_URL": "u", "SUPABASE_SERVICE_ROLE_KEY": "k"})
    assert s.data_go_key == "ab+cd==" and s.has_store


# ---------- 저장소 ----------
def test_store_upsert_skips_no_coords_and_chunks():
    fake = FakeSupabase(upsert_spots=2)
    store = SpotStore(fake)
    spots = [spot(i) for i in range(1, 4)] + [spot(9, lat=None, lng=None)]
    assert store.upsert(spots) == 2
    name, params = fake.calls[0]
    assert name == "upsert_spots" and len(params["p_rows"]) == 3
    row = params["p_rows"][0]
    assert row["province"] == "강원" and row["sources"] == ["tourapi"] and row["end_date"] == "2026-10-30"
    json.dumps(params)  # JSON 직렬화 가능해야 RPC 전송 가능


def test_store_search_params():
    fake = FakeSupabase(search_spots_nearby=[{"id": "x"}])
    rows = SpotStore(fake).search(37.88, 127.73, 3, date(2026, 10, 24), {"MOVIE", "FESTIVAL"})
    assert rows == [{"id": "x"}]
    assert fake.calls[0][1] == {"p_lat": 37.88, "p_lng": 127.73, "p_radius_m": 3000, "p_date": "2026-10-24",
                                "p_categories": ["FESTIVAL", "MOVIE"], "p_limit": 200}


def test_store_uses_one_client_per_thread():
    import threading

    made = []

    def make():
        made.append(object())
        return FakeSupabase()

    store = SpotStore(make(), factory=make)  # 메인 스레드용 1개
    assert store.for_thread() is store.for_thread()  # 같은 스레드에서는 재사용
    seen = []
    ts = [threading.Thread(target=lambda: seen.append(id(store.for_thread().client))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(seen)) == 3 and id(store.client) not in seen  # 스레드마다 다른 클라이언트
    assert SpotStore(FakeSupabase()).for_thread().client is not None  # 팩토리가 없으면 자기 자신


# ---------- 수집 오케스트레이션 ----------
def test_harvester_skips_missing_keys_and_isolates_errors(tmp_path):
    csv_path = tmp_path / "festival.csv"
    csv_path.write_text(
        "fstvlNm,fstvlStartDate,fstvlEndDate,rdnmadr,latitude,longitude\n"
        "소양강 별빛축제,2026-10-20,2026-10-30,강원특별자치도 춘천시 1,37.89,127.72\n"
        "좌표 없음,2026-10-20,2026-10-30,강원특별자치도 춘천시 2,,\n", encoding="utf-8")

    def handler(r: httpx.Request):
        return httpx.Response(500)  # TourAPI는 장애

    h = Harvester(Settings(data_go_key="K", mois_festival_file=str(csv_path)),
                  httpx.Client(transport=httpx.MockTransport(handler)))
    res = h.harvest(lat=37.88, lng=127.73, radius_km=10, target=date(2026, 10, 24), region_name="춘천시",
                    categories={Category.FESTIVAL, Category.MOVIE, Category.FLEA_MARKET})
    assert "tourapi_festival" in res.errors and "mois" in res.counts  # TourAPI 실패해도 파일 데이터 결과 유지
    assert "kobis_kakao" in res.skipped and "naver" in res.skipped
    assert [s.title for s in res.spots] == ["소양강 별빛축제"] and res.dropped_no_coords == 1


def test_harvester_skips_mois_when_file_missing(tmp_path):
    h = Harvester(Settings(data_go_key="K", mois_festival_file=str(tmp_path / "none.csv")),
                  httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    res = h.harvest(lat=37.88, lng=127.73, radius_km=10, target=date(2026, 10, 24), region_name="춘천시",
                    categories={Category.FESTIVAL})
    assert "mois" in res.skipped and "파일 없음" in res.skipped["mois"]


# ---------- 공급자 ----------
class StubHarvester:
    def __init__(self, spots):
        self.spots, self.calls = spots, 0

    def harvest(self, **kw):
        self.calls += 1
        return HarvestResult(spots=self.spots)


class StubStore:
    def __init__(self, rows):
        self.rows, self.upserted = rows, []

    def search(self, *a, **k):
        return self.rows

    def upsert(self, spots):
        self.upserted += spots
        self.rows = [{"title": s.title} for s in spots]
        return len(spots)


def test_provider_uses_db_when_populated():
    h, store = StubHarvester([spot()]), StubStore([{"title": "DB축제", "category": "FESTIVAL"}])
    assert DataLayerProvider(h, store).fetch(T1) == [{"title": "DB축제", "category": "FESTIVAL"}] and h.calls == 0


def test_provider_read_through_on_empty_db():
    h, store = StubHarvester([spot()]), StubStore([])
    assert DataLayerProvider(h, store).fetch(T1) == [{"title": "축제1"}]
    assert h.calls == 1 and len(store.upserted) == 1


def test_prepare_raw_caps_per_category_slims_and_prefers_confident_near():
    from app.providers import prepare_raw
    rows = [{"id": f"u{i}", "category": "TRAVEL_SPOT", "title": f"관광{i}", "confidence": 0.6, "distance_m": 1000 - i,
             "extra": {"image": "http://x/y.jpg", "dist_m": 5, "sources": ["tourapi"]}, "subtitle": None}
            for i in range(20)]
    rows.append({"id": "f", "category": "FESTIVAL", "title": "축제", "confidence": 0.9, "distance_m": 5000})
    out = prepare_raw(rows, per_category=8, max_rows=24)
    assert len([r for r in out if r["category"] == "TRAVEL_SPOT"]) == 8 and out[0]["title"] == "축제"
    spot0 = next(r for r in out if r["category"] == "TRAVEL_SPOT")
    # 사진 URL은 Spot 조립용으로 유지된다 (모델 입력에서는 model_view가 제거)
    assert "id" not in spot0 and "subtitle" not in spot0
    assert spot0["place_id"].startswith("u")  # DB id는 place_id로 이어진다 (좋아요·댓글의 키)
    assert spot0["extra"] == {"dist_m": 5, "sources": ["tourapi"], "image": "http://x/y.jpg"}
    assert spot0["title"] == "관광19"  # 같은 신뢰도면 가까운 순
    assert len(prepare_raw(rows, per_category=100, max_rows=5)) == 5


def test_provider_without_store_returns_live_rows():
    rows = DataLayerProvider(StubHarvester([spot()]), None).fetch(T1)
    assert rows[0]["title"] == "축제1" and "lat" in rows[0]


def test_build_provider_empty_without_keys():
    assert isinstance(build_provider(Settings(), None, None), EmptyProvider)
    assert isinstance(build_provider(Settings(kobis_key="x"), None, None), DataLayerProvider)


# ---------- API 라우트 ----------
@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings(admin_token="secret"))
    monkeypatch.setattr(main, "get_store", lambda: None)
    monkeypatch.setattr(main, "get_harvester", lambda: StubHarvester([spot()]))
    return TestClient(main.app)


BODY = {"lat": 37.88, "lng": 127.73, "region_name": "춘천시"}


def test_harvest_requires_token(api):
    assert api.post("/harvest", json=BODY).status_code == 401
    assert api.post("/harvest", json=BODY, headers={"x-admin-token": "wrong"}).status_code == 401
    r = api.post("/harvest", json=BODY, headers={"x-admin-token": "secret"})
    assert r.status_code == 200 and r.json()["collected"] == 1 and r.json()["upserted"] is None


def test_harvest_disabled_without_admin_token(api, monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings())
    assert api.post("/harvest", json=BODY, headers={"x-admin-token": "x"}).status_code == 503


def test_search_route_needs_store_and_validates(api, monkeypatch):
    assert api.get("/spots/search", params={"lat": 37.88, "lng": 127.73}).status_code == 503
    fake = FakeSupabase(search_spots_nearby=[{"id": "x"}])
    monkeypatch.setattr(main, "get_store", lambda: SpotStore(fake))
    r = api.get("/spots/search", params={"lat": 37.88, "lng": 127.73, "categories": "MOVIE,FESTIVAL"})
    assert r.json() == {"count": 1, "spots": [{"id": "x"}]}
    assert api.get("/spots/search", params={"lat": 37.88, "lng": 127.73, "categories": "BAD"}).status_code == 422
    assert api.get("/spots/search", params={"lat": 10, "lng": 127.73}).status_code == 422
