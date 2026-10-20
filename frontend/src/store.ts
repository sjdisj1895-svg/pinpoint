import type { Category, PipelineResponse, RegionFacet, RerouteResponse } from "./types";
import { ALL_CATEGORIES } from "./geo";
import type { PeriodFilter, SortKey } from "./geo";

/** 리라우팅 결과를 기존 데이터에 패치: 페르소나·핀 리스트 교체, 코스는 같은 id면 교체/없으면 추가 */
export function applyReroute(data: PipelineResponse, res: RerouteResponse): PipelineResponse {
  const courses = res.course
    ? data.t3.courses.some((c) => c.course_id === res.course!.course_id)
      ? data.t3.courses.map((c) => (c.course_id === res.course!.course_id ? res.course! : c))
      : [...data.t3.courses, res.course]
    : data.t3.courses;
  return {
    ...data,
    t1: { ...data.t1, user_persona: res.persona },
    t3: { pin_list: res.pin_list.length ? res.pin_list : data.t3.pin_list, courses },
  };
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export const PAGE_SIZE = 12; // "더보기" 한 번에 보여 줄 카드 수

export interface State {
  data: PipelineResponse | null;
  mode: "explore" | "search"; // explore: 권역 둘러보기(AI 없음), search: 채팅 추천 결과
  loading: boolean;
  error: string | null;
  messages: ChatMessage[];
  activeCategories: Category[];
  queryInput: string; // 검색창에 입력 중인 키워드 (내부 검색. AI 호출 없음)
  region: string; // 선택한 시·군 ("" = 전체)
  months: number[]; // 체크한 달(1~12). 비면 월 필터 없음
  regions: RegionFacet[]; // 둘러보기에서 서버가 알려 준 시·군별 개수
  total: number | null; // 둘러보기에서 한도로 자르기 전 일치 개수
  period: PeriodFilter;
  sort: SortKey;
  visible: number; // 목록에 보이는 카드 수
  selectedId: string | null; // 클릭
  hoveredId: string | null; // 호버
  showCourse: boolean;
  courseId: string | null;
}

export const initialState: State = {
  data: null,
  mode: "explore",
  loading: false,
  error: null,
  messages: [],
  activeCategories: ALL_CATEGORIES,
  queryInput: "",
  region: "",
  months: [],
  regions: [],
  total: null,
  period: "ALL",
  sort: "RECOMMEND",
  visible: PAGE_SIZE,
  selectedId: null,
  hoveredId: null,
  showCourse: false,
  courseId: null,
};

export type Action =
  | { type: "submit"; text: string }
  | { type: "explored"; data: PipelineResponse; greeting: string; regions?: RegionFacet[]; total?: number }
  | { type: "exploreResults"; data: PipelineResponse; regions: RegionFacet[]; total: number }
  | { type: "setQueryInput"; text: string }
  | { type: "setRegion"; region: string }
  | { type: "toggleMonth"; month: number }
  | { type: "clearMonths" }
  | { type: "resetFilters" }
  | { type: "setPeriod"; period: PeriodFilter }
  | { type: "setSort"; sort: SortKey }
  | { type: "loadMore" }
  | { type: "success"; data: PipelineResponse; note?: string }
  | { type: "failure"; error: string }
  | { type: "rerouted"; res: RerouteResponse }
  | { type: "toggleCategory"; category: Category }
  | { type: "select"; id: string | null }
  | { type: "hover"; id: string | null }
  | { type: "toggleCourse" }
  | { type: "pickCourse"; id: string };

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "submit":
      return {
        ...state, loading: true, error: null,
        messages: [...state.messages, { role: "user", text: action.text }],
      };
    case "explored":
      return {
        ...state,
        data: action.data,
        mode: "explore",
        loading: false,
        error: null,
        selectedId: null,
        hoveredId: null,
        showCourse: false,
        courseId: null,
        activeCategories: ALL_CATEGORIES,
        queryInput: "",
        region: "",
        months: [],
        regions: action.regions ?? [],
        total: action.total ?? action.data.t2.length,
        period: "ALL",
        sort: "RECOMMEND",
        visible: PAGE_SIZE,
        messages: state.messages.length ? state.messages : [{ role: "assistant", text: action.greeting }],
      };
    // 검색어·지역을 바꿔 다시 불러온 결과: 분류·시기·정렬 같은 다른 필터는 그대로 둔다
    case "exploreResults":
      return {
        ...state, data: action.data, regions: action.regions, total: action.total, visible: PAGE_SIZE, error: null,
        selectedId: null, hoveredId: null,
      };
    case "setQueryInput":
      return { ...state, queryInput: action.text, visible: PAGE_SIZE };
    case "setRegion":
      return { ...state, region: action.region, visible: PAGE_SIZE };
    case "toggleMonth": {
      const on = state.months.includes(action.month);
      const months = on ? state.months.filter((m) => m !== action.month) : [...state.months, action.month].sort((a, b) => a - b);
      return { ...state, months, visible: PAGE_SIZE };
    }
    case "clearMonths":
      return { ...state, months: [], visible: PAGE_SIZE };
    case "resetFilters":
      return {
        ...state, queryInput: "", region: "", months: [], period: "ALL", activeCategories: ALL_CATEGORIES,
        sort: "RECOMMEND", visible: PAGE_SIZE,
      };
    case "setPeriod":
      return { ...state, period: action.period, visible: PAGE_SIZE };
    case "setSort":
      return { ...state, sort: action.sort, visible: PAGE_SIZE };
    case "loadMore":
      return { ...state, visible: state.visible + PAGE_SIZE };
    case "success": {
      const { data } = action;
      const summary = `스팟 ${data.t2.length}곳, 추천 코스 ${data.t3.courses.length}개를 찾았어요.`;
      return {
        ...state,
        data,
        mode: "search",
        queryInput: "", // AI에게 물은 문장은 키워드 검색어로 남기지 않는다 (남기면 AI 결과가 그 문장으로 다시 걸러진다)
        region: "",
        months: [],
        regions: [],
        total: null,
        period: "ALL",
        sort: "RECOMMEND",
        visible: PAGE_SIZE,
        loading: false,
        selectedId: null,
        hoveredId: null,
        showCourse: false,
        courseId: data.t3.courses[0]?.course_id ?? null,
        activeCategories: data.t1.requested_categories.length ? data.t1.requested_categories : ALL_CATEGORIES,
        messages: [...state.messages, { role: "assistant", text: action.note ? `${summary}\n${action.note}` : summary }],
      };
    }
    case "failure":
      return { ...state, loading: false, error: action.error };
    case "rerouted": {
      if (!state.data) return state;
      const { res } = action;
      const notes = res.preference_notes.length ? `\n반영한 취향: ${res.preference_notes.join(", ")}` : "";
      const noCourse = res.course ? "" : "\n조건에 맞는 새 코스를 만들 수 없어 기존 코스를 유지했어요.";
      return {
        ...state,
        data: applyReroute(state.data, res),
        loading: false,
        error: null,
        selectedId: null,
        showCourse: res.course ? true : state.showCourse,
        courseId: res.course?.course_id ?? state.courseId,
        messages: [...state.messages, { role: "assistant", text: res.summary + notes + noCourse }],
      };
    }
    case "toggleCategory": {
      const on = state.activeCategories.includes(action.category);
      return {
        ...state,
        visible: PAGE_SIZE,
        activeCategories: on
          ? state.activeCategories.filter((c) => c !== action.category)
          : [...state.activeCategories, action.category],
      };
    }
    case "select":
      return { ...state, selectedId: action.id };
    case "hover":
      return { ...state, hoveredId: action.id };
    case "toggleCourse":
      return { ...state, showCourse: !state.showCourse };
    case "pickCourse":
      return { ...state, courseId: action.id, showCourse: true };
  }
}
