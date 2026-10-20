import { useCallback, useEffect, useState } from "react";
import LikeButton from "./LikeButton";
import { useSocial } from "./SocialContext";
import * as api from "./social";
import type { CommentView } from "./social";

/** 장소 상세의 좋아요·댓글 영역 */
export default function SocialPanel({ placeId }: { placeId: string }) {
  const { enabled, user, summaries, login, load, bumpComments } = useSocial();
  const [comments, setComments] = useState<CommentView[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    load([placeId]); // 핀으로 열었을 때처럼 목록에 없던 장소의 좋아요·댓글 수도 불러온다
    let alive = true;
    setComments([]);
    setNext(null);
    setError(null);
    setText("");
    setLoading(true);
    api.fetchComments(placeId)
      .then((r) => alive && (setComments(r.comments), setNext(r.next_before)))
      .catch((e) => alive && setError(e instanceof Error ? e.message : "댓글을 불러오지 못했어요"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [placeId, enabled, user?.id, load]); // 로그인/로그아웃하면 '내 댓글' 표시가 바뀌므로 다시 불러온다

  const more = useCallback(async () => {
    if (!next) return;
    setLoading(true);
    try {
      const r = await api.fetchComments(placeId, next);
      setComments((c) => [...c, ...r.comments]);
      setNext(r.next_before);
    } catch (e) {
      setError(e instanceof Error ? e.message : "댓글을 불러오지 못했어요");
    } finally {
      setLoading(false);
    }
  }, [placeId, next]);

  if (!enabled) return null;
  const count = summaries[placeId]?.comments ?? comments.length;
  const body = text.trim();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!body || posting) return;
    setPosting(true);
    setError(null);
    try {
      const c = await api.postComment(placeId, body);
      setComments((list) => [c, ...list]);
      bumpComments(placeId, 1);
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "댓글을 등록하지 못했어요");
    } finally {
      setPosting(false);
    }
  };

  const remove = async (c: CommentView) => {
    if (!window.confirm("이 댓글을 삭제할까요?")) return;
    try {
      await api.deleteComment(c.id);
      setComments((list) => list.filter((x) => x.id !== c.id));
      bumpComments(placeId, -1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "삭제하지 못했어요");
    }
  };

  const report = async (c: CommentView) => {
    if (!window.confirm("이 댓글을 부적절한 내용으로 신고할까요?")) return;
    try {
      const r = await api.reportComment(c.id);
      if (r.hidden) {
        setComments((list) => list.filter((x) => x.id !== c.id)); // 신고가 쌓여 숨김 처리됨
        bumpComments(placeId, -1);
      }
      window.alert(r.reported ? "신고했어요. 확인 후 조치할게요." : "이미 신고한 댓글이에요.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "신고하지 못했어요");
    }
  };

  return (
    <section className="social-panel" aria-label="좋아요와 댓글">
      <div className="social-head">
        <LikeButton placeId={placeId} large />
        <span className="cmt-count">💬 댓글 {count}</span>
      </div>

      {user ? (
        <form className="composer" onSubmit={submit}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={api.MAX_COMMENT}
            rows={3}
            placeholder={`${user.nickname}님, 이 장소에 대한 이야기를 남겨 주세요`}
            aria-label="댓글 입력"
          />
          <div className="composer-foot">
            <small>{text.length}/{api.MAX_COMMENT}</small>
            <button disabled={!body || posting}>{posting ? "등록 중…" : "등록"}</button>
          </div>
        </form>
      ) : (
        <button className="kakao-login wide" onClick={login}>카카오로 로그인하고 댓글 남기기</button>
      )}

      {error && <p className="msg error" role="alert">{error}</p>}

      <ul className="comments">
        {comments.map((c) => (
          <li key={c.id} className="comment">
            <div className="comment-meta">
              <b>{c.nickname}</b>
              <small>{api.timeAgo(c.created_at)}</small>
              {c.mine ? (
                <button className="link small" onClick={() => remove(c)}>삭제</button>
              ) : (
                user && <button className="link small muted" onClick={() => report(c)}>신고</button>
              )}
            </div>
            <p className="comment-body">{c.body}</p>
          </li>
        ))}
      </ul>
      {!loading && comments.length === 0 && !error && <p className="hint">아직 댓글이 없어요. 첫 댓글을 남겨 보세요.</p>}
      {loading && <p className="hint">불러오는 중…</p>}
      {next && !loading && <button className="more" onClick={() => void more()}>댓글 더보기</button>}
    </section>
  );
}
