// 지도 엔진과 무관한 기하 계산. 카카오맵의 '레벨'(1~14, 작을수록 확대)을 Leaflet식 웹 메르카토르 줌으로 환산해
// 줌 단계(시·도 → 시·군 → 핀) 기준을 두 지도에서 똑같이 쓰도록 한다.
export interface Box {
  south: number;
  north: number;
  west: number;
  east: number;
}

/** 화면 너비(px)가 경도 west~east를 보여 줄 때의 웹 메르카토르 줌. 256px가 360°면 0, 한 단계 확대마다 +1 */
export function equivalentZoom(widthPx: number, west: number, east: number): number {
  return Math.log2(360 / (256 * ((east - west) / widthPx)));
}

/** (lat, lng)를 가운데로 두고 z줌에서 widthPx × heightPx 화면이 보여 주는 영역 */
export function boxForZoom(lat: number, lng: number, z: number, widthPx: number, heightPx: number): Box {
  const degLng = 360 / (256 * 2 ** z); // 1px당 경도
  const degLat = degLng * Math.cos((lat * Math.PI) / 180); // 메르카토르에서 1px당 위도
  return {
    south: lat - (degLat * heightPx) / 2,
    north: lat + (degLat * heightPx) / 2,
    west: lng - (degLng * widthPx) / 2,
    east: lng + (degLng * widthPx) / 2,
  };
}

/** 중심에서 반경 radiusKm를 포함하는 사각형 */
export function boxForRadius(lat: number, lng: number, radiusKm: number): Box {
  const dLat = radiusKm / 111.32;
  const dLng = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180));
  return { south: lat - dLat, north: lat + dLat, west: lng - dLng, east: lng + dLng };
}
