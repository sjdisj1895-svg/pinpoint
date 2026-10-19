// 지도 위에 올리는 핀·배지의 HTML. Leaflet과 카카오맵이 같은 모양을 쓰도록 한곳에 둔다.
// 모든 외부 문자열은 escapeHtml을 거친다.
import { CATEGORY_META, earliestShowtime, escapeHtml } from "./geo";
import type { SpotGroup } from "./geo";
import type { Spot } from "./types";

export const PIN_SIZE: [number, number] = [40, 40];
export const PIN_ANCHOR: [number, number] = [20, 40]; // 핀 끝(아래 가운데)이 좌표
export const ORDER_SIZE: [number, number] = [28, 28];
export const ORDER_ANCHOR: [number, number] = [40, 52]; // 핀 머리의 왼쪽 위 (이모지·뱃지를 가리지 않게)
export const LEG_SIZE: [number, number] = [90, 22];

export function pinHtml(spot: Spot, focused: boolean): string {
  const meta = CATEGORY_META[spot.category];
  const live = spot.schedule.live_status === "OPEN_NOW";
  let badge = "";
  if (spot.category === "FLEA_MARKET" && live) badge = `<span class="pp-badge">오늘열림</span>`;
  if (spot.category === "NEW_OPEN" && live) badge = `<span class="pp-badge pp-live">LIVE OPEN</span>`;
  if (spot.category === "MOVIE") {
    const t = earliestShowtime(spot);
    if (t) badge = `<span class="pp-badge pp-time">🎬 ${escapeHtml(t)}</span>`;
  }
  const pulse = spot.category === "FESTIVAL" || (spot.category === "NEW_OPEN" && live) ? " pp-pulse" : "";
  return (
    `<div class="pp-pin${pulse}${focused ? " pp-bounce" : ""}" style="--c:${meta.color}">` +
    `<span class="pp-emoji">${meta.emoji}</span>${badge}</div>`
  );
}

export function regionHtml(g: SpotGroup, compact: boolean): string {
  const rep = CATEGORY_META[g.representative.category];
  const repLine = compact ? "" : `<div class="pp-region-rep">${rep.emoji} ${escapeHtml(g.representative.title)}</div>`;
  return (
    `<div class="pp-region${compact ? " compact" : ""}"><div class="pp-region-count">${g.count}</div>` +
    `<div class="pp-region-name">${escapeHtml(g.label)}</div>${repLine}</div>`
  );
}

export function regionSize(compact: boolean): [number, number] {
  return compact ? [72, 44] : [120, 64];
}

export const orderHtml = (n: number): string => `<div class="pp-order">${n}</div>`;
export const legHtml = (label: string): string => `<div class="pp-leg">${escapeHtml(label)}</div>`;
