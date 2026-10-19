import type { CardItem, Course, PipelineResponse, Transport } from "./types";

/** Leaflet(OpenFreeMap)과 카카오맵 두 지도 화면이 공통으로 받는 props */
export interface MapProps {
  data: PipelineResponse | null;
  items: CardItem[]; // 카테고리·시기 필터가 적용된 스팟
  course: Course | null; // 표시할 코스(토글 on일 때만 전달)
  transport: Transport;
  focusId: string | null; // 호버/선택된 스팟
  selectedId: string | null;
  onSelect: (id: string) => void;
  padBottom?: number; // 모바일 바텀시트에 가려지는 높이(px). 지도 맞춤 시 여백으로 쓴다
  compact?: boolean; // 좁은 화면: 배지를 작게(개수+지역명만)
  fitKey?: string; // "키워드|시·군". 필터가 걸려 있으면 지도를 결과(핀들)에 맞추고, "|"이면 원래 탐색 반경에 맞춘다
}
