import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { CardItem, Course, PipelineResponse, Spot, Transport } from "./types";
import {
  CATEGORY_META, CITY_VIEW_MAX_ZOOM, PROVINCE_VIEW_MAX_ZOOM, earliestShowtime, escapeHtml, groupSpots, travelLabel,
} from "./geo";

interface Props {
  data: PipelineResponse | null;
  items: CardItem[]; // 카테고리 필터 적용된 스팟
  course: Course | null; // 표시할 코스(토글 on일 때만 전달)
  transport: Transport;
  focusId: string | null; // 호버/선택된 스팟
  selectedId: string | null;
  onSelect: (id: string) => void;
  padBottom?: number; // 모바일 바텀시트에 가려지는 높이(px). 지도 맞춤 시 여백으로 쓴다
  compact?: boolean; // 좁은 화면: 배지를 작게(개수+지역명만)
}

const KOREA_CENTER: L.LatLngTuple = [36.4, 127.9];

function pinIcon(spot: Spot, focused: boolean): L.DivIcon {
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
  const html =
    `<div class="pp-pin${pulse}${focused ? " pp-bounce" : ""}" style="--c:${meta.color}">` +
    `<span class="pp-emoji">${meta.emoji}</span>${badge}</div>`;
  return L.divIcon({ className: "pp-icon", html, iconSize: [40, 40], iconAnchor: [20, 40] });
}

export default function MapView({
  data, items, course, transport, focusId, selectedId, onSelect, padBottom = 0, compact = false,
}: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerLayer = useRef(L.layerGroup());
  const courseLayer = useRef(L.layerGroup());
  const [zoom, setZoom] = useState(7);
  // 줌 단계: 시·도 배지 → 시·군 배지 → 개별 핀
  const level = zoom <= PROVINCE_VIEW_MAX_ZOOM ? "province" : zoom <= CITY_VIEW_MAX_ZOOM ? "city" : "pin";

  // 지도 초기화
  useEffect(() => {
    const map = L.map(elRef.current!, { center: KOREA_CENTER, zoom: 7, zoomControl: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    markerLayer.current.addTo(map);
    courseLayer.current.addTo(map);
    map.on("zoomend", () => setZoom(map.getZoom()));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // 새 결과 도착 시 T1 탐색 반경에 맞춰 이동
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !data) return;
    const { center_coords: c, radius_km } = data.t1.target_region;
    // 지도에 올리지 않은 L.circle은 getBounds()가 실패하므로 LatLng.toBounds(한 변의 길이 m)를 쓴다
    map.fitBounds(L.latLng(c.lat, c.lng).toBounds(radius_km * 2000), { paddingBottomRight: [0, padBottom] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // 마커 렌더링 (줌 레벨 적응)
  useEffect(() => {
    const map = mapRef.current;
    const layer = markerLayer.current;
    if (!map) return;
    layer.clearLayers();
    const spots = items.map((i) => i.spot);

    if (level !== "pin") {
      for (const g of groupSpots(spots, level)) {
        const rep = CATEGORY_META[g.representative.category];
        const repLine = compact ? "" : `<div class="pp-region-rep">${rep.emoji} ${escapeHtml(g.representative.title)}</div>`;
        const html =
          `<div class="pp-region${compact ? " compact" : ""}"><div class="pp-region-count">${g.count}</div>` +
          `<div class="pp-region-name">${escapeHtml(g.label)}</div>${repLine}</div>`;
        const size: L.PointTuple = compact ? [72, 44] : [120, 64];
        L.marker([g.lat, g.lng], {
          icon: L.divIcon({ className: "pp-icon", html, iconSize: size, iconAnchor: [size[0] / 2, size[1] / 2] }),
          title: `${g.label} ${g.count}곳`,
        })
          // 시·도 배지는 시·군 단계로, 시·군 배지는 개별 핀 단계로 확대
          .on("click", () => map.setView([g.lat, g.lng], level === "province" ? PROVINCE_VIEW_MAX_ZOOM + 2 : CITY_VIEW_MAX_ZOOM + 2))
          .addTo(layer);
      }
      return;
    }

    for (const spot of spots) {
      L.marker([spot.location.lat, spot.location.lng], {
        icon: pinIcon(spot, spot.id === focusId || spot.id === selectedId),
        title: spot.title,
        zIndexOffset: spot.id === focusId || spot.id === selectedId ? 1000 : 0,
      })
        .bindTooltip(escapeHtml(spot.title), { direction: "top", offset: [0, -36] })
        .on("click", () => onSelect(spot.id))
        .addTo(layer);
    }
  }, [items, level, focusId, selectedId, onSelect, compact]);

  // 카드 호버/클릭 → panTo
  useEffect(() => {
    const map = mapRef.current;
    const spot = items.find((i) => i.spot.id === focusId)?.spot ?? data?.t2.find((s) => s.id === focusId);
    if (!map || !spot) return;
    const ll: L.LatLngTuple = [spot.location.lat, spot.location.lng];
    if (map.getZoom() <= CITY_VIEW_MAX_ZOOM) {
      // 배지 단계에서는 카드를 클릭했을 때만 확대한다. 호버만으로 지도가 튀지 않게 한다.
      if (focusId === selectedId) map.setView(ll, 13);
    } else {
      map.panTo(ll);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  // AI 추천 코스: 점선 폴리라인 + 순서 배지 + 구간 이동 시간
  useEffect(() => {
    const map = mapRef.current;
    const layer = courseLayer.current;
    if (!map) return;
    layer.clearLayers();
    if (!course || !data) return;
    const byId = new Map(data.t2.map((s) => [s.id, s]));
    const stops = [...course.stops].sort((a, b) => a.order - b.order);
    const pts: L.LatLngTuple[] = [];

    stops.forEach((stop, idx) => {
      const spot = byId.get(stop.spot_id);
      if (!spot) return;
      const ll: L.LatLngTuple = [spot.location.lat, spot.location.lng];
      pts.push(ll);
      L.marker(ll, {
        icon: L.divIcon({
          className: "pp-icon",
          html: `<div class="pp-order">${idx + 1}</div>`,
          iconSize: [28, 28],
          iconAnchor: [40, 52], // 핀 머리의 왼쪽 위 (이모지·뱃지를 가리지 않게)
        }),
        interactive: false,
        zIndexOffset: 2000,
      }).addTo(layer);
      const prev = pts[pts.length - 2];
      if (prev && stop.distance_from_prev_km != null) {
        L.marker([(prev[0] + ll[0]) / 2, (prev[1] + ll[1]) / 2], {
          icon: L.divIcon({
            className: "pp-icon",
            html: `<div class="pp-leg">${escapeHtml(travelLabel(stop.distance_from_prev_km, transport))}</div>`,
            iconSize: [90, 22],
            iconAnchor: [45, 11],
          }),
          interactive: false,
        }).addTo(layer);
      }
    });
    if (pts.length > 1) {
      L.polyline(pts, { color: "#111827", weight: 4, dashArray: "2 10", lineCap: "round" }).addTo(layer);
      map.fitBounds(L.latLngBounds(pts), {
        paddingTopLeft: [60, 60], paddingBottomRight: [60, 60 + padBottom], maxZoom: 16,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [course, data, transport]);

  return <div ref={elRef} className="map" role="application" aria-label="대한민국 지도" />;
}
