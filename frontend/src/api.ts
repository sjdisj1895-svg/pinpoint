import { ALL_CATEGORIES } from "./geo";
import type { PipelineResponse, RerouteRequest, RerouteResponse, Spot } from "./types";

export async function fetchPipeline(text: string): Promise<PipelineResponse> {
  return post("/api/pipeline", { text });
}

export async function fetchReroute(req: RerouteRequest): Promise<RerouteResponse> {
  return post("/api/reroute", req);
}

/** 권역 둘러보기(AI 없이 DB의 진행 중 스팟). 화면이 쓰는 PipelineResponse 형태로 맞춰 반환한다. */
export async function fetchExplore(province: string, label: string, radiusKm = 80): Promise<PipelineResponse> {
  const res = await fetch(`/api/explore?province=${encodeURIComponent(province)}`);
  if (!res.ok) {
    const body = await res.json().catch(() => null); // 서버가 원인을 알려 주면 그대로 보여 준다
    throw new Error(body?.detail ?? `둘러보기를 불러오지 못했어요 (${res.status})`);
  }
  const body: { center: { lat: number; lng: number }; spots: Spot[] } = await res.json();
  return {
    t1: {
      target_region: { province: label, city_district: `${province} 전체`, center_coords: body.center, radius_km: radiusKm },
      time_context: { target_date: new Date().toISOString().slice(0, 10), time_window: "ALL_DAY", require_open_now: false },
      user_persona: { companion: "", transport: "CAR", vibe_keywords: [], activity_level: 3, budget_tier: "MID" },
      requested_categories: ALL_CATEGORIES,
      search_queries: [],
    },
    t2: body.spots,
    t3: { pin_list: [], courses: [] },
  };
}

async function post<T>(url: string, payload: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `요청 실패 (${res.status})`);
  }
  return res.json();
}
