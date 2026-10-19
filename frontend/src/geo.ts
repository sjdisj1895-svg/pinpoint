import type { CardItem, Category, PipelineResponse, Spot, Transport } from "./types";

// 지도 줌 단계: 전국/시·도 → 시·군 → 개별 핀
export const PROVINCE_VIEW_MAX_ZOOM = 7;
export const CITY_VIEW_MAX_ZOOM = 9;

export const CATEGORY_META: Record<Category, { label: string; emoji: string; color: string }> = {
  FESTIVAL: { label: "지역축제", emoji: "🎪", color: "#ff5a36" },
  FLEA_MARKET: { label: "플리마켓/팝업", emoji: "🛍️", color: "#8e44ad" },
  MOVIE: { label: "상영영화", emoji: "🎬", color: "#3f51b5" },
  TRAVEL_SPOT: { label: "여행지", emoji: "🌿", color: "#10b981" },
  NEW_OPEN: { label: "실시간 오픈", emoji: "✨", color: "#f5b301" },
};

export const ALL_CATEGORIES = Object.keys(CATEGORY_META) as Category[];

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** 모델/외부 데이터의 URL은 http(s)만 링크로 허용 */
export function safeUrl(url: string | undefined | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

/** 백엔드가 공식 페이지를 모를 때 넣는 지도 검색 링크 (공식 안내가 아님) */
export function isMapSearchLink(url: string): boolean {
  return url.startsWith("https://map.naver.com/p/search/");
}

export function earliestShowtime(spot: Spot): string | null {
  const times = spot.schedule.movie_showtimes;
  return times && times.length ? [...times].sort()[0] : null;
}

/** 이동 시간(분): 자차 30km/h, 그 외 도보 4.5km/h */
export function travelMinutes(km: number, transport: Transport): number {
  const speed = transport === "CAR" ? 30 : 4.5;
  return Math.max(1, Math.round((km / speed) * 60));
}

export function travelLabel(km: number, transport: Transport): string {
  return `${transport === "CAR" ? "🚗 자차" : "🚶 도보"} ${travelMinutes(km, transport)}분`;
}

export function distanceKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const h =
    Math.sin(rad(b.lat - a.lat) / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(rad(b.lng - a.lng) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

// ---------- 시기 · 상태 표시 ----------
const ISO = /(\d{4})-(\d{2})-(\d{2})/g;

/** "2026-10-20 ~ 2026-10-30" → 시작/종료 (없으면 null) */
export function parsePeriod(spot: Spot): { start: string | null; end: string | null } {
  const dates = [...spot.schedule.period.matchAll(ISO)].map((m) => m[0]);
  return { start: dates[0] ?? null, end: dates[dates.length - 1] ?? null };
}

export function formatPeriod(spot: Spot): string {
  const { start, end } = parsePeriod(spot);
  if (!start || !end) return spot.schedule.period; // "상시", "일정 미확인"
  const f = (d: string) => d.replaceAll("-", ".");
  return start === end ? f(start) : `${f(start)} ~ ${f(end)}`;
}

export function statusLabel(spot: Spot): string {
  const event = spot.category === "FESTIVAL" || spot.category === "FLEA_MARKET";
  switch (spot.schedule.live_status) {
    case "OPEN_NOW": return event ? "개최중" : "운영중";
    case "OPEN_SOON": return event ? "개최예정" : "오픈예정";
    default: return "종료";
  }
}

export function regionLabel(spot: Spot): string {
  return spot.location.region_tag || spot.location.address.split(" ").slice(0, 2).join(" ");
}

// ---------- 목록 필터·정렬 ----------
export type PeriodFilter = "ALL" | "NOW" | "SOON";
export type SortKey = "RECOMMEND" | "DATE" | "DISTANCE";

export function filterByPeriod(items: CardItem[], period: PeriodFilter): CardItem[] {
  if (period === "ALL") return items;
  const want = period === "NOW" ? "OPEN_NOW" : "OPEN_SOON";
  return items.filter((i) => i.spot.schedule.live_status === want);
}

export function sortItems(items: CardItem[], sort: SortKey, center?: { lat: number; lng: number }): CardItem[] {
  const out = [...items];
  if (sort === "DATE") {
    // 시작일이 빠른 순, 날짜 없는 항목은 뒤로
    out.sort((a, b) => (parsePeriod(a.spot).start ?? "9999").localeCompare(parsePeriod(b.spot).start ?? "9999"));
  } else if (sort === "DISTANCE" && center) {
    out.sort((a, b) => distanceKm(center, a.spot.location) - distanceKm(center, b.spot.location));
  }
  return out; // RECOMMEND는 buildCards의 순서(점수 → 신뢰도) 그대로
}

// ---------- 지도: 줌 단계별 집계 ----------
export interface SpotGroup {
  key: string;
  label: string;
  lat: number;
  lng: number;
  count: number;
  representative: Spot;
}

/** level=province: "경남", city: "경남 진주시" 단위로 묶어 개수와 대표 스팟을 만든다 */
export function groupSpots(spots: Spot[], level: "province" | "city"): SpotGroup[] {
  const by = new Map<string, Spot[]>();
  for (const s of spots) {
    const tokens = (s.location.region_tag || "기타").split(/\s+/);
    const key = level === "province" ? tokens[0] : tokens.slice(0, 2).join(" ");
    by.set(key, [...(by.get(key) ?? []), s]);
  }
  const isEvent = (s: Spot) => s.category === "FESTIVAL" || s.category === "FLEA_MARKET";
  return [...by.entries()].map(([key, list]) => ({
    key,
    label: level === "province" ? key : key.split(" ").slice(1).join(" ") || key,
    lat: list.reduce((a, s) => a + s.location.lat, 0) / list.length,
    lng: list.reduce((a, s) => a + s.location.lng, 0) / list.length,
    count: list.length,
    // 대표: 행사 우선, 그다음 신뢰도 높은 순
    representative: [...list].sort(
      (a, b) => Number(isEvent(b)) - Number(isEvent(a)) || b.confidence_score - a.confidence_score,
    )[0],
  }));
}

/** 스팟 + T3 추천 정보 결합. 점수 있는 항목 우선, 이후 신뢰도순 */
export function buildCards(data: PipelineResponse): CardItem[] {
  const pins = new Map(data.t3.pin_list.map((p) => [p.spot_id, p]));
  return data.t2
    .map((spot) => {
      const pin = pins.get(spot.id);
      return { spot, score: pin?.score ?? null, why: pin?.why_for_you ?? null, tips: pin?.tips ?? [] };
    })
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || b.spot.confidence_score - a.spot.confidence_score);
}
