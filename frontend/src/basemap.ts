import L from "leaflet";
import { TILE_STYLES, koreanizeStyle } from "./mapStyle";
import type { TileStyle } from "./mapStyle";

function addRaster(map: L.Map, t: Extract<TileStyle, { kind: "raster" }>): void {
  L.tileLayer(t.url, { maxZoom: 19, attribution: t.attribution, subdomains: t.subdomains ?? "abc" }).addTo(map);
}

/**
 * 바탕 지도를 붙인다. 벡터 지도(MapLibre)는 용량이 커서 필요할 때만 따로 불러오고(code splitting),
 * 불러오기에 실패하면 OSM 래스터 타일로 대체한다. isActive: 그 사이 지도가 사라졌으면 false.
 */
export async function loadBasemap(map: L.Map, tiles: TileStyle, isActive: () => boolean): Promise<void> {
  if (tiles.kind === "raster") {
    addRaster(map, tiles);
    return;
  }
  try {
    const [maplibre, worker] = await Promise.all([
      import("maplibre-gl"),
      import("maplibre-gl/dist/maplibre-gl-worker.mjs?url"), // 번들러에서는 worker 파일 경로를 직접 알려 줘야 한다
      import("@maplibre/maplibre-gl-leaflet"), // L.maplibreGL 등록
    ]);
    maplibre.setWorkerUrl(worker.default);
    const res = await fetch(tiles.style);
    if (!res.ok) throw new Error(`style ${res.status}`);
    const style = koreanizeStyle(await res.json());
    if (!isActive()) return;
    L.maplibreGL({ style }).addTo(map); // 출처 표기는 스타일이 가진 것을 플러그인이 자동으로 붙인다 (직접 또 넣으면 두 번 보인다)
  } catch (e) {
    console.warn("벡터 지도를 불러오지 못해 기본 지도로 대체합니다.", e);
    if (isActive()) addRaster(map, TILE_STYLES.osm as Extract<TileStyle, { kind: "raster" }>);
  }
}
