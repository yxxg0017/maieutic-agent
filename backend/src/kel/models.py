"""领域模型。所有跨层数据结构都在这里定义，并由 Pydantic 校验。

规格来源：`知识激发智能体_实现规格.md` 第 4 节。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SourceTier = Literal["primary", "secondary", "model_only"]

EvidenceKind = Literal[
    "personal_event",
    "experiment_observation",
    "paper_passage",
    "course_example",
    "code_result",
    "advisor_feedback",
    "official_documentation",
    "source_code",
    "research_paper",
    "runtime_observation",
    "model_knowledge",
]

CriterionName = Literal[
    "relevance", "specificity", "evidence", "novelty", "actionability", "robustness"
]

TaskType = Literal[
    "learn", "solve", "compare", "design", "research", "brainstorm", "externalize"
]

Phase = Literal[
    "task_frame",
    "depth_router",
    "clarify",
    "source",
    "diverge",
    "challenge",
    "synthesize",
    "learn_check",
    "finalize",
    "completed",
]


class SourceSpan(BaseModel):
    turn_id: str | None = None
    quote: str
    relation: Literal["supports", "refutes", "qualifies"] = "supports"


class EvidenceItem(BaseModel):
    id: str
    kind: EvidenceKind
    title: str = ""
    context: str = ""
    observed_at_time: list[str] = Field(default_factory=list)
    later_learned: list[str] = Field(default_factory=list)
    current_interpretation: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)
    source_tier: SourceTier
    locator: str
    version: str | None = None
    status: Literal["model_proposal", "user_confirmed", "retrieved"] = "retrieved"

    @model_validator(mode="after")
    def _model_only_has_no_fake_locator(self) -> EvidenceItem:
        if self.source_tier == "model_only" and not self.locator.startswith("model:"):
            # `model_only` 不得伪装成外部引用。
            object.__setattr__(self, "locator", "model:unverified")
        return self


class ValueCriterion(BaseModel):
    name: CriterionName
    weight: float = Field(ge=0.0, le=1.0)


class Candidate(BaseModel):
    id: str
    text: str
    mechanism: str = ""
    differentiator: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    verification: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    status: Literal["generated", "kept", "combined", "rejected"] = "generated"
    user_note: str = ""


class EvidenceLink(BaseModel):
    evidence_id: str
    turn_id: str | None = None
    quote: str = ""
    relation: Literal["supports", "refutes", "qualifies"] = "supports"
    asserted_by: Literal["user", "model", "source"] = "model"


class Boundary(BaseModel):
    text: str
    status: Literal["untested", "user_supported", "user_rejected", "conditional"] = (
        "untested"
    )
    confirmed_by_turn_id: str | None = None


class Claim(BaseModel):
    id: str
    text: str
    type: Literal["fact", "heuristic", "inference", "goal", "model_proposal"] = (
        "inference"
    )
    source_tier: SourceTier = "model_only"
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    boundaries: list[Boundary] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: Literal["model_proposal", "user_confirmed", "rejected"] = "model_proposal"

    @model_validator(mode="after")
    def _unsourced_is_proposal(self) -> Claim:
        if not self.evidence_links and self.type == "fact":
            object.__setattr__(self, "type", "model_proposal")
            object.__setattr__(self, "source_tier", "model_only")
        return self


class Challenge(BaseModel):
    id: str
    claim_id: str | None = None
    candidate_id: str | None = None
    text: str
    source: Literal["model_generated_probe", "user_provided"] = "model_generated_probe"
    status: Literal[
        "untested", "holds", "does_not_hold", "conditional", "not_encountered", "unknown"
    ] = "untested"
    confirmed_by_turn_id: str | None = None


class Hypothesis(BaseModel):
    id: str
    text: str
    p: float = Field(ge=0.0, le=1.0)


class HypothesisSet(BaseModel):
    id: str
    version: int = 1
    latent_variable: str
    status: Literal["draft", "frozen", "closed"] = "draft"
    hypotheses: list[Hypothesis]

    @field_validator("hypotheses")
    @classmethod
    def _at_least_two(cls, value: list[Hypothesis]) -> list[Hypothesis]:
        if len(value) < 2:
            raise ValueError("hypothesis set needs at least two hypotheses")
        return value

    @model_validator(mode="after")
    def _probabilities_sum_to_one(self) -> HypothesisSet:
        total = sum(h.p for h in self.hypotheses)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"hypothesis probabilities must sum to 1, got {total}")
        return self


class QuestionOption(BaseModel):
    id: str
    label: str


class Question(BaseModel):
    id: str
    text: str
    kind: Literal["discrete", "open"] = "discrete"
    options: list[QuestionOption] = Field(default_factory=list)
    hypothesis_set_id: str | None = None


class QuestionLikelihood(BaseModel):
    question_id: str
    hypothesis_id: str
    probabilities: dict[str, float]
    source: Literal["llm_estimated", "empirical", "uniform_fallback"] = "llm_estimated"


class EntropyRecord(BaseModel):
    hypothesis_set_id: str
    hypothesis_set_version: int
    question_id: str
    predicted_eig: float
    entropy_before: float
    entropy_after: float | None = None
    answer_option_id: str | None = None
    prior: dict[str, float] = Field(default_factory=dict)
    posterior: dict[str, float] = Field(default_factory=dict)


class Budget(BaseModel):
    turn_budget: int = 12
    turns_used: int = 0
    max_challenges: int = 2
    challenges_used: int = 0
    min_eig_to_ask: float = 0.03
    max_proposal_attempts: int = 2
    answer_mapping_threshold: float = 0.70


class LearningCheck(BaseModel):
    id: str
    kind: Literal["explain", "predict", "exercise", "implement"]
    prompt: str
    expected_signals: list[str] = Field(default_factory=list)
    feedback: str = ""
    user_answer: str = ""
    status: Literal["pending", "answered", "skipped"] = "pending"


class Message(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str


class InterruptPayload(BaseModel):
    kind: Literal["question", "learning_check"]
    question_id: str | None = None
    learning_check_id: str | None = None
    text: str
    options: list[QuestionOption] = Field(default_factory=list)
    free_text_allowed: bool = True


class TaskFrame(BaseModel):
    topic: str
    task_type: TaskType = "learn"
    depth: Literal["fast", "deep"] = "fast"
    desired_output: str = ""
    value_criteria: list[ValueCriterion] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    need_fresh_sources: bool = False
    user_context: dict[str, Any] = Field(default_factory=dict)
