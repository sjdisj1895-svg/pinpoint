import { compactCount } from "./social";
import { useSocial } from "./SocialContext";

/** 좋아요 버튼. 로그인하지 않았으면 눌렀을 때 카카오 로그인으로 보낸다. 소셜 기능이 꺼져 있으면 아무것도 그리지 않는다. */
export default function LikeButton({ placeId, large = false }: { placeId: string; large?: boolean }) {
  const { enabled, summaries, toggleLike } = useSocial();
  if (!enabled) return null;
  const s = summaries[placeId] ?? { likes: 0, comments: 0, liked: false };
  return (
    <button
      type="button"
      className={`like${s.liked ? " on" : ""}${large ? " large" : ""}`}
      aria-pressed={s.liked}
      aria-label={`좋아요 ${s.likes}개${s.liked ? ", 내가 누름" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        void toggleLike(placeId);
      }}
    >
      <span aria-hidden>{s.liked ? "♥" : "♡"}</span> {compactCount(s.likes)}
    </button>
  );
}
