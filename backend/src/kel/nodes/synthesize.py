"""synthesize 与 learn_check。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from langgraph.types import interrupt

from .. import prompts
from ..contracts import LearnCheckOut, SynthesizeOut
from ..events import new_id
from ..models import (
    Boundary,
    Candidate,
    Claim,
    EvidenceLink,
    InterruptPayload,
    LearningCheck,
)
from ..runtime import ctx_of
from .common import (
    candidate_digest,
    enter,
    evidence_digest,
    model_failure_reason,
    note_degradation,
    request,
)


async def synthesize(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "synthesize")
    candidates = [
        c if isinstance(c, Candidate) else Candidate.model_validate(c)
        for c in state.get("candidates", [])
    ]
    user = (
        f"目标：{state.get('topic', '')}\n期望产物：{state.get('desired_output', '')}\n"
        f"候选：\n{candidate_digest(state)}\n"
        f"边界候选：{[c if isinstance(c, dict) else c.model_dump() for c in state.get('challenges', [])]}\n"
        f"可引用来源：\n{evidence_digest(state)}\n"
        f"已知降级：{state.get('degradations', [])}"
    )
    try:
        out = await ctx.model.structured(
            request("synthesize", prompts.SYNTHESIZE, user, temperature=0.3, max_tokens=4096),
            SynthesizeOut,
        )
    except Exception as exc:
        return {
            "phase": "synthesize",
            "stop_reason": "synthesize_unavailable",
            "degradations": note_degradation(
                state, f"综合阶段不可用（{model_failure_reason(exc)}）"
            ),
        }

    for index, candidate in enumerate(candidates):
        if index in out.kept_candidate_indexes:
            candidate.status = "kept"
        elif index in out.rejected_candidate_indexes:
            candidate.status = "rejected"
        ctx.store.upsert_domain(
            "candidates", ctx.session_id, candidate.id, candidate.model_dump(), ctx.run_id
        )
        ctx.emit("candidate.updated", candidate.model_dump())

    allowed = {
        (i if isinstance(i, dict) else i.model_dump())["id"]
        for i in state.get("evidence_items", [])
    }
    claims: list[Claim] = list(state.get("claims", []))
    for raw in out.claims:
        links = [
            EvidenceLink(evidence_id=eid, asserted_by="source")
            for eid in raw.evidence_ids
            if eid in allowed
        ]
        claim = Claim(
            id=new_id("c"),
            text=raw.text,
            type=raw.type if links or raw.type != "fact" else "model_proposal",
            source_tier="primary" if links else "model_only",
            evidence_links=links,
            boundaries=[Boundary(text=b, status="untested") for b in raw.boundaries],
            confidence=max(0.0, min(1.0, raw.confidence)),
            status="model_proposal",
        )
        claims.append(claim)
        ctx.store.upsert_domain(
            "claims", ctx.session_id, claim.id, claim.model_dump(), ctx.run_id
        )
        ctx.emit("claim.updated", claim.model_dump())

    message_id = new_id("msg")
    ctx.emit(
        "message.completed",
        {"message_id": message_id, "role": "assistant", "content": out.answer_markdown},
    )
    ctx.store.add_message(
        message_id, ctx.session_id, "assistant", out.answer_markdown, ctx.run_id
    )

    return {
        "phase": "synthesize",
        "candidates": candidates,
        "claims": claims,
        "answer_markdown": out.answer_markdown,
        "unknowns": out.unknowns,
        "next_steps": out.next_steps,
    }


async def learn_check(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "learn_check")
    budget = state["budget"]
    if state.get("task_type") not in {"learn", "externalize"} or (
        budget.turns_used >= budget.turn_budget
    ):
        return {"phase": "learn_check"}

    try:
        out = await ctx.model.structured(
            request(
                "learn_check",
                prompts.LEARN_CHECK,
                f"结论：\n{state.get('answer_markdown', '')[:2000]}",
            ),
            LearnCheckOut,
        )
    except Exception as exc:
        return {
            "phase": "learn_check",
            "degradations": note_degradation(
                state, f"学习检查跳过（{model_failure_reason(exc)}）"
            ),
        }

    check = LearningCheck(
        id=new_id("lc"),
        kind=out.kind,
        prompt=out.prompt,
        expected_signals=out.expected_signals,
    )
    payload = InterruptPayload(
        kind="learning_check",
        learning_check_id=check.id,
        text=check.prompt,
        free_text_allowed=True,
    )
    ctx.emit("learning_check.created", check.model_dump())
    ctx.emit("interrupt.requested", payload.model_dump())

    answer = interrupt(payload.model_dump())
    check.user_answer = str((answer or {}).get("free_text", ""))
    check.status = "answered" if check.user_answer else "skipped"
    budget.turns_used += 1
    ctx.emit(
        "interrupt.resolved",
        {"learning_check_id": check.id, "free_text": check.user_answer},
    )
    return {
        "phase": "learn_check",
        "learning_checks": [*state.get("learning_checks", []), check],
        "budget": budget,
    }
