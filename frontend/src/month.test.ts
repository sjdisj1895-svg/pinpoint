import { describe, expect, it } from "vitest";
import { MOCK } from "./mock";
import { currentMonth, filterByMonths, monthCounts, monthsCovered } from "./geo";
import { initialState, reducer } from "./store";
import type { CardItem, Spot } from "./types";

const base: Spot = MOCK.t2[0];
const withPeriod = (id: string, period: string): CardItem => ({
  spot: { ...base, id, schedule: { ...base.schedule, period } }, score: null, why: null, tips: [],
});

describe("monthsCovered", () => {
  it("lists every month an event spans", () => {
    expect(monthsCovered(withPeriod("a", "2026-10-20 ~ 2026-10-30").spot)).toEqual([10]);
    expect(monthsCovered(withPeriod("a", "2026-09-22 ~ 2026-11-01").spot)).toEqual([9, 10, 11]);
  });
  it("wraps over the new year", () => {
    expect(monthsCovered(withPeriod("a", "2026-12-20 ~ 2027-02-10").spot)).toEqual([12, 1, 2]);
  });
  it("covers a whole year for year-round events", () => {
    expect(monthsCovered(withPeriod("a", "2026-01-01 ~ 2026-12-31").spot)).toHaveLength(12);
  });
  it("is empty for undated places and a malformed range", () => {
    expect(monthsCovered(withPeriod("a", "상시").spot)).toEqual([]);
    expect(monthsCovered(withPeriod("a", "일정 미확인").spot)).toEqual([]);
    expect(monthsCovered(withPeriod("a", "2026-11-10 ~ 2026-10-01").spot)).toEqual([]);
  });
});

describe("filterByMonths", () => {
  const items = [
    withPeriod("oct", "2026-10-17 ~ 2026-10-25"),
    withPeriod("sepnov", "2026-09-22 ~ 2026-11-01"),
    withPeriod("nov", "2026-11-06 ~ 2026-11-10"),
    withPeriod("always", "상시"),
  ];
  const ids = (xs: CardItem[]) => xs.map((i) => i.spot.id);
  it("returns everything when no month is checked", () => {
    expect(filterByMonths(items, [])).toBe(items);
  });
  it("keeps events that overlap the checked month, drops undated places", () => {
    expect(ids(filterByMonths(items, [10]))).toEqual(["oct", "sepnov"]);
    expect(ids(filterByMonths(items, [11]))).toEqual(["sepnov", "nov"]);
  });
  it("any of several checked months matches", () => {
    expect(ids(filterByMonths(items, [9, 11]))).toEqual(["sepnov", "nov"]);
    expect(ids(filterByMonths(items, [3]))).toEqual([]);
  });
  it("counts events per month", () => {
    const c = monthCounts(items);
    expect(c[10]).toBe(2);
    expect(c[11]).toBe(2);
    expect(c[9]).toBe(1);
    expect(c[3]).toBeUndefined();
  });
});

describe("month state", () => {
  it("toggles months and keeps them sorted", () => {
    let s = reducer(initialState, { type: "toggleMonth", month: 11 });
    s = reducer(s, { type: "toggleMonth", month: 10 });
    expect(s.months).toEqual([10, 11]);
    s = reducer(s, { type: "toggleMonth", month: 11 });
    expect(s.months).toEqual([10]);
    expect(reducer(s, { type: "clearMonths" }).months).toEqual([]);
  });
  it("is cleared by resetFilters, a home reload and an AI result", () => {
    const s = reducer(initialState, { type: "toggleMonth", month: 10 });
    expect(reducer(s, { type: "resetFilters" }).months).toEqual([]);
    expect(reducer(s, { type: "explored", data: MOCK, greeting: "hi" }).months).toEqual([]);
    expect(reducer(s, { type: "success", data: MOCK }).months).toEqual([]);
  });
  it("is kept when only the keyword or region results are refreshed", () => {
    const s = reducer(initialState, { type: "toggleMonth", month: 10 });
    expect(reducer(s, { type: "exploreResults", data: MOCK, regions: [], total: 1 }).months).toEqual([10]);
  });
  it("currentMonth is 1..12", () => {
    expect(currentMonth(new Date(2026, 9, 20))).toBe(10);
    expect(currentMonth(new Date(2026, 0, 1))).toBe(1);
  });
});
