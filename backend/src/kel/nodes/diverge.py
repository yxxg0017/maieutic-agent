"""diverge：生成实质不同的候选。生成器不负责宣布最佳答案。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from .. import prompts
from ..contracts import DivergeOut
from ..events import new_id
from ..models import Candidate
from ..runtime import ctx_of
from .common import (
    enter,
    evidence_digest,
    model_failure_reason,
    note_degradation,
    request,
)


def _valid_evidence_ids(state: dict[str, Any]) -> set[str]:
    return {
        (item if isinstance(item, dict) else item.model_dump())["id"]
        for item in state.get("evidence_items", [])
    }


async def diverge(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "diverge")
    if state.get("candidates"):
        # 中断恢复后重放：沿用已有候选，避免候选漂移。
        return {"phase": "diverge"}

    answers = state.get("user_context", {}).get("answers", [])
    user = (
        f"目标：{state.get('topic', '')}\n期望产物：{state.get('desired_output', '')}\n"
        f"任务类型：{state.get('task_type', '')}\n用户澄清回答：{answers}\n"
        f"可引用来源（只能使用这些 ID）：\n{evidence_digest(state)}"
    )
    try:
        out = await ctx.model.structured(
            request("diverge", prompts.DIVERGE, user, temperature=0.9), DivergeOut
        )
    except Exception as exc:
        return {
            "phase": "diverge",
            "stop_reason": "diverge_unavailable",
            "degradations": note_degradation(
                state, f"候选生成不可用（{model_failure_reason(exc)}）"
            ),
        }

    allowed = _valid_evidence_ids(state)
    candidates: list[Candidate] = []
    seen_text: set[str] = set()
    for raw in out.candidates[:5]:
        key = raw.text.strip()[:80]
        if not key or key in seen_text:
            continue  # 丢弃同义改写
        seen_text.add(key)
        evidence_ids = [eid for eid in raw.evidence_ids if eid in allowed]
        assumptions = list(raw.assumptions)
        if not evidence_ids:
            assumptions.append("无可定位来源，基于模型已有知识（未核验）")
        candidate = Candidate(
            id=new_id("cand"),
            text=raw.text,
            mechanism=raw.mechanism,
            differentiator=raw.differentiator,
            evidence_ids=evidence_ids,
            assumptions=assumptions,
            verification=raw.verification,
            status="generated",
        )
        candidates.append(candidate)
        ctx.store.upsert_domain(
            "candidates", ctx.session_id, candidate.id, candidate.model_dump(), ctx.run_id
        )
        ctx.emit("candidate.created", candidate.model_dump())

    if len(candidates) < 2:
        return {
            "phase": "diverge",
            "candidates": candidates,
            "proposal_attempts": state.get("proposal_attempts", 0) + 1,
            "degradations": note_degradation(state, "候选不足两个，未形成实质对比"),
        }

    return {"phase": "diverge", "candidates": candidates}
