"""SSE 事件协议。

事件信封与 `schemas/events.schema.json` 保持一致；前端类型由该 schema 生成。
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"

EventType = Literal[
    "run.started",
    "phase.changed",
    "message.delta",
    "message.completed",
    "source.added",
    "candidate.created",
    "candidate.updated",
    "challenge.created",
    "claim.updated",
    "learning_check.created",
    "interrupt.requested",
    "interrupt.resolved",
    "run.completed",
    "run.failed",
    "run.cancelled",
]

_counter = itertools.count(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class Event(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str
    session_id: str
    run_id: str
    sequence: int
    type: EventType
    timestamp: str = Field(default_factory=_now)
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> dict[str, str]:
        return {
            "id": self.event_id,
            "event": self.type,
            "data": json.dumps(self.model_dump(), ensure_ascii=False),
        }


class EventFactory:
    """按 run 生成严格递增的 sequence。"""

    def __init__(self, session_id: str, run_id: str, start_sequence: int = 0) -> None:
        self.session_id = session_id
        self.run_id = run_id
        self._sequence = start_sequence

    @property
    def sequence(self) -> int:
        return self._sequence

    def make(self, type_: EventType, payload: dict[str, Any] | None = None) -> Event:
        self._sequence += 1
        return Event(
            event_id=f"evt_{self.run_id}_{self._sequence}",
            session_id=self.session_id,
            run_id=self.run_id,
            sequence=self._sequence,
            type=type_,
            payload=payload or {},
        )


def new_id(prefix: str) -> str:
    """稳定顺序 ID。仅用于进程内临时对象；持久对象使用 store 分配的 ID。"""
    return f"{prefix}_{next(_counter):06d}"
