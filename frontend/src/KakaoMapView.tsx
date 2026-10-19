/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, useState } from "react";
import { loadKakaoSdk } from "./kakaoSdk";
import type { MapProps } from "./mapTypes";
import {
  LEG_SIZE, ORDER_ANCHOR, PIN_ANCHOR, legHtml, orderHtml, pinHtml, regionHtml, regionSize,
} from "./markerHtml";
import { CITY_VIEW_MAX_ZOOM, PROVINCE_VIEW_MAX_ZOOM, groupSpots, travelLabel } from "./geo";
import { boxForRadius, boxForZoom, equivalentZoom } from "./zoomEquiv";
import type { Box } from "./zoomEquiv";

interface Props extends MapProps {
  appKey: string;
  onUnavailable: () => void; // SDK 로드 실패, 도메인 미등록 등 지도가 뜨지 않을 때 (호출한 쪽이 다른 지도로 대체)
}

const KOREA_CENTER: [number, number] = [36.4, 127.9];
const TILES_TIMEOUT_MS = 8000;

/** 카카오맵 화면. Leaflet 화면(MapView)과 같은 props·같은 핀 모양·같은 줌 단계 기준을 쓴다. */
export default function KakaoMapView({
  data, items, course, transport, focusId, selectedId, onSelect, padBottom = 0, compact = false, appKey, onUnavailable,
}: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const kakaoRef = useRef<any>(null);
  const mapRef = useRef<any>(null);
  const markerOverlays = useRef<any[]>([]);
  const courseOverlays = useRef<any[]>([]);
  const [ready, setReady] = useState(false);
  const [zoom, setZoom] = useState(7);
  const level = zoom <= PROVINCE_VIEW_MAX_ZOOM ? "province" : zoom <= CITY_VIEW_MAX_ZOOM ? "city" : "pin";
  const unavailableRef = useRef(onUnavailable);
  unavailableRef.current = onUnavailable;

  const toBounds = (box: Box) => {
    const k = kakaoRef.current;
    return new k.maps.LatLngBounds(new k.maps.LatLng(box.south, box.west), new k.maps.LatLng(box.north, box.east));
  };
  /** 지금 보이는 영역을 웹 메르카토르 줌으로 환산 */
  const currentZoom = (): number => {
    const b = mapRef.current.getBounds();
    return equivalentZoom(elRef.current!.clientWidth, b.getSouthWest().getLng(), b.getNorthEast().getLng());
  };
  /** (lat,lng)를 가운데로 z줌 정도로 확대/이동 (카카오는 정수 레벨이라 가장 가까운 레벨로 맞춰진다) */
  const goToZoom = (lat: number, lng: number, z: number) => {
    const el = elRef.current!;
    mapRef.current.setBounds(toBounds(boxForZoom(lat, lng, z, el.clientWidth, el.clientHeight)));
  };
  /** 좌표를 기준점이 (anchorX, anchorY)인 HTML 요소로 올린다 — Leaflet divIcon의 iconAnchor와 같은 의미 */
  const addOverlay = (
    lat: number, lng: number, html: string, [ax, ay]: [number, number], zIndex: number, opts?: { onClick?: () => void; title?: string },
  ) => {
    const k = kakaoRef.current;
    const root = document.createElement("div");
    root.className = "k-anchor";
    const box = document.createElement("div");
    box.className = "k-box";
    box.style.left = `${-ax}px`;
    box.style.top = `${-ay}px`;
    box.innerHTML = html; // markerHtml의 모든 외부 문자열은 escapeHtml을 거친다
    if (opts?.title) box.title = opts.title;
    if (opts?.onClick) {
      box.style.cursor = "pointer";
      box.addEventListener("click", (e) => {
        e.stopPropagation();
        opts.onClick!();
      });
    }
    root.appendChild(box);
    const overlay = new k.maps.CustomOverlay({
      position: new k.maps.LatLng(lat, lng), content: root, xAnchor: 0, yAnchor: 0, zIndex, clickable: !!opts?.onClick,
    });
    overlay.setMap(mapRef.current);
    return overlay;
  };
  const clear = (list: React.MutableRefObject<any[]>) => {
    list.current.forEach((o) => o.setMap(null));
    list.current = [];
  };

  // 지도 초기화
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    loadKakaoSdk(appKey)
      .then((kakao) => {
        if (disposed || !elRef.current) return;
        kakaoRef.current = kakao;
        const map = new kakao.maps.Map(elRef.current, {
          center: new kakao.maps.LatLng(KOREA_CENTER[0], KOREA_CENTER[1]),
          level: 12,
        });
        mapRef.current = map;
        if (!compact) map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
        // 키·도메인 설정이 틀리면 SDK는 불러와져도 타일이 뜨지 않는다 → 일정 시간 안에 타일이 안 뜨면 다른 지도로 대체
        timer = setTimeout(() => !disposed && unavailableRef.current(), TILES_TIMEOUT_MS);
        kakao.maps.event.addListener(map, "tilesloaded", () => clearTimeout(timer));
        const syncZoom = () => setZoom(Math.round(currentZoom()));
        kakao.maps.event.addListener(map, "idle", syncZoom);
        setReady(true);
      })
      .catch(() => !disposed && unavailableRef.current());
    const onResize = () => mapRef.current?.relayout();
    window.addEventListener("resize", onResize);
    return () => {
      disposed = true;
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
      clear(markerOverlays);
      clear(courseOverlays);
      mapRef.current = null;
      if (elRef.current) elRef.current.innerHTML = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appKey]);

  // 새 결과 도착 시 T1 탐색 반경에 맞춰 이동
  useEffect(() => {
    if (!ready || !data) return;
    const { center_coords: c, radius_km } = data.t1.target_region;
    mapRef.current.setBounds(toBounds(boxForRadius(c.lat, c.lng, radius_km)), 0, 0, padBottom, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, data]);

  // 마커 렌더링 (줌 단계 적응)
  useEffect(() => {
    if (!ready) return;
    clear(markerOverlays);
    const spots = items.map((i) => i.spot);

    if (level !== "pin") {
      for (const g of groupSpots(spots, level)) {
        const size = regionSize(compact);
        markerOverlays.current.push(
          // 개수가 많은 배지를 위로 올려, 가까운 시·군 배지가 서로 덮어도 큰 쪽이 눌리게 한다
          addOverlay(g.lat, g.lng, regionHtml(g, compact), [size[0] / 2, size[1] / 2], g.count, {
            title: `${g.label} ${g.count}곳`,
            // 시·도 배지는 시·군 단계로, 시·군 배지는 개별 핀 단계로 확대
            onClick: () => goToZoom(g.lat, g.lng, level === "province" ? PROVINCE_VIEW_MAX_ZOOM + 2 : CITY_VIEW_MAX_ZOOM + 2),
          }),
        );
      }
      return;
    }
    for (const spot of spots) {
      const focused = spot.id === focusId || spot.id === selectedId;
      markerOverlays.current.push(
        addOverlay(spot.location.lat, spot.location.lng, pinHtml(spot, focused), PIN_ANCHOR, focused ? 1000 : 0, {
          title: spot.title, onClick: () => onSelect(spot.id),
        }),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, items, level, focusId, selectedId, onSelect, compact]);

  // 카드 호버/클릭 → 이동
  useEffect(() => {
    if (!ready) return;
    const spot = items.find((i) => i.spot.id === focusId)?.spot ?? data?.t2.find((s) => s.id === focusId);
    if (!spot) return;
    const { lat, lng } = spot.location;
    if (currentZoom() <= CITY_VIEW_MAX_ZOOM) {
      // 배지 단계에서는 카드를 클릭했을 때만 확대한다. 호버만으로 지도가 튀지 않게 한다.
      if (focusId === selectedId) goToZoom(lat, lng, 13);
    } else {
      mapRef.current.panTo(new kakaoRef.current.maps.LatLng(lat, lng));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  // AI 추천 코스: 점선 폴리라인 + 순서 배지 + 구간 이동 시간
  useEffect(() => {
    if (!ready) return;
    clear(courseOverlays);
    if (!course || !data) return;
    const k = kakaoRef.current;
    const byId = new Map(data.t2.map((s) => [s.id, s]));
    const stops = [...course.stops].sort((a, b) => a.order - b.order);
    const pts: { lat: number; lng: number }[] = [];

    stops.forEach((stop, idx) => {
      const spot = byId.get(stop.spot_id);
      if (!spot) return;
      const p = { lat: spot.location.lat, lng: spot.location.lng };
      pts.push(p);
      courseOverlays.current.push(addOverlay(p.lat, p.lng, orderHtml(idx + 1), ORDER_ANCHOR, 2000));
      const prev = pts[pts.length - 2];
      if (prev && stop.distance_from_prev_km != null) {
        courseOverlays.current.push(
          addOverlay((prev.lat + p.lat) / 2, (prev.lng + p.lng) / 2, legHtml(travelLabel(stop.distance_from_prev_km, transport)),
            [LEG_SIZE[0] / 2, LEG_SIZE[1] / 2], 1500),
        );
      }
    });
    if (pts.length > 1) {
      const line = new k.maps.Polyline({
        path: pts.map((p) => new k.maps.LatLng(p.lat, p.lng)),
        strokeWeight: 4, strokeColor: "#111827", strokeOpacity: 1, strokeStyle: "shortdot",
      });
      line.setMap(mapRef.current);
      courseOverlays.current.push(line);
      const box = pts.reduce<Box>(
        (b, p) => ({ south: Math.min(b.south, p.lat), north: Math.max(b.north, p.lat), west: Math.min(b.west, p.lng), east: Math.max(b.east, p.lng) }),
        { south: 90, north: -90, west: 180, east: -180 },
      );
      mapRef.current.setBounds(toBounds(box), 60, 60, 60 + padBottom, 60);
      if (currentZoom() > 16) goToZoom((box.south + box.north) / 2, (box.west + box.east) / 2, 16); // 너무 확대되지 않게
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, course, data, transport]);

  return <div ref={elRef} className="map" role="application" aria-label="대한민국 지도(카카오맵)" />;
}
