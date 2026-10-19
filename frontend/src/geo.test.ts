import { describe, expect, it } from "vitest";
import { MOCK } from "./mock";
import {
  buildCards, distanceKm, earliestShowtime, escapeHtml, filterByPeriod, formatPeriod, groupSpots, isMapSearchLink,
  parsePeriod, regionLabel, safeUrl, sortItems, statusLabel, travelMinutes,
} from "./geo";
import type { Spot } from "./types";

const spot = (over: Partial<Spot> & { id: string }): Spot => ({
  ...MOCK.t2[0], ...over, schedule: { ...MOCK.t2[0].schedule, ...(over.schedule ?? {}) },
  location: { ...MOCK.t2[0].location, ...(over.location ?? {}) },
});
const card = (s: Spot) => ({ spot: s, score: null, why: null, tips: [] });

describe("geo helpers", () => {
  it("escapes html", () => {
    expect(escapeHtml(`<img onerror="x">`)).not.toContain("<");
  });
  it("blocks non-http urls", () => {
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("https://a.kr/x")).toContain("https://a.kr");
    expect(safeUrl(undefined)).toBeNull();
  });
  it("detects map search links (not official pages)", () => {
    expect(isMapSearchLink("https://map.naver.com/p/search/%EA%B2%BD%EB%B3%B5%EA%B6%81")).toBe(true);
    expect(isMapSearchLink("https://chuncheon.go.kr/fest")).toBe(false);
  });
  it("travel time", () => {
    expect(travelMinutes(1.5, "WALK")).toBe(20);
    expect(travelMinutes(15, "CAR")).toBe(30);
  });
  it("earliest showtime", () => {
    const m = MOCK.t2.find((s) => s.category === "MOVIE")!;
    expect(earliestShowtime(m)).toBe("14:20");
  });
  it("cards: scored first", () => {
    expect(buildCards(MOCK)[0].score).not.toBeNull();
  });
  it("distance", () => {
    expect(distanceKm({ lat: 37.88, lng: 127.73 }, { lat: 37.88, lng: 127.73 })).toBe(0);
    expect(distanceKm({ lat: 37.88, lng: 127.73 }, { lat: 37.884, lng: 127.733 })).toBeGreaterThan(0.4);
  });
});

describe("period and status display", () => {
  it("parses and formats dated periods", () => {
    const s = spot({ id: "a", schedule: { ...MOCK.t2[0].schedule, period: "2026-10-20 ~ 2026-10-30" } });
    expect(parsePeriod(s)).toEqual({ start: "2026-10-20", end: "2026-10-30" });
    expect(formatPeriod(s)).toBe("2026.10.20 ~ 2026.10.30");
  });
  it("keeps non-date periods as-is", () => {
    const s = spot({ id: "a", schedule: { ...MOCK.t2[0].schedule, period: "상시" } });
    expect(parsePeriod(s)).toEqual({ start: null, end: null });
    expect(formatPeriod(s)).toBe("상시");
  });
  it("status labels differ for events and places", () => {
    const fest = spot({ id: "f", category: "FESTIVAL", schedule: { ...MOCK.t2[0].schedule, live_status: "OPEN_NOW" } });
    const cafe = spot({ id: "c", category: "NEW_OPEN", schedule: { ...MOCK.t2[0].schedule, live_status: "OPEN_SOON" } });
    expect(statusLabel(fest)).toBe("개최중");
    expect(statusLabel(cafe)).toBe("오픈예정");
    expect(statusLabel(spot({ id: "x", schedule: { ...MOCK.t2[0].schedule, live_status: "CLOSED" } }))).toBe("종료");
  });
  it("region label falls back to the address", () => {
    expect(regionLabel(spot({ id: "a", location: { ...MOCK.t2[0].location, region_tag: "" } }))).toBe("강원 춘천");
    expect(regionLabel(spot({ id: "b", location: { ...MOCK.t2[0].location, region_tag: "경남 진주시" } }))).toBe("경남 진주시");
  });
});

describe("filter and sort", () => {
  const items = buildCards(MOCK);
  it("filters by period", () => {
    const now = filterByPeriod(items, "NOW");
    const soon = filterByPeriod(items, "SOON");
    expect(now.every((i) => i.spot.schedule.live_status === "OPEN_NOW")).toBe(true);
    expect(soon.length).toBeGreaterThan(0);
    expect(now.length + soon.length).toBe(items.length);
    expect(filterByPeriod(items, "ALL")).toBe(items);
  });
  it("sorts by start date with undated last", () => {
    const mk = (id: string, period: string) => card(spot({ id, schedule: { ...MOCK.t2[0].schedule, period } }));
    const out = sortItems([mk("b", "상시"), mk("c", "2026-11-01 ~ 2026-11-02"), mk("a", "2026-10-05 ~ 2026-10-06")], "DATE");
    expect(out.map((i) => i.spot.id)).toEqual(["a", "c", "b"]);
  });
  it("sorts by distance from a center and does not mutate input", () => {
    const center = { lat: 37.88, lng: 127.73 }; // 춘천
    const before = items.map((i) => i.spot.id);
    const out = sortItems(items, "DISTANCE", center);
    expect(out[0].spot.location.region_tag).toContain("춘천");
    expect(out[out.length - 1].spot.location.region_tag).not.toContain("춘천");
    expect(items.map((i) => i.spot.id)).toEqual(before); // 원본 배열은 그대로
  });
  it("RECOMMEND keeps the card order", () => {
    expect(sortItems(items, "RECOMMEND").map((i) => i.spot.id)).toEqual(items.map((i) => i.spot.id));
  });
});

describe("map grouping", () => {
  it("province level counts every spot and prefers an event as representative", () => {
    const g = groupSpots(MOCK.t2, "province");
    const gangwon = g.find((x) => x.key === "강원")!;
    expect(gangwon.count).toBe(5);
    expect(["FESTIVAL", "FLEA_MARKET"]).toContain(gangwon.representative.category);
    expect(g.reduce((n, x) => n + x.count, 0)).toBe(MOCK.t2.length);
  });
  it("city level uses the city token as label", () => {
    const g = groupSpots(MOCK.t2, "city");
    expect(g.find((x) => x.key === "부산 광안리")!.label).toBe("광안리");
    expect(g.length).toBeGreaterThan(groupSpots(MOCK.t2, "province").length - 1);
  });
});
