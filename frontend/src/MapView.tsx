import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "maplibre-gl/dist/maplibre-gl.css";
import { loadBasemap } from "./basemap";
import { pickTileStyle } from "./mapStyle";
import type { MapProps } from "./mapTypes";
import {
  LEG_SIZE, ORDER_ANCHOR, ORDER_SIZE, PIN_ANCHOR, PIN_SIZE, legHtml, orderHtml, pinHtml, regionHtml, regionSize,
} from "./markerHtml";
import { CITY_VIEW_MAX_ZOOM, PROVINCE_VIEW_MAX_ZOOM, escapeHtml, groupSpots, travelLabel } from "./geo";

const KOREA_CENTER: L.LatLngTuple = [36.4, 127.9];

/** Leaflet 지도(OpenFreeMap 벡터 / 대체 OSM 타일). 카카오맵 키가 없거나 실패했을 때 쓰인다. */
export default function MapView({
  data, items, course, transport, focusId, selectedId, onSelect, padBottom = 0, compact = false,
}: MapProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerLayer = useRef(L.layerGroup());
  const courseLayer = useRef(L.layerGroup());
  const [zoom, setZoom] = useState(7);
  // 줌 단계: 시·도 배지 → 시·군 배지 → 개별 핀
  const level = zoom <= PROVINCE_VIEW_MAX_ZOOM ? "province" : zoom <= CITY_VIEW_MAX_ZOOM ? "city" : "pin";

  // 지도 초기화
  useEffect(() => {
    const map = L.map(elRef.current!, { center: KOREA_CENTER, zoom: 7, zoomControl: false, maxZoom: 18 });
    L.control.zoom({ position: "bottomright" }).addTo(map);
    markerLayer.current.addTo(map);
    courseLayer.current.addTo(map);
    map.on("zoomend", () => setZoom(map.getZoom()));
    mapRef.current = map;
    void loadBasemap(map, pickTileStyle(window.location.search), () => mapRef.current === map);
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
        const size = regionSize(compact);
        L.marker([g.lat, g.lng], {
          icon: L.divIcon({
            className: "pp-icon", html: regionHtml(g, compact), iconSize: size, iconAnchor: [size[0] / 2, size[1] / 2],
          }),
          title: `${g.label} ${g.count}곳`,
          zIndexOffset: g.count, // 개수가 많은 배지를 위로 (가까운 배지가 덮어도 큰 쪽이 눌린다)
        })
          // 시·도 배지는 시·군 단계로, 시·군 배지는 개별 핀 단계로 확대
          .on("click", () => map.setView([g.lat, g.lng], level === "province" ? PROVINCE_VIEW_MAX_ZOOM + 2 : CITY_VIEW_MAX_ZOOM + 2))
          .addTo(layer);
      }
      return;
    }

    for (const spot of spots) {
      const focused = spot.id === focusId || spot.id === selectedId;
      L.marker([spot.location.lat, spot.location.lng], {
        icon: L.divIcon({ className: "pp-icon", html: pinHtml(spot, focused), iconSize: PIN_SIZE, iconAnchor: PIN_ANCHOR }),
        title: spot.title,
        zIndexOffset: focused ? 1000 : 0,
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
        icon: L.divIcon({ className: "pp-icon", html: orderHtml(idx + 1), iconSize: ORDER_SIZE, iconAnchor: ORDER_ANCHOR }),
        interactive: false,
        zIndexOffset: 2000,
      }).addTo(layer);
      const prev = pts[pts.length - 2];
      if (prev && stop.distance_from_prev_km != null) {
        L.marker([(prev[0] + ll[0]) / 2, (prev[1] + ll[1]) / 2], {
          icon: L.divIcon({
            className: "pp-icon", html: legHtml(travelLabel(stop.distance_from_prev_km, transport)),
            iconSize: LEG_SIZE, iconAnchor: [LEG_SIZE[0] / 2, LEG_SIZE[1] / 2],
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
