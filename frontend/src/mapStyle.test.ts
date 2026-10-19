import { describe, expect, it } from "vitest";
import {
  DEFAULT_TILE, FALLBACK_TILE, KOREAN_LABEL, TILE_STYLES, koreanizeStyle, pickTileStyle, webglAvailable,
} from "./mapStyle";

describe("koreanizeStyle", () => {
  const style = {
    version: 8,
    layers: [
      { id: "bg", type: "background" },
      { id: "place", type: "symbol", layout: { "text-field": ["coalesce", ["get", "name:latin"], ["get", "name:nonlatin"]] } },
      { id: "city", type: "symbol", layout: { "text-field": "{name}", "text-size": 12 } },
      { id: "road-number", type: "symbol", layout: { "text-field": ["get", "ref"] } },
      { id: "icon-only", type: "symbol", layout: { "icon-image": "dot" } },
    ],
  };
  it("switches name labels to Korean-first and leaves other labels alone", () => {
    const out = koreanizeStyle(style);
    const field = (id: string) => out.layers.find((l) => l.id === id)?.layout?.["text-field"];
    expect(field("place")).toEqual(KOREAN_LABEL);
    expect(field("city")).toEqual(KOREAN_LABEL);
    expect(field("road-number")).toEqual(["get", "ref"]); // 도로 번호는 그대로
    expect(out.layers.find((l) => l.id === "city")?.layout?.["text-size"]).toBe(12); // 다른 속성 유지
    expect(out.layers.find((l) => l.id === "icon-only")?.layout).toEqual({ "icon-image": "dot" });
  });
  it("does not mutate the input style", () => {
    const before = JSON.stringify(style);
    koreanizeStyle(style);
    expect(JSON.stringify(style)).toBe(before);
  });
  it("handles styles without layers", () => {
    expect(koreanizeStyle({})).toEqual({});
  });
});

describe("pickTileStyle", () => {
  it("uses the default vector style when nothing is requested", () => {
    expect(pickTileStyle("", true)).toBe(TILE_STYLES[DEFAULT_TILE]);
    expect(pickTileStyle("?sample", true)).toBe(TILE_STYLES[DEFAULT_TILE]);
    expect(TILE_STYLES[DEFAULT_TILE].kind).toBe("vector");
  });
  it("lets the URL pick another style for comparison", () => {
    expect(pickTileStyle("?tiles=positron", true)).toBe(TILE_STYLES.positron);
    expect(pickTileStyle("?x=1&tiles=bright", true)).toBe(TILE_STYLES.bright);
  });
  it("falls back to the default for unknown names", () => {
    expect(pickTileStyle("?tiles=nope", true)).toBe(TILE_STYLES[DEFAULT_TILE]);
  });
  it("uses raster tiles when WebGL is unavailable", () => {
    expect(pickTileStyle("", false)).toBe(TILE_STYLES[FALLBACK_TILE]);
    expect(pickTileStyle("?tiles=positron", false).kind).toBe("raster");
    expect(pickTileStyle("?tiles=osm", false)).toBe(TILE_STYLES.osm); // 래스터를 직접 고르면 그대로
  });
  it("detects missing WebGL safely outside a browser", () => {
    expect(webglAvailable()).toBe(false); // 테스트 환경에는 document가 없다
  });
  it("every style carries an attribution and valid source info", () => {
    for (const s of Object.values(TILE_STYLES)) {
      expect(s.attribution.length).toBeGreaterThan(10);
      if (s.kind === "raster") expect(s.url).toMatch(/\{z\}.*\{x\}.*\{y\}/);
      else expect(s.style).toMatch(/^https:\/\/tiles\.openfreemap\.org\/styles\//);
    }
  });
});
