// 좋아요·댓글·로그인 API 클라이언트. 로그인 상태는 HttpOnly 쿠키라 자바스크립트가 토큰을 다루지 않는다.
export interface SocialUser {
  id: number;
  nickname: string;
}
export interface Summary {
  likes: number;
  comments: number;
  liked: boolean;
}
export interface CommentView {
  id: string;
  body: string;
  created_at: string;
  nickname: string;
  mine: boolean;
}

export const MAX_COMMENT = 300; // 서버(app/social.py)와 같은 한도
export const SUMMARY_CHUNK = 60; // 한 번에 요청할 수 있는 장소 수 (서버 한도와 같다)

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    // 상태를 바꾸는 요청에는 커스텀 헤더를 붙인다 → 다른 사이트가 우리 쿠키로 요청을 위조(CSRF)할 수 없다
    headers: method === "GET" ? undefined : { "Content-Type": "application/json", "X-PinPlay": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    const detail = typeof data?.detail === "string" ? data.detail : `요청에 실패했어요 (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const fetchMe = () => call<{ social: boolean; user: SocialUser | null }>("GET", "/api/auth/me");
export const logout = () => call<{ ok: boolean }>("POST", "/api/auth/logout");

export const loginUrl = (returnTo: string) => `/api/auth/kakao/login?return=${encodeURIComponent(returnTo)}`;

export async function fetchSummaries(placeIds: string[]): Promise<Record<string, Summary>> {
  const out: Record<string, Summary> = {};
  for (let i = 0; i < placeIds.length; i += SUMMARY_CHUNK) {
    const ids = placeIds.slice(i, i + SUMMARY_CHUNK).join(",");
    Object.assign(out, await call<Record<string, Summary>>("GET", `/api/social/summary?ids=${encodeURIComponent(ids)}`));
  }
  return out;
}

export const toggleLike = (placeId: string) =>
  call<{ liked: boolean; likes: number }>("POST", `/api/social/likes/${placeId}`);

export const fetchComments = (placeId: string, before?: string | null) =>
  call<{ comments: CommentView[]; next_before: string | null }>(
    "GET", `/api/social/comments/${placeId}?limit=20${before ? `&before=${encodeURIComponent(before)}` : ""}`,
  );
export const postComment = (placeId: string, body: string) =>
  call<CommentView>("POST", `/api/social/comments/${placeId}`, { body });
export const deleteComment = (id: string) => call<{ deleted: boolean }>("DELETE", `/api/social/comments/${id}`);
export const reportComment = (id: string) =>
  call<{ reported: boolean; hidden: boolean }>("POST", `/api/social/comments/${id}/report`);

/** "방금 전 / 5분 전 / 3시간 전 / 2일 전 / 2026.10.01" */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const sec = Math.max(0, Math.floor((now.getTime() - t) / 1000));
  if (sec < 60) return "방금 전";
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`;
  if (sec < 7 * 86400) return `${Math.floor(sec / 86400)}일 전`;
  const d = new Date(t);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

/** 큰 수는 줄여서 보여 준다 (1200 → 1.2천) */
export function compactCount(n: number): string {
  return n >= 1000 ? `${(Math.floor(n / 100) / 10).toString().replace(/\.0$/, "")}천` : String(n);
}
