"""LangGraph 状态定义。state 是会话业务状态的唯一真源。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from .models import (
    Budget,
    Candidate,
    Challenge,
    Claim,
    EntropyRecord,
    EvidenceItem,
    HypothesisSet,
    InterruptPayload,
    LearningCheck,
    Message,
    Question,
    ValueCriterion,
)


class AgentState(TypedDict, total=False):
    session_id: str
    run_id: str
    phase: str
    topic: str
    task_type: str
    depth: Literal["fast", "deep"]
    desired_output: str
    user_context: dict[str, Any]
    value_criteria: list[ValueCriterion]
    evidence_items: list[EvidenceItem]
    hypothesis_sets: list[HypothesisSet]
    candidates: list[Candidate]
    claims: list[Claim]
    challenges: list[Challenge]
    questions: list[Question]
    entropy_trace: list[EntropyRecord]
    learning_checks: list[LearningCheck]
    pending_interrupt: InterruptPayload | None
    messages: list[Message]
    budget: Budget
    proposal_attempts: int
    stop_reason: str | None
    answer_markdown: str
    unknowns: list[str]
    next_steps: list[str]
    degradations: list[str]


DEFAULT_CRITERIA: dict[str, list[tuple[str, float]]] = {
    "learn": [
        ("relevance", 0.2),
        ("specificity", 0.25),
        ("evidence", 0.2),
        ("actionability", 0.2),
        ("robustness", 0.15),
    ],
    "compare": [
        ("relevance", 0.15),
        ("evidence", 0.3),
        ("robustness", 0.3),
        ("actionability", 0.25),
    ],
    "design": [
        ("relevance", 0.2),
        ("evidence", 0.2),
        ("robustness", 0.25),
        ("actionability", 0.35),
    ],
    "brainstorm": [
        ("novelty", 0.4),
        ("relevance", 0.2),
        ("specificity", 0.2),
        ("actionability", 0.2),
    ],
    "research": [
        ("evidence", 0.4),
        ("relevance", 0.2),
        ("novelty", 0.2),
        ("robustness", 0.2),
    ],
    "solve": [
        ("relevance", 0.2),
        ("evidence", 0.25),
        ("actionability", 0.35),
        ("robustness", 0.2),
    ],
    "externalize": [
        ("evidence", 0.35),
        ("specificity", 0.25),
        ("relevance", 0.2),
        ("robustness", 0.2),
    ],
}


def default_criteria(task_type: str) -> list[ValueCriterion]:
    pairs = DEFAULT_CRITERIA.get(task_type, DEFAULT_CRITERIA["learn"])
    return [ValueCriterion(name=name, weight=weight) for name, weight in pairs]  # type: ignore[arg-type]


def initial_state(session_id: str, run_id: str, user_text: str) -> AgentState:
    return AgentState(
        session_id=session_id,
        run_id=run_id,
        phase="task_frame",
        topic=user_text[:200],
        task_type="learn",
        depth="fast",
        desired_output="",
        user_context={},
        value_criteria=[],
        evidence_items=[],
        hypothesis_sets=[],
        candidates=[],
        claims=[],
        challenges=[],
        questions=[],
        entropy_trace=[],
        learning_checks=[],
        pending_interrupt=None,
        messages=[],
        budget=Budget(),
        proposal_attempts=0,
        stop_reason=None,
        answer_markdown="",
        unknowns=[],
        next_steps=[],
        degradations=[],
    )
