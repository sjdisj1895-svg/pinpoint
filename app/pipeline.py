"""파이프라인 뼈대. 이후 단계(T3~)는 Stage를 구현해 STAGES에 추가한다."""
from __future__ import annotations

from typing import Any, Protocol

from app.providers import EmptyProvider, RawDataProvider
from app.schemas import ParseRequest, Spot, T1Result
from app.stages.t1_intent import parse_intent
from app.stages.t2_harvester import harvest
from app.stages.t3_curator import curate

# 실제 검색/API 연동 시 이 값을 교체
provider: RawDataProvider = EmptyProvider()


class Stage(Protocol):
    name: str

    def run(self, ctx: dict[str, Any]) -> Any:
        """ctx를 받아 이 단계의 결과(JSON 직렬화 가능)를 반환(ctx[name]에 저장됨)."""


class T1Stage:
    name = "t1"

    def run(self, ctx: dict[str, Any]) -> Any:
        return parse_intent(ctx["request"]).model_dump(mode="json")


class T2Stage:
    name = "t2"

    def run(self, ctx: dict[str, Any]) -> Any:
        t1 = T1Result.model_validate(ctx["t1"])
        return [s.model_dump(mode="json", exclude_none=True) for s in harvest(t1, provider)]


class T3Stage:
    name = "t3"

    def run(self, ctx: dict[str, Any]) -> Any:
        t1 = T1Result.model_validate(ctx["t1"])
        spots = [Spot.model_validate(s) for s in ctx["t2"]]
        return curate(t1, spots).model_dump(mode="json", exclude_none=True)


# T4 이후 단계는 프롬프트 확정 후 여기에 추가
STAGES: list[Stage] = [T1Stage(), T2Stage(), T3Stage()]


def run_pipeline(req: ParseRequest) -> dict[str, Any]:
    ctx: dict[str, Any] = {"request": req}
    for stage in STAGES:
        ctx[stage.name] = stage.run(ctx)
    ctx.pop("request")
    return ctx
