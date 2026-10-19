import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { fetchExplore, fetchPipeline, fetchReroute } from "./api";
import type { Weather } from "./types";
import BottomSheet from "./BottomSheet";
import { buildCards, filterByPeriod, sortItems } from "./geo";
import KakaoMapView from "./KakaoMapView";
import MapView from "./MapView";
import { MOCK } from "./mock";
import Panel, { CategoryChips } from "./Panel";
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

  // 카테고리 → 시기 필터 → 정렬 순으로 적용한 전체 결과 (지도에는 이 전체가, 목록에는 "더보기" 단위로 보인다)
  const items = useMemo(() => {
    if (!state.data) return [];
    const byCategory = buildCards(state.data).filter((c) => state.activeCategories.includes(c.spot.category));
    return sortItems(filterByPeriod(byCategory, state.period), state.sort, state.data.t1.target_region.center_coords);
  }, [state.data, state.activeCategories, state.period, state.sort]);
  const shown = useMemo(() => items.slice(0, state.visible), [items, state.visible]);
  const course = useMemo(
    () => (state.showCourse ? state.data?.t3.courses.find((c) => c.course_id === state.courseId) ?? null : null),
    [state.showCourse, state.data, state.courseId],
  );

  const onExplore = useCallback(async () => {
    try {
      const data = await fetchExplore(HOME_PROVINCE, HOME_LABEL);
      const greeting = data.t2.length
        ? `${HOME_PROVINCE}에서 지금 즐길 수 있는 축제와 볼거리를 모았어요. 원하는 분위기나 일정을 말해 주시면 골라 드릴게요.`
        : "아직 수집된 데이터가 없어요. 그래도 원하는 곳을 물어보면 실시간으로 찾아 드려요.";
      dispatch({ type: "explored", data, greeting });
    } catch (e) {
      dispatch({ type: "failure", error: e instanceof Error ? e.message : "알 수 없는 오류" });
    }
  }, []);

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
    />
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
        <BottomSheet>{panel}</BottomSheet>
      </div>
    );
  }
  return (
    <div className="app desktop">
      <aside className="left">{panel}</aside>
      <main className="right">{map}</main>
    </div>
  );
}
