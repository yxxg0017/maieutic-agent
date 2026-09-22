"""模型调用契约。每个契约对应一次结构化调用，独立校验。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import CriterionName, TaskType


class MissingInfo(BaseModel):
    text: str
    changes_answer_how: str


class TaskFrameOut(BaseModel):
    topic: str
    task_type: TaskType
    depth: Literal["fast", "deep"]
    desired_output: str
    value_criteria: list[dict] = Field(default_factory=list)
    missing_information: list[MissingInfo] = Field(default_factory=list)
    need_fresh_sources: bool = False


class HypothesisOut(BaseModel):
    id: str
    text: str
    p: float


class QuestionOut(BaseModel):
    id: str
    text: str
    options: list[dict] = Field(default_factory=list)


class ClarifyOut(BaseModel):
    latent_variable: str
    hypotheses: list[HypothesisOut]
    questions: list[QuestionOut]


class LikelihoodRow(BaseModel):
    question_id: str
    hypothesis_id: str
    probabilities: dict[str, float]


class LikelihoodOut(BaseModel):
    rows: list[LikelihoodRow]


class CandidateOut(BaseModel):
    text: str
    mechanism: str
    differentiator: str
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    verification: str = ""


class DivergeOut(BaseModel):
    candidates: list[CandidateOut]


class CritiqueItem(BaseModel):
    candidate_index: int
    failure_modes: list[str] = Field(default_factory=list)
    boundary_probe: str = ""
    scores: dict[CriterionName, float] = Field(default_factory=dict)


class ChallengeOut(BaseModel):
    items: list[CritiqueItem]


class ClaimOut(BaseModel):
    text: str
    type: Literal["fact", "heuristic", "inference", "goal", "model_proposal"]
    evidence_ids: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class SynthesizeOut(BaseModel):
    answer_markdown: str
    kept_candidate_indexes: list[int] = Field(default_factory=list)
    rejected_candidate_indexes: list[int] = Field(default_factory=list)
    claims: list[ClaimOut] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class LearnCheckOut(BaseModel):
    kind: Literal["explain", "predict", "exercise", "implement"]
    prompt: str
    expected_signals: list[str] = Field(default_factory=list)


class AnswerInterpretationOut(BaseModel):
    selected_option: str
    confidence: float
    supporting_span: str = ""
