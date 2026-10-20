import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import * as api from "./social";
import type { SocialUser, Summary } from "./social";

interface SocialValue {
  enabled: boolean; // 서버에 좋아요·댓글 설정이 갖춰졌는가 (false면 관련 화면을 숨긴다)
  loaded: boolean;
  user: SocialUser | null;
  summaries: Record<string, Summary>;
  notice: string | null; // 사용자에게 알릴 짧은 안내/오류
  login: () => void;
  logout: () => Promise<void>;
  load: (placeIds: string[]) => void; // 카드 목록에 보일 장소들의 좋아요·댓글 수를 불러온다
  toggleLike: (placeId: string) => Promise<void>;
  bumpComments: (placeId: string, delta: number) => void;
  dismissNotice: () => void;
}

const Ctx = createContext<SocialValue | null>(null);

export function useSocial(): SocialValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("SocialProvider 안에서만 쓸 수 있어요");
  return v;
}

const EMPTY: Summary = { likes: 0, comments: 0, liked: false };

export function SocialProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [user, setUser] = useState<SocialUser | null>(null);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const requested = useRef(new Set<string>()); // 이미 요청한 장소 (같은 요청을 반복하지 않는다)

  useEffect(() => {
    let alive = true;
    api.fetchMe()
      .then((me) => alive && (setEnabled(me.social), setUser(me.user)))
      .catch(() => undefined) // 실패하면 소셜은 꺼진 채로 둔다 (나머지 기능에는 영향 없음)
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 6000); // 안내는 잠시 뒤 저절로 사라진다
    return () => clearTimeout(t);
  }, [notice]);

  const load = useCallback(
    (placeIds: string[]) => {
      if (!enabled) return;
      const todo = placeIds.filter((id) => id && !requested.current.has(id));
      if (!todo.length) return;
      todo.forEach((id) => requested.current.add(id));
      api.fetchSummaries(todo)
        .then((got) => setSummaries((prev) => ({ ...prev, ...got })))
        .catch(() => todo.forEach((id) => requested.current.delete(id))); // 실패하면 다음에 다시 시도
    },
    [enabled],
  );

  const login = useCallback(() => {
    window.location.assign(api.loginUrl(window.location.pathname + window.location.search));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      // 내가 눌렀는지(liked)는 로그인한 사람 기준이라 모두 지운다. 수는 그대로 둔다.
      setSummaries((prev) => Object.fromEntries(Object.entries(prev).map(([k, v]) => [k, { ...v, liked: false }])));
    }
  }, []);

  const toggleLike = useCallback(
    async (placeId: string) => {
      if (!user) {
        login(); // 로그인이 필요하다 → 카카오 로그인으로 보낸다
        return;
      }
      const before = summaries[placeId] ?? EMPTY;
      // 낙관적 갱신: 눌렀을 때 바로 반영하고, 서버 응답으로 확정하거나 실패하면 되돌린다
      setSummaries((p) => ({ ...p, [placeId]: { ...before, liked: !before.liked, likes: Math.max(0, before.likes + (before.liked ? -1 : 1)) } }));
      try {
        const r = await api.toggleLike(placeId);
        setSummaries((p) => ({ ...p, [placeId]: { ...(p[placeId] ?? before), liked: r.liked, likes: r.likes } }));
      } catch (e) {
        setSummaries((p) => ({ ...p, [placeId]: before }));
        if (e instanceof api.ApiError && e.status === 401) setUser(null); // 세션이 만료됨
        setNotice(e instanceof Error ? e.message : "좋아요를 처리하지 못했어요");
      }
    },
    [user, summaries, login],
  );

  const bumpComments = useCallback((placeId: string, delta: number) => {
    setSummaries((p) => {
      const cur = p[placeId] ?? EMPTY;
      return { ...p, [placeId]: { ...cur, comments: Math.max(0, cur.comments + delta) } };
    });
  }, []);

  const value = useMemo<SocialValue>(
    () => ({ enabled, loaded, user, summaries, notice, login, logout, load, toggleLike, bumpComments, dismissNotice: () => setNotice(null) }),
    [enabled, loaded, user, summaries, notice, login, logout, load, toggleLike, bumpComments],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
