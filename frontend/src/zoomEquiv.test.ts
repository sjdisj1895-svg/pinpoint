import { describe, expect, it } from "vitest";
import { boxForRadius, boxForZoom, equivalentZoom } from "./zoomEquiv";

describe("equivalentZoom", () => {
  it("matches the web mercator definition", () => {
    expect(equivalentZoom(256, 0, 360)).toBeCloseTo(0);
    expect(equivalentZoom(256, 0, 360 / 1024)).toBeCloseTo(10);
    expect(equivalentZoom(1024, 127, 127 + 90)).toBeCloseTo(4); // 1024px가 경도 90°를 보여 주면 z=4
  });
  it("increases by one when the visible span halves", () => {
    const a = equivalentZoom(800, 127, 129);
    const b = equivalentZoom(800, 127, 128);
    expect(b - a).toBeCloseTo(1);
  });
});

describe("boxForZoom", () => {
  it("is the inverse of equivalentZoom for the longitude span", () => {
    const box = boxForZoom(35.2, 128.3, 9, 860, 900);
    expect(equivalentZoom(860, box.west, box.east)).toBeCloseTo(9);
    expect((box.west + box.east) / 2).toBeCloseTo(128.3);
    expect((box.south + box.north) / 2).toBeCloseTo(35.2);
  });
  it("shows a smaller area at a higher zoom", () => {
    const wide = boxForZoom(35.2, 128.3, 9, 800, 800);
    const near = boxForZoom(35.2, 128.3, 13, 800, 800);
    expect(near.east - near.west).toBeLessThan((wide.east - wide.west) / 10);
  });
});

describe("boxForRadius", () => {
  it("is about 2×radius tall and widens in degrees at higher latitude", () => {
    const b = boxForRadius(35, 128, 10);
    expect((b.north - b.south) * 111.32).toBeCloseTo(20, 0);
    expect(b.east - b.west).toBeGreaterThan(b.north - b.south); // 위도 35°에서는 경도 1°가 더 짧다
  });
});
