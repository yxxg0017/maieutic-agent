"""challenge：为候选寻找反例、边界与失败模式；评分聚合由代码完成。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from .. import prompts
from ..contracts import ChallengeOut
from ..eig import weighted_score
from ..events import new_id
from ..models import Candidate, Challenge
from ..runtime import ctx_of
from .common import (
    candidate_digest,
    enter,
    model_failure_reason,
    note_degradation,
    request,
)


async def challenge(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "challenge")
    candidates = [
        c if isinstance(c, Candidate) else Candidate.model_validate(c)
        for c in state.get("candidates", [])
    ]
    if not candidates:
        return {"phase": "challenge"}

    budget = state["budget"]
    weights = {
        (c if isinstance(c, dict) else c.model_dump())["name"]:
        (c if isinstance(c, dict) else c.model_dump())["weight"]
        for c in state.get("value_criteria", [])
    }

    user = (
        f"目标：{state.get('topic', '')}\n候选：\n{candidate_digest(state)}\n"
        f"价值标准：{weights}"
    )
    try:
        out = await ctx.model.structured(
            request("challenge", prompts.CHALLENGE, user, temperature=0.3), ChallengeOut
        )
    except Exception as exc:
        return {
            "phase": "challenge",
            "candidates": candidates,
            "degradations": note_degradation(
                state, f"批判阶段不可用，候选未经反例检验（{model_failure_reason(exc)}）"
            ),
        }

    challenges = list(state.get("challenges", []))
    for item in out.items:
        if not 0 <= item.candidate_index < len(candidates):
            continue
        candidate = candidates[item.candidate_index]
        candidate.failure_modes = item.failure_modes
        candidate.scores = {k: float(v) for k, v in item.scores.items()}
        candidate.scores["aggregate"] = weighted_score(candidate.scores, weights)
        ctx.store.upsert_domain(
            "candidates", ctx.session_id, candidate.id, candidate.model_dump(), ctx.run_id
        )
        ctx.emit("candidate.updated", candidate.model_dump())

        if item.boundary_probe and budget.challenges_used < budget.max_challenges:
            probe = Challenge(
                id=new_id("ch"),
                candidate_id=candidate.id,
                text=item.boundary_probe,
                source="model_generated_probe",
                status="untested",  # 模型提出的边界只能是 untested
            )
            challenges.append(probe)
            budget.challenges_used += 1
            ctx.store.upsert_domain(
                "challenges", ctx.session_id, probe.id, probe.model_dump()
            )
            ctx.emit("challenge.created", probe.model_dump())

    return {
        "phase": "challenge",
        "candidates": candidates,
        "challenges": challenges,
        "budget": budget,
    }
