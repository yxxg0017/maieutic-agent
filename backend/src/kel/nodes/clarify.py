"""clarify：只询问会改变答案的信息，并用 EIG 选题。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

import numpy as np
from langgraph.types import interrupt

from .. import prompts
from ..contracts import ClarifyOut, LikelihoodOut
from ..eig import apply_noise_floor, entropy, posterior, rank_questions
from ..events import new_id
from ..models import (
    EntropyRecord,
    Hypothesis,
    HypothesisSet,
    InterruptPayload,
    Question,
    QuestionOption,
)
from ..runtime import ctx_of
from .common import (
    enter,
    evidence_digest,
    model_failure_reason,
    note_degradation,
    request,
)

FIXED_OPTIONS = [
    QuestionOption(id="other", label="其他"),
    QuestionOption(id="uncertain", label="不确定"),
]


def _build_questions(out: ClarifyOut) -> list[Question]:
    questions: list[Question] = []
    for raw in out.questions:
        options = [
            QuestionOption(id=str(o["id"]), label=str(o.get("label", o["id"])))
            for o in raw.options
            if isinstance(o, dict) and "id" in o and str(o["id"]) not in {"other", "uncertain"}
        ][:5]
        if len(options) < 2:
            continue
        questions.append(
            Question(id=raw.id, text=raw.text, options=[*options, *FIXED_OPTIONS])
        )
    return questions[:5]


def _likelihood_matrix(
    question: Question,
    hypotheses: list[Hypothesis],
    rows: dict[tuple[str, str], dict[str, float]],
) -> tuple[np.ndarray, bool]:
    """返回 (矩阵, 是否降级)。缺失或非法行使用均匀分布。"""
    option_ids = [o.id for o in question.options]
    matrix = np.zeros((len(hypotheses), len(option_ids)))
    degraded = False
    for i, hypothesis in enumerate(hypotheses):
        row = rows.get((question.id, hypothesis.id))
        values = (
            np.array([max(float(row.get(opt, 0.0)), 0.0) for opt in option_ids])
            if row
            else np.zeros(len(option_ids))
        )
        if row is None or values.sum() <= 0:
            degraded = True
            values = np.full(len(option_ids), 1.0 / len(option_ids))
        matrix[i] = values / values.sum()
    return matrix, degraded


async def clarify(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "clarify")
    budget = state["budget"]
    degradations = state.get("degradations", [])

    if budget.turns_used >= budget.turn_budget:
        return {"phase": "clarify", "stop_reason": "turn_budget_exhausted"}

    user = (
        f"目标：{state.get('topic', '')}\n期望产物：{state.get('desired_output', '')}\n"
        f"缺失信息：{state.get('user_context', {}).get('missing_information', [])}\n"
        f"已有来源：\n{evidence_digest(state)}"
    )
    try:
        out = await ctx.model.structured(
            request("clarify", prompts.CLARIFY, user), ClarifyOut
        )
        hypotheses = [Hypothesis(id=h.id, text=h.text, p=h.p) for h in out.hypotheses]
        total = sum(h.p for h in hypotheses)
        if total <= 0:
            raise ValueError("invalid prior")
        for h in hypotheses:
            h.p = h.p / total
        hset = HypothesisSet(
            id=new_id("hs"),
            latent_variable=out.latent_variable,
            status="frozen",
            hypotheses=hypotheses,
        )
        questions = _build_questions(out)
        if not questions:
            raise ValueError("no usable question")
    except Exception as exc:
        # 无法构造有效假设集时不追问，直接进入检索，避免无价值提问。
        return {
            "phase": "clarify",
            "degradations": note_degradation(
                state, f"clarify 跳过（{model_failure_reason(exc)}）"
            ),
        }

    ctx.store.save_hypothesis_set(ctx.session_id, hset.model_dump())
    for question in questions:
        ctx.store.upsert_domain(
            "questions", ctx.session_id, question.id, question.model_dump()
        )

    # likelihood 批量估计；模型不得计算 EIG。
    rows: dict[tuple[str, str], dict[str, float]] = {}
    likelihood_source = "llm_estimated"
    try:
        matrix_out = await ctx.model.structured(
            request(
                "likelihood",
                prompts.LIKELIHOOD,
                "假设集：\n"
                + "\n".join(f"{h.id}: {h.text}" for h in hset.hypotheses)
                + "\n问题：\n"
                + "\n".join(
                    f"{q.id}: {q.text} 选项 {[o.id for o in q.options]}" for q in questions
                ),
            ),
            LikelihoodOut,
        )
        rows = {
            (row.question_id, row.hypothesis_id): row.probabilities
            for row in matrix_out.rows
        }
    except Exception as exc:
        likelihood_source = "uniform_fallback"
        degradations = note_degradation(
            state, f"likelihood 均匀降级（{model_failure_reason(exc)}）"
        )

    prior = np.array([h.p for h in hset.hypotheses])
    matrices: dict[str, np.ndarray] = {}
    degraded_ids: set[str] = set()
    persisted = []
    for question in questions:
        matrix, degraded = _likelihood_matrix(question, hset.hypotheses, rows)
        matrices[question.id] = matrix
        if degraded:
            degraded_ids.add(question.id)
        for i, hypothesis in enumerate(hset.hypotheses):
            persisted.append(
                {
                    "question_id": question.id,
                    "hypothesis_id": hypothesis.id,
                    "probabilities": {
                        option.id: float(matrix[i][j])
                        for j, option in enumerate(question.options)
                    },
                    "source": "uniform_fallback" if degraded else likelihood_source,
                }
            )
    ctx.store.save_likelihoods(ctx.session_id, persisted)

    ranked = rank_questions(prior, matrices, degraded_ids)
    best = ranked[0]
    if best.eig < budget.min_eig_to_ask:
        return {
            "phase": "clarify",
            "hypothesis_sets": [*state.get("hypothesis_sets", []), hset],
            "questions": questions,
            "stop_reason": None,
            "degradations": degradations,
        }

    question = next(q for q in questions if q.id == best.question_id)
    payload = InterruptPayload(
        kind="question",
        question_id=question.id,
        text=question.text,
        options=question.options,
    )
    entropy_before = entropy(prior)
    ctx.emit("interrupt.requested", payload.model_dump() | {"predicted_eig": best.eig})

    answer = interrupt(payload.model_dump())

    option_id = str((answer or {}).get("option_id") or "uncertain")
    option_ids = [o.id for o in question.options]
    posterior_dist = prior
    entropy_after = entropy_before
    if option_id in option_ids and option_id not in {"other", "uncertain"}:
        index = option_ids.index(option_id)
        posterior_dist = posterior(
            prior, apply_noise_floor(matrices[question.id]), index
        )
        entropy_after = entropy(posterior_dist)
        for i, hypothesis in enumerate(hset.hypotheses):
            hypothesis.p = float(posterior_dist[i])

    record = EntropyRecord(
        hypothesis_set_id=hset.id,
        hypothesis_set_version=hset.version,
        question_id=question.id,
        predicted_eig=best.eig,
        entropy_before=entropy_before,
        entropy_after=entropy_after,
        answer_option_id=option_id,
        prior={h.id: float(prior[i]) for i, h in enumerate(hset.hypotheses)},
        posterior={h.id: float(posterior_dist[i]) for i, h in enumerate(hset.hypotheses)},
    )
    ctx.store.add_entropy_record(ctx.session_id, ctx.run_id, record.model_dump())
    ctx.emit(
        "interrupt.resolved",
        {
            "question_id": question.id,
            "option_id": option_id,
            "free_text": (answer or {}).get("free_text", ""),
            "entropy_before": entropy_before,
            "entropy_after": entropy_after,
        },
    )

    budget.turns_used += 1
    user_context = dict(state.get("user_context", {}))
    user_context.setdefault("answers", []).append(
        {
            "question_id": question.id,
            "question": question.text,
            "option_id": option_id,
            "free_text": (answer or {}).get("free_text", ""),
        }
    )
    return {
        "phase": "clarify",
        "hypothesis_sets": [*state.get("hypothesis_sets", []), hset],
        "questions": questions,
        "entropy_trace": [*state.get("entropy_trace", []), record],
        "user_context": user_context,
        "budget": budget,
        "pending_interrupt": None,
        "degradations": degradations,
    }
