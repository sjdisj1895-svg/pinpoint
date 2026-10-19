"""공개 배포용 간이 요청 제한 (IP별 슬라이딩 윈도). LLM 호출이 돈이 드는 라우트에만 건다.

서버리스에서는 인스턴스마다 메모리가 따로라 완벽한 제한은 아니다(최선의 방어선).
확실하게 막으려면 Vercel Firewall의 Rate Limit 규칙과 LLM 서비스의 사용 한도를 함께 설정한다.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

DEFAULT_LIMIT = 20  # 윈도 안에서 IP당 허용 횟수 (RATE_LIMIT, 0이면 끔)
WINDOW_SECONDS = 600


class RateLimiter:
    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self.hits) > 10_000:  # 메모리가 무한히 늘지 않게 오래된 키 정리
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > WINDOW_SECONDS]:
                del self.hits[k]
        return True

    def reset(self) -> None:
        self.hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """Vercel은 x-forwarded-for를 실제 접속자 IP로 설정한다. 없으면 소켓 주소를 쓴다."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def limit_llm(request: Request) -> None:
    """FastAPI 의존성: LLM을 호출하는 라우트에 붙인다."""
    try:
        limit = int(os.environ.get("RATE_LIMIT", DEFAULT_LIMIT))
    except ValueError:
        limit = DEFAULT_LIMIT
    if not limiter.allow(client_ip(request), limit):
        raise HTTPException(429, "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
