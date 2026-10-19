import { describe, expect, it } from "vitest";
import { MOCK } from "./mock";
import {
  buildCards, cityOf, filterByQuery, filterByRegion, matchesQuery, regionFacets, tokenize,
} from "./geo";
import { PAGE_SIZE, initialState, reducer } from "./store";
import type { CardItem, Spot } from "./types";

const base: Spot = MOCK.t2[0];
const mk = (id: string, over: Partial<Spot> & { why?: string; tag?: string; address?: string }): CardItem => ({
  spot: {
    ...base, id, ...over,
    location: { ...base.location, region_tag: over.tag ?? base.location.region_tag, address: over.address ?? base.location.address },
    attributes: { ...base.attributes, ...(over.attributes ?? {}) },
  },
  score: null, why: over.why ?? null, tips: [],
});

describe("tokenize", () => {
  it("lowercases, splits on whitespace, caps the count", () => {
    expect(tokenize("  진주   Night ")).toEqual(["진주", "night"]);
    expect(tokenize("   ")).toEqual([]);
    expect(tokenize("a b c d e f g")).toHaveLength(5);
  });
});

describe("matchesQuery (AND, spaces and case ignored)", () => {
  const item = mk("a", { title: "소양강 스카이워크", subtitle: "강 위를 걷는 전망 명소", tag: "경남 진주시", category: "TRAVEL_SPOT" });
  it("finds by title, subtitle, region and category words", () => {
    expect(matchesQuery(item, tokenize("스카이워크"))).toBe(true);
    expect(matchesQuery(item, tokenize("전망"))).toBe(true);
    expect(matchesQuery(item, tokenize("진주시"))).toBe(true);
    expect(matchesQuery(item, tokenize("관광"))).toBe(true); // 분류 동의어
  });
  it("ignores spaces and case", () => {
    expect(matchesQuery(item, tokenize("소양강스카이"))).toBe(true);
    expect(matchesQuery(item, tokenize("스카이 워크"))).toBe(true);
  });
  it("requires every word to match", () => {
    expect(matchesQuery(item, tokenize("진주 스카이워크"))).toBe(true);
    expect(matchesQuery(item, tokenize("진주 영화관"))).toBe(false);
  });
  it("searches the AI recommendation reason too, and an empty query matches everything", () => {
    expect(matchesQuery(mk("b", { title: "x", why: "야경이 아름다워요" }), tokenize("야경"))).toBe(true);
    expect(matchesQuery(item, [])).toBe(true);
  });
});

describe("filters and facets", () => {
  const items = [
    mk("1", { title: "A", tag: "경남 진주시" }), mk("2", { title: "B", tag: "경남 진주시" }),
    mk("3", { title: "C", tag: "경남 통영시" }), mk("4", { title: "D", tag: "부산" }),
  ];
  it("extracts the city token", () => {
    expect(cityOf(items[0].spot)).toBe("진주시");
    expect(cityOf(items[3].spot)).toBe("부산"); // 시·군 토큰이 없으면 첫 토큰
  });
  it("filters by region and query", () => {
    expect(filterByRegion(items, "진주시").map((i) => i.spot.title)).toEqual(["A", "B"]);
    expect(filterByRegion(items, "")).toBe(items);
    expect(filterByQuery(items, "c").map((i) => i.spot.title)).toEqual(["C"]);
    expect(filterByQuery(items, "")).toBe(items);
  });
  it("counts regions, most first", () => {
    expect(regionFacets(items)).toEqual([
      { name: "진주시", count: 2 }, { name: "부산", count: 1 }, { name: "통영시", count: 1 },
    ]);
  });
  it("works on the sample data", () => {
    const all = buildCards(MOCK);
    expect(filterByQuery(all, "춘천 플리마켓").length).toBeGreaterThan(0);
    expect(filterByQuery(all, "없는검색어xyz")).toHaveLength(0);
  });
});

describe("search state", () => {
  it("typing or choosing a region resets the paging", () => {
    const grown = reducer(initialState, { type: "loadMore" });
    expect(reducer(grown, { type: "setQueryInput", text: "진주" })).toMatchObject({ queryInput: "진주", visible: PAGE_SIZE });
    expect(reducer(grown, { type: "setRegion", region: "통영시" })).toMatchObject({ region: "통영시", visible: PAGE_SIZE });
  });
  it("exploreResults keeps other filters but replaces data and facets", () => {
    const s0 = reducer(reducer(initialState, { type: "setPeriod", period: "NOW" }), { type: "setRegion", region: "진주시" });
    const s1 = reducer(s0, { type: "exploreResults", data: MOCK, regions: [{ name: "진주시", count: 3 }], total: 9 });
    expect(s1).toMatchObject({ period: "NOW", region: "진주시", total: 9, regions: [{ name: "진주시", count: 3 }] });
  });
  it("an AI result clears the keyword so it does not re-filter the AI answer", () => {
    const typed = reducer(reducer(initialState, { type: "setQueryInput", text: "이번 주말 진주 데이트" }), { type: "setRegion", region: "진주시" });
    expect(reducer(typed, { type: "success", data: MOCK })).toMatchObject({ queryInput: "", region: "", mode: "search" });
  });
  it("resetFilters clears keyword, region, period and category", () => {
    let s = reducer(initialState, { type: "setQueryInput", text: "x" });
    s = reducer(s, { type: "setRegion", region: "진주시" });
    s = reducer(s, { type: "setPeriod", period: "SOON" });
    s = reducer(s, { type: "toggleCategory", category: "MOVIE" });
    expect(reducer(s, { type: "resetFilters" })).toMatchObject({ queryInput: "", region: "", period: "ALL" });
    expect(reducer(s, { type: "resetFilters" }).activeCategories).toHaveLength(5);
  });
});
