import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { CATEGORY_META, formatPeriod, isMapSearchLink, regionLabel, safeUrl, statusLabel } from "./geo";
import Thumb from "./Thumb";
import type { CardItem } from "./types";

interface Props {
  item: CardItem;
  onClose: () => void;
  children?: React.ReactNode; // 좋아요·댓글 같은 소셜 영역이 들어갈 자리
}

/** 장소 상세. 카드나 지도의 핀을 누르면 목록 위치와 상관없이 항상 이 화면이 열린다. */
export default function PlaceDetail({ item, onClose, children }: Props) {
  const { spot } = item;
  const m = CATEGORY_META[spot.category];
  const url = safeUrl(spot.source_url);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus(); // 키보드·스크린리더 사용자가 바로 이 화면으로 들어오게
  }, [spot.id]);

  return (
    <div className="drawer-inner" role="dialog" aria-label={`${spot.title} 상세`} style={{ "--c": m.color } as CSSProperties}>
      <div className="drawer-top">
        <button ref={closeRef} className="back" onClick={onClose}>← 목록으로</button>
      </div>
      <div className="drawer-hero">
        <Thumb spot={spot} />
        <span className="b-cat">{m.emoji} {m.label}</span>
        <span className={`b-status s-${spot.schedule.live_status}`}>{statusLabel(spot)}</span>
      </div>
      <div className="drawer-body">
        <h2>{spot.title}</h2>
        <p className="drawer-sub">{spot.subtitle}</p>
        <p className="period">{formatPeriod(spot)}</p>
        {item.score != null && <p className="drawer-score">AI 추천 {item.score}점</p>}
        {item.why && <p className="why">💡 {item.why}</p>}
        {item.tips.length > 0 && <ul className="drawer-tips">{item.tips.map((t, i) => <li key={i}>{t}</li>)}</ul>}
        <dl>
          <dt>지역</dt><dd>{regionLabel(spot)}</dd>
          <dt>주소</dt><dd>{spot.location.address}</dd>
          <dt>운영</dt><dd>{spot.schedule.operating_hours}</dd>
          <dt>입장료</dt><dd>{spot.attributes.admission_fee}{spot.attributes.parking_available ? " · 주차 가능" : ""}</dd>
          {spot.attributes.vibe_tags.length > 0 && <><dt>분위기</dt><dd>{spot.attributes.vibe_tags.join(" ")}</dd></>}
        </dl>
        <small className="verify">✔ {spot.verification_note} (신뢰도 {Math.round(spot.confidence_score * 100)}%)</small>
        {spot.image_url?.includes("visitkorea.or.kr") && <small className="credit">사진: 한국관광공사 TourAPI</small>}
        {url && (
          <a className="drawer-link" href={url} target="_blank" rel="noopener noreferrer">
            {isMapSearchLink(url) ? "지도에서 검색 ↗" : "공식 안내 ↗"}
          </a>
        )}
        {children}
      </div>
    </div>
  );
}
