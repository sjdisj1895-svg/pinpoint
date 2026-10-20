import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { fetchExplore, fetchPipeline, fetchReroute } from "./api";
import type { Weather } from "./types";
import BottomSheet from "./BottomSheet";
import {
  buildCards, filterByMonths, filterByPeriod, filterByQuery, filterByRegion, monthCounts, regionFacets, sortItems,
} from "./geo";
import KakaoMapView from "./KakaoMapView";
import MapView from "./MapView";
import { MOCK } from "./mock";
import PlaceDetail from "./PlaceDetail";
import Panel, { CategoryChips, MAX_KEYWORD_LENGTH } from "./Panel";
import { initialState, reducer } from "./store";

const HOME_PROVINCE = "경남"; // 첫 화면으로 보여 줄 권역
const HOME_LABEL = "경상남도";

/** 브라우저 위치(3초 제한). 거부·실패하면 검색 중심 좌표를 현재 위치로 간주 */
function currentLocation(fallback: { lat: number; lng: number }): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(fallback);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(fallback),
      { timeout: 3000, maximumAge: 60000 },
    );
  });
}

function useIsMobile(): boolean {
  const q = "(max-width: 768px)";
  const [m, setM] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return m;
}

/** 값이 바뀐 뒤 ms만큼 가만히 있으면 반영한다 (검색어를 칠 때마다 요청하지 않게) */
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** 서버가 알려 주는 공개 설정(카카오맵 JavaScript 키). 실패하거나 키가 없으면 null → OpenFreeMap 지도 */
function useMapConfig(): { loading: boolean; kakaoKey: string | null } {
  const [cfg, setCfg] = useState<{ loading: boolean; kakaoKey: string | null }>({ loading: true, kakaoKey: null });
  useEffect(() => {
    let alive = true;
    fetch("/api/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => alive && setCfg({ loading: false, kakaoKey: c?.kakao_js_key ?? null }))
      .catch(() => alive && setCfg({ loading: false, kakaoKey: null }));
    return () => {
      alive = false;
    };
  }, []);
  return cfg;
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const mobile = useIsMobile();
  const mapCfg = useMapConfig();
  const [kakaoFailed, setKakaoFailed] = useState(false); // 카카오맵이 뜨지 않으면 true → OpenFreeMap으로 대체
  // 주소의 ?map=leaflet 으로 카카오맵 대신 OpenFreeMap을 강제로 볼 수 있다 (비교·문제 확인용)
  const forceLeaflet = new URLSearchParams(window.location.search).get("map") === "leaflet";
  const mapEngine: "kakao" | "leaflet" = !forceLeaflet && mapCfg.kakaoKey && !kakaoFailed ? "kakao" : "leaflet";

  // 키워드는 입력을 멈춘 뒤 반영한다. 입력을 비우면 기다리지 않고 바로 전체로 돌아간다.
  const debouncedInput = useDebounced(state.queryInput, 300);
  const typed = state.queryInput.trim() ? debouncedInput.trim() : "";
  const q = typed.length <= MAX_KEYWORD_LENGTH ? typed : ""; // 긴 문장은 키워드가 아니라 AI에게 묻는 입력으로 본다

  // 둘러보기: 키워드·시·군은 서버(DB 전체)가 걸러서 준다. AI 추천 결과: 몇 건 안 되므로 화면에서 바로 거른다.
  const clientSide = state.mode === "search";
  const base = useMemo(() => (state.data ? buildCards(state.data) : []), [state.data]);
  const queried = useMemo(() => (clientSide ? filterByQuery(base, q) : base), [clientSide, base, q]);
  const regionOptions = useMemo(() => (clientSide ? regionFacets(queried) : state.regions), [clientSide, queried, state.regions]);

  // (키워드·시·군) → 분류 → 월 → 시기 → 정렬 순으로 적용한 전체 결과 (지도에는 이 전체가, 목록에는 "더보기" 단위로 보인다)
  const candidates = useMemo(() => {
    const byRegion = clientSide ? filterByRegion(queried, state.region) : queried;
    return byRegion.filter((c) => state.activeCategories.includes(c.spot.category));
  }, [clientSide, queried, state.region, state.activeCategories]);
  const monthCountsMemo = useMemo(() => monthCounts(candidates), [candidates]); // 월 체크박스 옆 개수 (월 필터 적용 전 기준)
  const items = useMemo(() => {
    if (!state.data) return [];
    const byMonth = filterByMonths(candidates, state.months);
    return sortItems(filterByPeriod(byMonth, state.period), state.sort, state.data.t1.target_region.center_coords);
  }, [state.data, candidates, state.months, state.period, state.sort]);

  // 선택한 장소(카드나 지도의 핀을 누르면). 필터로 목록에서 빠졌거나 "더보기" 밖에 있어도 상세는 항상 열린다.
  const selectedItem = useMemo(
    () => (state.selectedId ? items.find((i) => i.spot.id === state.selectedId) ?? base.find((i) => i.spot.id === state.selectedId) ?? null : null),
    [state.selectedId, items, base],
  );
  useEffect(() => {
    if (!state.selectedId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && dispatch({ type: "select", id: null });
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.selectedId]);
  const fitKey = `${q}|${state.region}`; // 검색어·시·군이 바뀌면 지도를 그 결과에 맞춘다 ("|" = 필터 없음)
  const shown = useMemo(() => items.slice(0, state.visible), [items, state.visible]);
  const course = useMemo(
    () => (state.showCourse ? state.data?.t3.courses.find((c) => c.course_id === state.courseId) ?? null : null),
    [state.showCourse, state.data, state.courseId],
  );

  const lastFetch = useRef("|"); // 마지막으로 불러온 (키워드|시·군). 같은 조건을 다시 요청하지 않는다
  const reqId = useRef(0); // 늦게 도착한 옛 응답이 새 결과를 덮어쓰지 않게 한다

  const onExplore = useCallback(async () => {
    lastFetch.current = "|";
    const id = ++reqId.current;
    try {
      const r = await fetchExplore(HOME_PROVINCE, HOME_LABEL);
      if (id !== reqId.current) return;
      const greeting = r.data.t2.length
        ? `${HOME_PROVINCE}에서 지금 즐길 수 있는 축제와 볼거리를 모았어요. 검색창에 키워드를 입력하거나 시·군을 골라 보세요. 문장으로 묻고 싶다면 ✨ AI 추천을 눌러 주세요.`
        : "아직 수집된 데이터가 없어요. 그래도 원하는 곳을 물어보면 실시간으로 찾아 드려요.";
      dispatch({ type: "explored", data: r.data, greeting, regions: r.regions, total: r.total });
    } catch (e) {
      dispatch({ type: "failure", error: e instanceof Error ? e.message : "알 수 없는 오류" });
    }
  }, []);

  // 둘러보기에서 키워드·시·군이 바뀌면 서버(DB 전체)에서 다시 찾는다. AI 호출 없음.
  useEffect(() => {
    if (state.mode !== "explore") return;
    const key = `${q}|${state.region}`;
    if (key === lastFetch.current) return;
    lastFetch.current = key;
    const id = ++reqId.current;
    fetchExplore(HOME_PROVINCE, HOME_LABEL, { q, region: state.region })
      .then((r) => id === reqId.current && dispatch({ type: "exploreResults", data: r.data, regions: r.regions, total: r.total }))
      .catch((e) => id === reqId.current && dispatch({ type: "failure", error: e instanceof Error ? e.message : "알 수 없는 오류" }));
  }, [q, state.region, state.mode]);

  const onAsk = useCallback(async (text: string) => {
    dispatch({ type: "submit", text });
    try {
      const data = await fetchPipeline(text);
      const note = data.t2.length === 0 ? "조건에 맞는 곳을 찾지 못했어요. 지역이나 날짜를 바꿔 보세요." : undefined;
      dispatch({ type: "success", data, note });
    } catch (e) {
      dispatch({ type: "failure", error: e instanceof Error ? e.message : "알 수 없는 오류" });
    }
  }, []);

  const onReroute = useCallback(
    async (feedback: string, weather?: Weather) => {
      const data = state.data;
      if (!data) return;
      dispatch({ type: "submit", text: feedback });
      try {
        const location = await currentLocation(data.t1.target_region.center_coords);
        const res = await fetchReroute({
          feedback, location, weather, t1: data.t1, spots: data.t2,
          course: data.t3.courses.find((c) => c.course_id === state.courseId) ?? null,
        });
        dispatch({ type: "rerouted", res });
      } catch (e) {
        dispatch({ type: "failure", error: e instanceof Error ? e.message : "알 수 없는 오류" });
      }
    },
    [state.data, state.courseId],
  );

  const onSample = useCallback(() => dispatch({ type: "success", data: MOCK, note: "샘플 데이터입니다." }), []);

  // 첫 화면: 경남 둘러보기. /?sample 로 열면 샘플 데이터(&course: 추천 코스까지)로 확인할 수 있다
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.has("sample")) {
      onSample();
      if (q.has("course")) dispatch({ type: "toggleCourse" });
    } else {
      void onExplore();
    }
  }, [onSample, onExplore]);

  const onSelect = useCallback((id: string) => dispatch({ type: "select", id }), []);

  const panel = (
    <Panel
      state={state}
      dispatch={dispatch}
      items={items}
      shown={shown}
      courses={state.data?.t3.courses ?? []}
      onAsk={onAsk}
      onSample={onSample}
      onReroute={onReroute}
      onExplore={onExplore}
      showChips={!mobile}
      mapEngine={mapEngine}
      regionOptions={regionOptions}
      monthCounts={monthCountsMemo}
    />
  );
  const drawer = selectedItem && (
    <PlaceDetail item={selectedItem} onClose={() => dispatch({ type: "select", id: null })} />
  );

  const mapProps = {
    data: state.data,
    items,
    course,
    transport: state.data?.t1.user_persona.transport ?? ("WALK" as const),
    focusId: state.hoveredId ?? state.selectedId,
    selectedId: state.selectedId,
    onSelect,
    padBottom: mobile ? Math.round(window.innerHeight * 0.5) : 0,
    compact: mobile,
    fitKey,
  };
  const map = mapCfg.loading ? (
    <div className="map" aria-busy="true" aria-label="지도를 불러오는 중" />
  ) : mapEngine === "kakao" ? (
    <KakaoMapView {...mapProps} appKey={mapCfg.kakaoKey!} onUnavailable={() => setKakaoFailed(true)} />
  ) : (
    <MapView {...mapProps} />
  );

  if (mobile) {
    return (
      <div className="app mobile">
        {map}
        <div className="floating-chips">
          <CategoryChips active={state.activeCategories} dispatch={dispatch} />
        </div>
        <BottomSheet overlay={drawer} expandKey={state.selectedId}>{panel}</BottomSheet>
      </div>
    );
  }
  return (
    <div className="app desktop">
      <aside className="left">
        <div className="left-scroll">{panel}</div>
        {drawer && <div className="drawer">{drawer}</div>}
      </aside>
      <main className="right">{map}</main>
    </div>
  );
}
