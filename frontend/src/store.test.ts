import { describe, expect, it } from "vitest";
import { MOCK } from "./mock";
import { PAGE_SIZE, applyReroute, initialState, reducer } from "./store";
import type { RerouteResponse } from "./types";

const res = (course: RerouteResponse["course"]): RerouteResponse => ({
  trigger: "WEATHER", summary: "야외 → 실내", preference_notes: [], replacements: [],
  persona: { ...MOCK.t1.user_persona, activity_level: 1 },
  course, pin_list: [{ spot_id: "spot_003", category: "MOVIE", score: 95, why_for_you: "x", tips: [] }],
  markers: { type: "FeatureCollection", features: [] }, route: null,
});

describe("list controls", () => {
  it("starts in explore mode and 더보기 grows the list", () => {
    expect(initialState.mode).toBe("explore");
    const s = reducer(initialState, { type: "loadMore" });
    expect(s.visible).toBe(PAGE_SIZE * 2);
  });
  it("changing period/sort/category resets paging", () => {
    const grown = reducer(initialState, { type: "loadMore" });
    expect(reducer(grown, { type: "setPeriod", period: "NOW" })).toMatchObject({ period: "NOW", visible: PAGE_SIZE });
    expect(reducer(grown, { type: "setSort", sort: "DATE" })).toMatchObject({ sort: "DATE", visible: PAGE_SIZE });
    expect(reducer(grown, { type: "toggleCategory", category: "MOVIE" }).visible).toBe(PAGE_SIZE);
  });
  it("explored shows a greeting once and keeps an existing conversation", () => {
    const first = reducer(initialState, { type: "explored", data: MOCK, greeting: "안녕" });
    expect(first.mode).toBe("explore");
    expect(first.messages).toEqual([{ role: "assistant", text: "안녕" }]);
    const chatted = reducer(reducer(first, { type: "submit", text: "축제" }), { type: "explored", data: MOCK, greeting: "다시" });
    expect(chatted.messages.map((m) => m.text)).toEqual(["안녕", "축제"]);
  });
  it("a search result switches to search mode and resets filters", () => {
    const filtered = reducer(initialState, { type: "setPeriod", period: "SOON" });
    expect(reducer(filtered, { type: "success", data: MOCK })).toMatchObject({ mode: "search", period: "ALL", sort: "RECOMMEND" });
  });
});

describe("applyReroute", () => {
  it("replaces course with same id and updates persona/pins", () => {
    const next = { ...MOCK.t3.courses[0], title: "비 오는 날 코스" };
    const out = applyReroute(MOCK, res(next));
    expect(out.t3.courses).toHaveLength(MOCK.t3.courses.length);
    expect(out.t3.courses[0].title).toBe("비 오는 날 코스");
    expect(out.t1.user_persona.activity_level).toBe(1);
    expect(out.t3.pin_list[0].score).toBe(95);
  });
  it("appends a new course id", () => {
    const out = applyReroute(MOCK, res({ ...MOCK.t3.courses[0], course_id: "course_new" }));
    expect(out.t3.courses).toHaveLength(MOCK.t3.courses.length + 1);
  });
  it("keeps courses when none returned", () => {
    expect(applyReroute(MOCK, res(null)).t3.courses).toEqual(MOCK.t3.courses);
  });
});
