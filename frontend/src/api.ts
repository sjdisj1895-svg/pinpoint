import { ALL_CATEGORIES } from "./geo";
import type { PipelineResponse, RegionFacet, RerouteRequest, RerouteResponse, Spot } from "./types";

export async function fetchPipeline(text: string): Promise<PipelineResponse> {
  return post("/api/pipeline", { text });
}

export async function fetchReroute(req: RerouteRequest): Promise<RerouteResponse> {
  return post("/api/reroute", req);
}

export interface ExploreResult {
  data: PipelineResponse; // 화면이 쓰는 형태로 맞춘 결과
  regions: RegionFacet[]; // 시·군별 개수 (키워드 기준, 지역 필터 적용 전)
  total: number; // 한도로 자르기 전 일치 개수
}

/** 권역 둘러보기 + 내부 검색(AI 없이 DB). q: 키워드, region: 시·군 필터 */
export async function fetchExplore(
  province: string, label: string, opts: { q?: string; region?: string; radiusKm?: number } = {},
): Promise<ExploreResult> {
  const params = new URLSearchParams({ province });
  if (opts.q?.trim()) params.set("q", opts.q.trim());
  if (opts.region) params.set("region", opts.region);
  const res = await fetch(`/api/explore?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => null); // 서버가 원인을 알려 주면 그대로 보여 준다
    throw new Error(body?.detail ?? `불러오지 못했어요 (${res.status})`);
  }
  const body: { center: { lat: number; lng: number }; spots: Spot[]; regions: RegionFacet[]; total: number } = await res.json();
  return {
    regions: body.regions ?? [],
    total: body.total ?? body.spots.length,
    data: {
      t1: {
        target_region: { province: label, city_district: `${province} 전체`, center_coords: body.center, radius_km: opts.radiusKm ?? 80 },
        time_context: { target_date: new Date().toISOString().slice(0, 10), time_window: "ALL_DAY", require_open_now: false },
        user_persona: { companion: "", transport: "CAR", vibe_keywords: [], activity_level: 3, budget_tier: "MID" },
        requested_categories: ALL_CATEGORIES,
        search_queries: [],
      },
      t2: body.spots,
      t3: { pin_list: [], courses: [] },
    },
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
