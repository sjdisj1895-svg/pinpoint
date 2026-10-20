// 백엔드 app/schemas.py 와 대응

export type Category = "FESTIVAL" | "FLEA_MARKET" | "MOVIE" | "TRAVEL_SPOT" | "NEW_OPEN";
export type Transport = "PUBLIC" | "CAR" | "WALK";
export type LiveStatus = "OPEN_NOW" | "OPEN_SOON" | "CLOSED";

export interface T1Result {
  target_region: {
    province: string;
    city_district: string;
    center_coords: { lat: number; lng: number };
    radius_km: number;
  };
  time_context: { target_date: string; time_window: string; require_open_now: boolean };
  user_persona: { companion: string; transport: Transport; vibe_keywords: string[]; activity_level: number; budget_tier: string };
  requested_categories: Category[];
  search_queries: string[];
}

export interface Spot {
  id: string;
  category: Category;
  title: string;
  subtitle: string;
  location: { address: string; lat: number; lng: number; region_tag: string };
  schedule: { period: string; operating_hours: string; live_status: LiveStatus; movie_showtimes?: string[] };
  attributes: { vibe_tags: string[]; admission_fee: string; parking_available: boolean | null; indoor_outdoor: string };
  source_url: string;
  image_url?: string;
  place_id?: string; // DB 고유 ID. 좋아요·댓글이 붙는 키 (없으면 소셜 기능 비활성)
  confidence_score: number;
  verification_note: string;
}

export interface PinItem {
  spot_id: string;
  category: Category;
  score: number;
  why_for_you: string;
  tips: string[];
}

export interface CourseStop {
  order: number;
  spot_id: string;
  suggested_time: string;
  why_for_you: string;
  tips: string[];
  distance_from_prev_km?: number;
}

export interface Course {
  course_id: string;
  title: string;
  duration_type: "HALF_DAY" | "FULL_DAY";
  score: number;
  why_for_you: string;
  stops: CourseStop[];
}

export interface PipelineResponse {
  t1: T1Result;
  t2: Spot[];
  t3: { pin_list: PinItem[]; courses: Course[] };
}

export type Weather = "CLEAR" | "RAIN" | "HEAT";

export interface RerouteRequest {
  feedback: string;
  location: { lat: number; lng: number };
  weather?: Weather;
  t1: T1Result;
  spots: Spot[];
  course: Course | null;
}

export interface RerouteResponse {
  trigger: "WEATHER" | "DELAY" | "FEEDBACK" | "CROWD" | "EVENT_END";
  summary: string;
  persona: T1Result["user_persona"];
  preference_notes: string[];
  replacements: { removed_spot_id: string | null; added_spot_id: string | null; reason: string }[];
  course: Course | null;
  pin_list: PinItem[];
  markers: GeoJSON.FeatureCollection;
  route: GeoJSON.Feature | null;
}

/** 시·군 필터 칩: 이름과 (현재 검색어 기준) 개수 */
export interface RegionFacet {
  name: string;
  count: number;
}

/** 카드 리스트용: 스팟 + T3 추천 정보 */
export interface CardItem {
  spot: Spot;
  score: number | null;
  why: string | null;
  tips: string[];
}
