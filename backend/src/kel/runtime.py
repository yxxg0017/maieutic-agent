"""运行上下文。节点通过 LangGraph config 获取它，不使用全局单例。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig

from .adapters import ChatModelAdapter, RetrievalAdapter
from .events import Event, EventFactory, EventType
from .store import Store


@dataclass
class RunContext:
    session_id: str
    run_id: str
    store: Store
    model: ChatModelAdapter
    retrieval: RetrievalAdapter | None
    queue: asyncio.Queue[Event | None]
    factory: EventFactory
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    def emit(self, type_: EventType, payload: dict[str, Any] | None = None) -> Event:
        """持久化后入队。持久化失败（重复）时不重复推送。"""
        event = self.factory.make(type_, payload)
        if self.store.append_event(event.model_dump()):
            self.queue.put_nowait(event)
        return event

    def config(self) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": self.session_id,
                "ctx": self,
            }
        }


def ctx_of(config: RunnableConfig) -> RunContext:
    ctx = (config or {}).get("configurable", {}).get("ctx")
    if ctx is None:
        raise RuntimeError("RunContext missing in config.configurable.ctx")
    return ctx
