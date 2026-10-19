import { useRef, useState } from "react";
import type { ReactNode } from "react";

// 3단계 높이 (뷰포트 비율): 접힘 / 중간 / 전체
const SNAPS = [0.14, 0.5, 0.88];

export default function BottomSheet({ children }: { children: ReactNode }) {
  const [snap, setSnap] = useState(1);
  const [dragH, setDragH] = useState<number | null>(null); // 드래그 중 높이(px)
  const start = useRef<{ y: number; h: number } | null>(null);
  const vh = () => window.innerHeight;

  const onDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    start.current = { y: e.clientY, h: SNAPS[snap] * vh() };
  };
  const onMove = (e: React.PointerEvent) => {
    if (!start.current) return;
    const h = start.current.h + (start.current.y - e.clientY);
    setDragH(Math.min(SNAPS[2] * vh(), Math.max(SNAPS[0] * vh(), h)));
  };
  const onUp = () => {
    if (dragH != null) {
      const ratio = dragH / vh();
      setSnap(SNAPS.reduce((best, s, i) => (Math.abs(s - ratio) < Math.abs(SNAPS[best] - ratio) ? i : best), 0));
    }
    start.current = null;
    setDragH(null);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowUp") setSnap((s) => Math.min(2, s + 1));
    if (e.key === "ArrowDown") setSnap((s) => Math.max(0, s - 1));
  };

  return (
    <div className={`sheet${dragH != null ? " dragging" : ""}`} style={{ height: dragH ?? `${SNAPS[snap] * 100}vh` }}>
      <div
        className="sheet-handle"
        role="slider"
        tabIndex={0}
        aria-label="바텀시트 높이 조절"
        aria-valuemin={0}
        aria-valuemax={2}
        aria-valuenow={snap}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onKeyDown={onKey}
      >
        <span />
      </div>
      <div className="sheet-body">{children}</div>
    </div>
  );
}
