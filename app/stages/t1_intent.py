"""T1: 사용자 의도 및 성향 분석기."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import anthropic

from app.llm import LLMOutputError, ask_json
from app.schemas import ParseRequest, T1Result

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "t1_system.md").read_text(encoding="utf-8")
T1ParseError = LLMOutputError


def build_user_message(req: ParseRequest, today: date) -> str:
    profile = req.profile.model_dump_json() if req.profile else "없음"
    return f"오늘 날짜: {today.isoformat()}\n사용자 프로필: {profile}\n사용자 입력: {req.text}"


def extract_json(text: str) -> dict:
    """모델이 코드펜스 등을 붙여도 JSON 객체만 추출."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON 객체를 찾을 수 없음")
    return json.loads(text[start : end + 1])


def parse_intent(req: ParseRequest, client: anthropic.Anthropic | None = None) -> T1Result:
    user = build_user_message(req, req.today or date.today())
    return ask_json(SYSTEM_PROMPT, user, lambda t: T1Result.model_validate(extract_json(t)), client)
