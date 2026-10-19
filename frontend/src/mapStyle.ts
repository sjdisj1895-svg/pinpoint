// 지도 스타일. 다른 스타일로 바꾸려면 여기만 고치면 된다.
// 기본은 OpenFreeMap 벡터 지도(키·가입 불필요, 상업 이용 가능, 출처 표기 필요)다.
// WebGL을 못 쓰는 환경에서는 OSM 래스터 타일로 자동 대체한다.
export type TileStyle =
  | { kind: "raster"; url: string; attribution: string; subdomains?: string }
  | { kind: "vector"; style: string; attribution: string };

const OPENFREEMAP_ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> ' +
  '&copy; <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> ' +
  'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';

const vector = (name: string): TileStyle => ({
  kind: "vector",
  style: `https://tiles.openfreemap.org/styles/${name}`,
  attribution: OPENFREEMAP_ATTRIBUTION,
});

export const TILE_STYLES: Record<string, TileStyle> = {
  liberty: vector("liberty"), // 색이 풍부하고 건물·지형이 보이는 스타일
  bright: vector("bright"), // 밝고 선명한 일반 스타일
  positron: vector("positron"), // 거의 무채색이라 컬러 핀이 가장 돋보이는 미니멀 스타일
  // WebGL을 못 쓸 때의 대체 (예전 기본 지도)
  osm: {
    kind: "raster",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors",
    subdomains: "abc",
  },
};

export const DEFAULT_TILE = "positron";
export const FALLBACK_TILE = "osm";

/** 지명 라벨을 한글 이름(name:ko) 우선으로 바꾼다. 도로 번호 같은 name이 아닌 라벨은 그대로 둔다. 입력은 바꾸지 않는다. */
export const KOREAN_LABEL = ["coalesce", ["get", "name:ko"], ["get", "name"]];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function koreanizeStyle<T extends { layers?: any[] }>(style: T): T {
  const copy = structuredClone(style);
  for (const layer of copy.layers ?? []) {
    const field = layer.layout?.["text-field"];
    if (field !== undefined && JSON.stringify(field).includes("name")) layer.layout["text-field"] = KOREAN_LABEL;
  }
  return copy;
}

export function webglAvailable(): boolean {
  if (typeof document === "undefined") return false;
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

/** 주소의 ?tiles=positron 처럼 미리 비교해 볼 수 있다. 알 수 없는 이름이면 기본 스타일, WebGL이 없으면 래스터로 대체 */
export function pickTileStyle(search: string, webgl: boolean = webglAvailable()): TileStyle {
  const name = new URLSearchParams(search).get("tiles") ?? DEFAULT_TILE;
  const style = TILE_STYLES[name] ?? TILE_STYLES[DEFAULT_TILE];
  return style.kind === "vector" && !webgl ? TILE_STYLES[FALLBACK_TILE] : style;
}
