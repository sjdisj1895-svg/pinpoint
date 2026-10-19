import type { Category, LiveStatus, PipelineResponse, Spot } from "./types";

// 데이터 소스 연동 전 UI 확인용 샘플 (실제 행사가 아님)
function s(
  id: string, category: Category, title: string, subtitle: string, tag: string, lat: number, lng: number,
  status: LiveStatus, extra: Partial<Spot["schedule"]> = {}, io = "OUTDOOR",
): Spot {
  return {
    id, category, title: `(샘플) ${title}`, subtitle,
    location: { address: `${tag} 샘플로 1`, lat, lng, region_tag: tag },
    schedule: { period: "2026-10-18 ~ 2026-10-26", operating_hours: "11:00 ~ 19:00", live_status: status, ...extra },
    attributes: { vibe_tags: ["#샘플", "#로컬"], admission_fee: "무료", parking_available: true, indoor_outdoor: io },
    source_url: "https://example.com", confidence_score: 0.8, verification_note: "샘플 데이터",
  };
}

const spots: Spot[] = [
  s("spot_001", "FESTIVAL", "소양강 야시장 축제", "강변에서 열리는 가을 야시장", "강원 춘천", 37.8935, 127.7195, "OPEN_NOW"),
  s("spot_002", "FLEA_MARKET", "브라운5번가 플리마켓", "수공예 로컬 마켓", "강원 춘천", 37.878, 127.728, "OPEN_NOW"),
  s("spot_003", "MOVIE", "춘천 독립영화관", "독립영화 상영", "강원 춘천", 37.88, 127.725, "OPEN_NOW",
    { movie_showtimes: ["16:50", "14:20"] }, "INDOOR"),
  s("spot_004", "TRAVEL_SPOT", "소양강 스카이워크", "강 위를 걷는 전망 명소", "강원 춘천", 37.8946, 127.7216, "OPEN_NOW"),
  s("spot_005", "NEW_OPEN", "신상 로스터리 카페", "갓 오픈한 스페셜티 카페", "강원 춘천", 37.8815, 127.7305, "OPEN_NOW", {}, "INDOOR"),
  s("spot_006", "FESTIVAL", "부산 가을 불꽃 축제", "해안 불꽃 행사", "부산 광안리", 35.1532, 129.1186, "OPEN_NOW"),
  s("spot_007", "FLEA_MARKET", "부산 항구 플리마켓", "항구 빈티지 마켓", "부산 영도", 35.0911, 129.0689, "OPEN_NOW"),
  s("spot_008", "FESTIVAL", "전주 한옥 야행", "한옥마을 야간 개장", "전북 전주", 35.8151, 127.153, "OPEN_NOW"),
  s("spot_009", "FESTIVAL", "제주 억새 축제", "오름 억새 행사", "제주 제주시", 33.4996, 126.5312, "OPEN_SOON"),
];

export const MOCK: PipelineResponse = {
  t1: {
    target_region: { province: "강원특별자치도", city_district: "춘천시", center_coords: { lat: 37.8813, lng: 127.7298 }, radius_km: 10 },
    time_context: { target_date: "2026-10-24", time_window: "AFTERNOON", require_open_now: false },
    user_persona: { companion: "연인", transport: "WALK", vibe_keywords: ["로맨틱", "로컬"], activity_level: 3, budget_tier: "MID" },
    requested_categories: ["FESTIVAL", "FLEA_MARKET", "MOVIE", "TRAVEL_SPOT", "NEW_OPEN"],
    search_queries: [],
  },
  t2: spots,
  t3: {
    pin_list: [
      { spot_id: "spot_002", category: "FLEA_MARKET", score: 92, why_for_you: "연인과 로컬 감성을 즐기기 좋은 수공예 마켓이에요.", tips: ["주차: 이용 가능", "운영: 11:00 ~ 19:00"] },
      { spot_id: "spot_001", category: "FESTIVAL", score: 88, why_for_you: "로맨틱한 강변 야경을 함께 걷기 좋아요.", tips: ["입장료: 무료"] },
      { spot_id: "spot_003", category: "MOVIE", score: 80, why_for_you: "걷다 쉬어 가며 볼 독립영화로 데이트 코스에 어울려요.", tips: [] },
    ],
    courses: [
      {
        course_id: "course_001", title: "구도심 감성 반나절", duration_type: "HALF_DAY", score: 90,
        why_for_you: "연인과 도보로 이어지는 로컬 감성 코스예요.",
        stops: [
          { order: 1, spot_id: "spot_003", suggested_time: "14:20 ~ 16:00", why_for_you: "영화로 시작", tips: [] },
          { order: 2, spot_id: "spot_002", suggested_time: "16:10 ~ 17:30", why_for_you: "마켓 구경", tips: [], distance_from_prev_km: 0.35 },
          { order: 3, spot_id: "spot_005", suggested_time: "17:40 ~ 19:00", why_for_you: "신상 카페 마무리", tips: [], distance_from_prev_km: 0.45 },
        ],
      },
      {
        course_id: "course_002", title: "소양강 야경 코스", duration_type: "HALF_DAY", score: 84,
        why_for_you: "강변 야시장과 스카이워크를 잇는 짧은 산책 코스예요.",
        stops: [
          { order: 1, spot_id: "spot_001", suggested_time: "17:00 ~ 18:30", why_for_you: "야시장", tips: [] },
          { order: 2, spot_id: "spot_004", suggested_time: "18:40 ~ 19:30", why_for_you: "스카이워크", tips: [], distance_from_prev_km: 0.22 },
        ],
      },
    ],
  },
};
