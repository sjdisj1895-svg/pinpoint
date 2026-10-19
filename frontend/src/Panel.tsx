import { useState } from "react";
import type { CSSProperties, Dispatch } from "react";
import type { Action, State } from "./store";
import type { CardItem, Category, Course, Spot, Weather } from "./types";
import type { PeriodFilter, SortKey } from "./geo";
import {
  ALL_CATEGORIES, CATEGORY_META, formatPeriod, isMapSearchLink, regionLabel, safeUrl, statusLabel,
} from "./geo";

export function CategoryChips({ active, dispatch }: { active: Category[]; dispatch: Dispatch<Action> }) {
  return (
    <div className="chips" role="group" aria-label="카테고리 필터">
      {ALL_CATEGORIES.map((c) => {
        const m = CATEGORY_META[c];
        const on = active.includes(c);
        return (
          <button
            key={c}
            className={`chip${on ? " on" : ""}`}
            style={{ "--c": m.color } as CSSProperties}
            aria-pressed={on}
            onClick={() => dispatch({ type: "toggleCategory", category: c })}
          >
            {m.emoji} {m.label}
          </button>
        );
      })}
    </div>
  );
}

function Brand({ state, onExplore }: { state: State; onExplore: () => void }) {
  return (
    <header className="brand">
      <span className="logo" aria-hidden>📍</span>
      <div className="brand-text">
        <b>PinPlay</b>
        <small>경남 로컬 큐레이션</small>
      </div>
      {state.mode === "search" && (
        <button className="ghost" onClick={onExplore} disabled={state.loading}>경남 둘러보기</button>
      )}
    </header>
  );
}

function Chat({ state, onAsk, onSample }: { state: State; onAsk: (t: string) => void; onSample: () => void }) {
  const [text, setText] = useState("");
  return (
    <section className="chat">
      <div className="messages" aria-live="polite">
        {state.messages.slice(-3).map((m, i) => (
          <p key={i} className={`msg ${m.role}`}>{m.text}</p>
        ))}
        {state.loading && <p className="msg assistant">찾는 중이에요…</p>}
        {state.error && <p className="msg error">{state.error}</p>}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = text.trim();
          if (t && !state.loading) {
            onAsk(t);
            setText("");
          }
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="예: 이번 주말 진주에서 연인이랑 야경 보기 좋은 곳"
          maxLength={2000}
          aria-label="어디서 어떻게 놀고 싶은지 입력"
        />
        <button disabled={state.loading}>{state.loading ? "찾는 중…" : "추천"}</button>
      </form>
      {!state.data && state.mode === "search" && (
        <button className="link" onClick={onSample}>샘플 데이터로 화면 확인</button>
      )}
    </section>
  );
}

const PERIODS: { key: PeriodFilter; label: string }[] = [
  { key: "ALL", label: "전체" },
  { key: "NOW", label: "개최중" },
  { key: "SOON", label: "개최예정" },
];
const SORTS: { key: SortKey; label: string }[] = [
  { key: "RECOMMEND", label: "추천순" },
  { key: "DATE", label: "일정순" },
  { key: "DISTANCE", label: "거리순" },
];

function FilterBar({ state, dispatch, total, showChips }: {
  state: State; dispatch: Dispatch<Action>; total: number; showChips: boolean;
}) {
  const sorts = state.mode === "explore" ? SORTS.filter((s) => s.key !== "DISTANCE") : SORTS; // 둘러보기엔 기준점이 없다
  return (
    <section className="filters" aria-label="필터와 정렬">
      <div className="filter-row">
        <span className="filter-label">시기</span>
        <div className="seg" role="group" aria-label="시기">
          {PERIODS.map((p) => (
            <button key={p.key} className={state.period === p.key ? "on" : ""} aria-pressed={state.period === p.key}
              onClick={() => dispatch({ type: "setPeriod", period: p.key })}>{p.label}</button>
          ))}
        </div>
      </div>
      {showChips && (
        <div className="filter-row">
          <span className="filter-label">분류</span>
          <CategoryChips active={state.activeCategories} dispatch={dispatch} />
        </div>
      )}
      <div className="filter-row between">
        <span className="count">총 <b>{total}</b>곳</span>
        <div className="sort" role="tablist" aria-label="정렬">
          {sorts.map((s) => (
            <button key={s.key} role="tab" aria-selected={state.sort === s.key} className={state.sort === s.key ? "on" : ""}
              onClick={() => dispatch({ type: "setSort", sort: s.key })}>{s.label}</button>
          ))}
        </div>
      </div>
    </section>
  );
}

const QUICK_REROUTE: { label: string; text: string; weather?: Weather }[] = [
  { label: "☔ 비 와요", text: "갑자기 비가 와요. 실내로 바꿔 주세요", weather: "RAIN" },
  { label: "⏰ 늦었어요", text: "일정이 늦어졌어요. 지금 갈 수 있는 곳으로 다시 짜 주세요" },
  { label: "👥 사람 많아요", text: "사람이 너무 많아요. 한적한 곳으로 바꿔 주세요" },
  { label: "🅿️ 주차 편한 곳", text: "주차가 편한 곳으로 바꿔 주세요" },
];

function RerouteBar({ disabled, onReroute }: { disabled: boolean; onReroute: (text: string, weather?: Weather) => void }) {
  const [text, setText] = useState("");
  return (
    <details className="reroute">
      <summary>지금 상황이 달라졌나요? <small>비·지연·취향 변경 반영</small></summary>
      <div className="chips">
        {QUICK_REROUTE.map((q) => (
          <button key={q.label} className="chip" disabled={disabled} onClick={() => onReroute(q.text, q.weather)}>{q.label}</button>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = text.trim();
          if (t && !disabled) {
            onReroute(t);
            setText("");
          }
        }}
      >
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="예: 조금 더 로컬스러운 곳으로" maxLength={1000} />
        <button disabled={disabled}>변경</button>
      </form>
    </details>
  );
}

function CourseBar({ courses, state, dispatch }: { courses: Course[]; state: State; dispatch: Dispatch<Action> }) {
  if (!courses.length) return null;
  return (
    <section className="course-bar">
      <label className="toggle">
        <input type="checkbox" checked={state.showCourse} onChange={() => dispatch({ type: "toggleCourse" })} />
        AI 추천 코스 보기
      </label>
      {state.showCourse && (
        <div className="course-list">
          {courses.map((c) => (
            <button
              key={c.course_id}
              className={`course${state.courseId === c.course_id ? " on" : ""}`}
              onClick={() => dispatch({ type: "pickCourse", id: c.course_id })}
            >
              <b>{c.title}</b>
              <small>{c.duration_type === "HALF_DAY" ? "반나절" : "하루"} · {c.stops.length}곳 · {c.score}점</small>
            </button>
          ))}
          {state.courseId && (
            <p className="why">{courses.find((c) => c.course_id === state.courseId)?.why_for_you}</p>
          )}
        </div>
      )}
    </section>
  );
}

/** 사진이 없거나 불러오지 못하면 카테고리 색 배경 + 이모지로 대체한다 */
function Thumb({ spot }: { spot: Spot }) {
  const [failed, setFailed] = useState(false);
  const meta = CATEGORY_META[spot.category];
  const src = safeUrl(spot.image_url);
  if (!src || failed) {
    return <div className="thumb-fallback" style={{ "--c": meta.color } as CSSProperties} aria-hidden>{meta.emoji}</div>;
  }
  return <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

function Card({ item, state, dispatch }: { item: CardItem; state: State; dispatch: Dispatch<Action> }) {
  const { spot } = item;
  const m = CATEGORY_META[spot.category];
  const selected = state.selectedId === spot.id;
  const url = safeUrl(spot.source_url);
  return (
    <li
      className={`pcard${selected ? " selected" : ""}`}
      style={{ "--c": m.color } as CSSProperties}
      onMouseEnter={() => dispatch({ type: "hover", id: spot.id })}
      onMouseLeave={() => dispatch({ type: "hover", id: null })}
    >
      <button className="pcard-main" onClick={() => dispatch({ type: "select", id: selected ? null : spot.id })} aria-expanded={selected}>
        <div className="thumb">
          <Thumb spot={spot} />
          <span className="b-cat">{m.emoji} {m.label}</span>
          <span className={`b-status s-${spot.schedule.live_status}`}>{statusLabel(spot)}</span>
          {item.score != null && <span className="b-score">{item.score}점</span>}
        </div>
        <div className="pbody">
          <strong>{spot.title}</strong>
          <span className="period">{formatPeriod(spot)}</span>
          <span className="region">📍 {regionLabel(spot)}</span>
          {item.why && !selected && <p className="why-snippet">💡 {item.why}</p>}
        </div>
      </button>
      {selected && (
        <div className="pdetail">
          <p className="sub">{spot.subtitle}</p>
          {item.why && <p className="why">💡 {item.why}</p>}
          {item.tips.length > 0 && <ul>{item.tips.map((t, i) => <li key={i}>{t}</li>)}</ul>}
          <dl>
            <dt>주소</dt><dd>{spot.location.address}</dd>
            <dt>운영</dt><dd>{spot.schedule.operating_hours}</dd>
            <dt>입장료</dt><dd>{spot.attributes.admission_fee}{spot.attributes.parking_available ? " · 주차 가능" : ""}</dd>
          </dl>
          <small className="verify">✔ {spot.verification_note} (신뢰도 {Math.round(spot.confidence_score * 100)}%)</small>
          {spot.image_url && spot.image_url.includes("visitkorea.or.kr") && (
            <small className="credit">사진: 한국관광공사 TourAPI</small>
          )}
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer">
              {isMapSearchLink(url) ? "지도에서 검색 ↗" : "공식 안내 ↗"}
            </a>
          )}
        </div>
      )}
    </li>
  );
}

interface PanelProps {
  state: State;
  dispatch: Dispatch<Action>;
  items: CardItem[]; // 필터·정렬이 적용된 전체 결과
  shown: CardItem[]; // 그중 지금 보이는 만큼 ("더보기")
  courses: Course[];
  onAsk: (t: string) => void;
  onSample: () => void;
  onReroute: (text: string, weather?: Weather) => void;
  onExplore: () => void;
  showChips: boolean; // 모바일은 지도 위 플로팅 칩을 쓴다
}

export default function Panel({ state, dispatch, items, shown, courses, onAsk, onSample, onReroute, onExplore, showChips }: PanelProps) {
  return (
    <div className="panel">
      <Brand state={state} onExplore={onExplore} />
      <Chat state={state} onAsk={onAsk} onSample={onSample} />
      {state.data && <FilterBar state={state} dispatch={dispatch} total={items.length} showChips={showChips} />}
      {state.mode === "search" && <CourseBar courses={courses} state={state} dispatch={dispatch} />}
      {state.mode === "search" && state.data && <RerouteBar disabled={state.loading} onReroute={onReroute} />}
      {state.data && items.length === 0 && <p className="hint">조건에 맞는 곳이 없어요. 시기나 분류 필터를 바꿔 보세요.</p>}
      {!state.data && !state.loading && (
        <p className="hint">경남의 진행 중인 축제와 볼거리를 불러오는 중이에요. 바로 원하는 곳을 물어봐도 좋아요.</p>
      )}
      <ul className="cards">
        {shown.map((it) => <Card key={it.spot.id} item={it} state={state} dispatch={dispatch} />)}
      </ul>
      {shown.length < items.length && (
        <button className="more" onClick={() => dispatch({ type: "loadMore" })}>
          더보기 ({shown.length}/{items.length})
        </button>
      )}
    </div>
  );
}
