#!/usr/bin/env python
"""从 Pydantic 模型生成 schemas/events.schema.json。

协议单一真源在 Python 侧；前端 TypeScript 类型由该 schema 生成，避免两套手写类型漂移。
用法：python scripts/gen_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from pydantic import BaseModel  # noqa: E402

from kel.events import SCHEMA_VERSION, Event  # noqa: E402
from kel.models import (  # noqa: E402
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
    TaskFrame,
    ValueCriterion,
)


class EventProtocol(BaseModel):
    """把信封与所有领域负载收拢到一个 schema 文件。"""

    event: Event
    task_frame: TaskFrame
    evidence_item: EvidenceItem
    candidate: Candidate
    claim: Claim
    challenge: Challenge
    question: Question
    hypothesis_set: HypothesisSet
    interrupt_payload: InterruptPayload
    learning_check: LearningCheck
    entropy_record: EntropyRecord
    value_criterion: ValueCriterion
    budget: Budget
    message: Message


def main() -> int:
    schema = EventProtocol.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://maieutic.local/schemas/events.schema.json"
    schema["title"] = "KelEventProtocol"
    schema["description"] = (
        f"知识激发智能体前后端共享事件协议（schema_version {SCHEMA_VERSION}）。"
        "由 scripts/gen_schema.py 生成，请勿手工编辑。"
    )
    out = ROOT / "schemas" / "events.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
