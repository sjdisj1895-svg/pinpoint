import { useEffect, useState } from "react";
import type { CSSProperties, Dispatch } from "react";
import LikeButton from "./LikeButton";
import { useSocial } from "./SocialContext";
import type { Action, State } from "./store";
import type { CardItem, Category, Course, RegionFacet, Weather } from "./types";
import type { PeriodFilter, SortKey } from "./geo";
import { ALL_CATEGORIES, CATEGORY_META, MONTHS, currentMonth, formatPeriod, regionLabel, statusLabel } from "./geo";
import Thumb from "./Thumb";

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
  const { enabled, user, login, logout } = useSocial();
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
      {enabled &&
        (user ? (
          <>
            <span className="me" title="카카오 계정으로 로그인 중">{user.nickname}</span>
            <button className="ghost" onClick={() => void logout()}>로그아웃</button>
          </>
        ) : (
          <button className="kakao-login" onClick={login}>카카오 로그인</button>
        ))}
    </header>
  );
}

/** 검색창: 입력하면 AI 없이 바로 찾고(내부 검색), 부족하면 ✨ AI 추천 버튼으로 같은 문장을 AI에게 묻는다 */
export const MAX_KEYWORD_LENGTH = 60; // 이보다 긴 입력은 키워드 검색이 아니라 AI에게 묻는 문장으로 본다 (서버 q 한도와 같다)

function SearchBox({ state, dispatch, onAsk, onSample }: {
  state: State; dispatch: Dispatch<Action>; onAsk: (t: string) => void; onSample: () => void;
}) {
  const text = state.queryInput;
  const ask = () => {
    const t = text.trim();
    if (t && !state.loading) onAsk(t);
  };
  return (
    <section className="searchbox">
      <form role="search" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <span aria-hidden>🔍</span>
          <input
            value={text}
            onChange={(e) => dispatch({ type: "setQueryInput", text: e.target.value })}
            placeholder="검색어를 입력하세요 (예: 진주 야경, 벚꽃, 영화관)"
            maxLength={2000}
            aria-label="축제·장소·지역 검색"
          />
          {text && (
            <button type="button" className="clear" aria-label="검색어 지우기" onClick={() => dispatch({ type: "setQueryInput", text: "" })}>✕</button>
          )}
        </div>
        <button type="button" className="ai" onClick={ask} disabled={state.loading || !text.trim()}>
          {state.loading ? "찾는 중…" : "✨ AI 추천"}
        </button>
      </form>
      <p className="hint">
        {text.trim().length > MAX_KEYWORD_LENGTH
          ? "문장이 길어요. ✨ AI 추천으로 물어보세요."
          : "키워드로 먼저 찾아보고, 문장으로 묻고 싶다면 ✨ AI 추천을 눌러 주세요."}
      </p>
      <div className="messages" aria-live="polite">
        {state.messages.slice(-3).map((m, i) => (
          <p key={i} className={`msg ${m.role}`}>{m.text}</p>
        ))}
        {state.loading && <p className="msg assistant">AI가 찾는 중이에요…</p>}
        {state.error && <p className="msg error">{state.error}</p>}
      </div>
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

function FilterBar({ state, dispatch, total, showChips, regionOptions, monthCounts }: {
  state: State; dispatch: Dispatch<Action>; total: number; showChips: boolean; regionOptions: RegionFacet[];
  monthCounts: Record<number, number>;
}) {
  const sorts = state.mode === "explore" ? SORTS.filter((s) => s.key !== "DISTANCE") : SORTS; // 둘러보기엔 기준점이 없다
  const filtered = !!(state.region || state.queryInput.trim() || state.months.length);
  const thisMonth = currentMonth();
  return (
    <section className="filters" aria-label="필터와 정렬">
      <div className="filter-row">
        <span className="filter-label">지역</span>
        <select
          className="region-select"
          value={state.region}
          onChange={(e) => dispatch({ type: "setRegion", region: e.target.value })}
          aria-label="시·군 선택"
        >
          <option value="">전체 시·군</option>
          {regionOptions.map((r) => (
            <option key={r.name} value={r.name}>{r.name} ({r.count})</option>
          ))}
          {state.region && !regionOptions.some((r) => r.name === state.region) && (
            <option value={state.region}>{state.region} (0)</option>
          )}
        </select>
        {filtered && (
          <button className="link small" onClick={() => dispatch({ type: "resetFilters" })}>필터 초기화</button>
        )}
      </div>
      <div className="filter-row">
        <span className="filter-label">시기</span>
        <div className="seg" role="group" aria-label="시기">
          {PERIODS.map((p) => (
            <button key={p.key} className={state.period === p.key ? "on" : ""} aria-pressed={state.period === p.key}
              onClick={() => dispatch({ type: "setPeriod", period: p.key })}>{p.label}</button>
          ))}
        </div>
      </div>
      <fieldset className="months">
        <legend className="filter-label">월</legend>
        <div className="month-grid">
          {MONTHS.map((m) => {
            const on = state.months.includes(m);
            const n = monthCounts[m] ?? 0;
            return (
              <label key={m} className={`month${on ? " on" : ""}${m === thisMonth ? " now" : ""}${n === 0 && !on ? " empty" : ""}`}
                title={m === thisMonth ? "이번 달" : undefined}>
                <input type="checkbox" checked={on} onChange={() => dispatch({ type: "toggleMonth", month: m })} />
                {m}월<small>{n}</small>
              </label>
            );
          })}
        </div>
        {state.months.length > 0 ? (
          <button className="link small" onClick={() => dispatch({ type: "clearMonths" })}>월 해제</button>
        ) : (
          <button className="link small" onClick={() => dispatch({ type: "toggleMonth", month: thisMonth })}>이번 달({thisMonth}월)만</button>
        )}
      </fieldset>
      {state.months.length > 0 && (
        <p className="hint month-hint">고른 달에 일정이 걸쳐 있는 행사만 보여요. 상시 운영하는 장소는 월을 고르면 빠집니다.</p>
      )}
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

/** 카드를 누르면 상세 서랍(PlaceDetail)이 열린다. 지도의 핀을 눌러도 같은 서랍이 열린다. */
function Card({ item, state, dispatch }: { item: CardItem; state: State; dispatch: Dispatch<Action> }) {
  const { spot } = item;
  const m = CATEGORY_META[spot.category];
  const selected = state.selectedId === spot.id;
  const { enabled, summaries } = useSocial();
  return (
    <li
      className={`pcard${selected ? " selected" : ""}`}
      style={{ "--c": m.color } as CSSProperties}
      onMouseEnter={() => dispatch({ type: "hover", id: spot.id })}
      onMouseLeave={() => dispatch({ type: "hover", id: null })}
    >
      <button className="pcard-main" onClick={() => dispatch({ type: "select", id: spot.id })} aria-haspopup="dialog">
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
          {item.why && <p className="why-snippet">💡 {item.why}</p>}
        </div>
      </button>
      {/* 좋아요·댓글 수: 버튼 안에 버튼을 넣을 수 없어 카드 아래 줄로 둔다. DB 고유 ID(place_id)가 있는 장소만 */}
      {enabled && spot.place_id && (
        <div className="pcard-foot">
          <LikeButton placeId={spot.place_id} />
          <span className="cmt-count" aria-label={`댓글 ${summaries[spot.place_id]?.comments ?? 0}개`}>
            💬 {summaries[spot.place_id]?.comments ?? 0}
          </span>
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
  mapEngine: "kakao" | "leaflet"; // 쓰고 있는 지도에 맞는 출처를 표기한다
  regionOptions: RegionFacet[]; // 시·군 선택지 (개수 포함)
  monthCounts: Record<number, number>; // 달별 행사 개수
}

export default function Panel({
  state, dispatch, items, shown, courses, onAsk, onSample, onReroute, onExplore, showChips, mapEngine, regionOptions,
  monthCounts,
}: PanelProps) {
  const keyword = state.queryInput.trim();
  const { enabled, load, notice, dismissNotice } = useSocial();
  // 지금 목록에 보이는 카드들의 좋아요·댓글 수를 한 번에 불러온다 ("더보기"로 늘어나면 새로 보이는 것만 추가)
  useEffect(() => {
    if (enabled) load(shown.map((i) => i.spot.place_id).filter((id): id is string => !!id));
  }, [enabled, shown, load]);
  return (
    <div className="panel">
      <Brand state={state} onExplore={onExplore} />
      <SearchBox state={state} dispatch={dispatch} onAsk={onAsk} onSample={onSample} />
      {notice && (
        <p className="msg error" role="alert" onClick={dismissNotice}>{notice} <small>(눌러서 닫기)</small></p>
      )}
      {state.data && (
        <FilterBar state={state} dispatch={dispatch} total={items.length} showChips={showChips} regionOptions={regionOptions}
          monthCounts={monthCounts} />
      )}
      {state.mode === "search" && <CourseBar courses={courses} state={state} dispatch={dispatch} />}
      {state.mode === "search" && state.data && <RerouteBar disabled={state.loading} onReroute={onReroute} />}
      {state.data && items.length === 0 && (
        <div className="empty">
          <p>
            {keyword && keyword.length <= MAX_KEYWORD_LENGTH ? `'${keyword}'에 맞는 곳이 없어요.` : "조건에 맞는 곳이 없어요."}{" "}
            필터를 바꾸거나 AI에게 물어보세요.
          </p>
          <div className="empty-actions">
            <button onClick={() => dispatch({ type: "resetFilters" })}>필터 초기화</button>
            {keyword && (
              <button className="ai" disabled={state.loading} onClick={() => onAsk(keyword)}>✨ AI에게 물어보기</button>
            )}
          </div>
        </div>
      )}
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
      {/* 모바일은 지도 위 표기가 시트에 가려져, 이용 조건에 맞게 시트 안에도 출처를 둔다 */}
      <footer className="credits">
        {mapEngine === "kakao" ? (
          <>지도 © <a href="https://map.kakao.com" target="_blank" rel="noopener noreferrer">Kakao</a></>
        ) : (
          <>
            지도 © <a href="https://openfreemap.org" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> ©{" "}
            <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener noreferrer">OpenMapTiles</a> · 데이터 ©{" "}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> 기여자
          </>
        )}{" "}
        · 사진 한국관광공사
      </footer>
    </div>
  );
}
