import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError, SUMMARY_CHUNK, compactCount, deleteComment, fetchComments, fetchSummaries, loginUrl, postComment, timeAgo,
  toggleLike,
} from "./social";

afterEach(() => vi.unstubAllGlobals());

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

describe("timeAgo", () => {
  const now = new Date("2026-10-20T12:00:00Z");
  const ago = (s: number) => new Date(now.getTime() - s * 1000).toISOString();
  it("formats relative times", () => {
    expect(timeAgo(ago(10), now)).toBe("방금 전");
    expect(timeAgo(ago(5 * 60), now)).toBe("5분 전");
    expect(timeAgo(ago(3 * 3600), now)).toBe("3시간 전");
    expect(timeAgo(ago(2 * 86400), now)).toBe("2일 전");
  });
  it("falls back to a date after a week and tolerates future/invalid input", () => {
    expect(timeAgo("2026-10-01T00:00:00Z", now)).toMatch(/^2026\.10\.0[01]$/);
    expect(timeAgo(ago(-60), now)).toBe("방금 전"); // 서버·브라우저 시계가 조금 어긋나도 음수로 보이지 않는다
    expect(timeAgo("not-a-date", now)).toBe("");
  });
});

describe("compactCount", () => {
  it("shortens big numbers", () => {
    expect(compactCount(0)).toBe("0");
    expect(compactCount(999)).toBe("999");
    expect(compactCount(1000)).toBe("1천");
    expect(compactCount(1250)).toBe("1.2천");
  });
});

describe("loginUrl", () => {
  it("encodes the return path", () => {
    expect(loginUrl("/?tiles=a&b=1")).toBe("/api/auth/kakao/login?return=%2F%3Ftiles%3Da%26b%3D1");
  });
});

describe("api calls", () => {
  it("sends the anti-CSRF header and same-origin cookies on writes, but not on reads", async () => {
    const f = vi.fn().mockResolvedValue(json({ liked: true, likes: 1 }));
    vi.stubGlobal("fetch", f);
    await toggleLike("p1");
    const [, init] = f.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers["X-PinPlay"]).toBe("1");

    f.mockResolvedValue(json({ comments: [], next_before: null }));
    await fetchComments("p1");
    expect(f.mock.calls[1][1].headers).toBeUndefined();
    expect(f.mock.calls[1][1].method).toBe("GET");
  });

  it("posts the comment body as JSON and deletes by id", async () => {
    const f = vi.fn().mockResolvedValue(json({ id: "c1", body: "hi", created_at: "x", nickname: "n", mine: true }, 201));
    vi.stubGlobal("fetch", f);
    await postComment("p1", "hi");
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ body: "hi" });
    f.mockResolvedValue(json({ deleted: true }));
    await deleteComment("c1");
    expect(f.mock.calls[1][0]).toBe("/api/social/comments/c1");
    expect(f.mock.calls[1][1].method).toBe("DELETE");
  });

  it("turns server errors into ApiError with the server's message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "로그인이 필요합니다." }, 401)));
    await expect(toggleLike("p1")).rejects.toMatchObject({ status: 401, message: "로그인이 필요합니다." });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 500 })));
    const err = await toggleLike("p1").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
  });

  it("splits summary requests into chunks the server accepts and merges the answers", async () => {
    const f = vi.fn().mockImplementation(async (url: string) => {
      const ids = decodeURIComponent(url.split("ids=")[1]).split(",");
      return json(Object.fromEntries(ids.map((i) => [i, { likes: 1, comments: 0, liked: false }])));
    });
    vi.stubGlobal("fetch", f);
    const ids = Array.from({ length: SUMMARY_CHUNK * 2 + 10 }, (_, i) => `id${i}`);
    const out = await fetchSummaries(ids);
    expect(f).toHaveBeenCalledTimes(3);
    expect(Object.keys(out)).toHaveLength(ids.length);
    for (const [url] of f.mock.calls) expect(decodeURIComponent(url.split("ids=")[1]).split(",").length).toBeLessThanOrEqual(SUMMARY_CHUNK);
    f.mockClear();
    expect(await fetchSummaries([])).toEqual({});
    expect(f).not.toHaveBeenCalled();
  });
});
