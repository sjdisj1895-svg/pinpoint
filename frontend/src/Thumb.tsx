import { useState } from "react";
import type { CSSProperties } from "react";
import { CATEGORY_META, safeUrl } from "./geo";
import type { Spot } from "./types";

/** 사진이 없거나 불러오지 못하면 카테고리 색 배경 + 이모지로 대체한다 */
export default function Thumb({ spot }: { spot: Spot }) {
  const [failed, setFailed] = useState(false);
  const meta = CATEGORY_META[spot.category];
  const src = safeUrl(spot.image_url);
  if (!src || failed) {
    return <div className="thumb-fallback" style={{ "--c": meta.color } as CSSProperties} aria-hidden>{meta.emoji}</div>;
  }
  return <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}
