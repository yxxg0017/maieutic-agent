"""run 管理：一个 session 同时只有一个活动 run；事件持久化后广播。"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from typing import Any

from .adapters import ChatModelAdapter, LocalChunkRetrieval, RetrievalAdapter
from .events import Event, EventFactory
from .runtime import RunContext
from .state import initial_state
from .store import Store

_run_counter = itertools.count(1)


class Channel:
    """按 session 广播事件。订阅者队列满时丢弃该订阅者，不阻塞图执行。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)

    def put_nowait(self, event: Event) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self.unsubscribe(queue)


@dataclass
class SessionRuntime:
    session_id: str
    channel: Channel = field(default_factory=Channel)
    task: asyncio.Task[None] | None = None
    ctx: RunContext | None = None
    resume_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RunManager:
    def __init__(
        self,
        store: Store,
        graph: Any,
        model_factory: Any,
    ) -> None:
        self.store = store
        self.graph = graph
        self._model_factory = model_factory
        self._sessions: dict[str, SessionRuntime] = {}

    # ------------------------------------------------------------ 基础设施

    def runtime(self, session_id: str) -> SessionRuntime:
        return self._sessions.setdefault(session_id, SessionRuntime(session_id))

    def is_busy(self, session_id: str) -> bool:
        runtime = self._sessions.get(session_id)
        return bool(runtime and runtime.task and not runtime.task.done())

    def _retrieval(self, session_id: str) -> RetrievalAdapter | None:
        chunks = self.store.list_chunks(session_id)
        return LocalChunkRetrieval(chunks) if chunks else None

    def _make_ctx(self, session_id: str, run_id: str) -> RunContext:
        runtime = self.runtime(session_id)
        model: ChatModelAdapter = self._model_factory()
        return RunContext(
            session_id=session_id,
            run_id=run_id,
            store=self.store,
            model=model,
            retrieval=self._retrieval(session_id),
            queue=runtime.channel,  # type: ignore[arg-type]
            factory=EventFactory(session_id, run_id, self.store.max_sequence(run_id)),
        )

    # ------------------------------------------------------------ 运行

    async def start_run(self, session_id: str, user_text: str) -> str:
        run_id = f"run_{session_id}_{next(_run_counter):04d}"
        self.store.create_run(run_id, session_id, thread_id=session_id)
        ctx = self._make_ctx(session_id, run_id)
        runtime = self.runtime(session_id)
        runtime.ctx = ctx
        state = initial_state(session_id, run_id, user_text)
        runtime.task = asyncio.create_task(self._drive(ctx, state))
        return run_id

    async def resume_run(self, session_id: str, payload: dict[str, Any]) -> str:
        from langgraph.types import Command

        run_id = f"run_{session_id}_{next(_run_counter):04d}"
        self.store.create_run(run_id, session_id, thread_id=session_id)
        ctx = self._make_ctx(session_id, run_id)
        runtime = self.runtime(session_id)
        runtime.ctx = ctx
        runtime.task = asyncio.create_task(self._drive(ctx, Command(resume=payload)))
        return run_id

    async def _drive(self, ctx: RunContext, payload: Any) -> None:
        ctx.emit("run.started", {"run_id": ctx.run_id})
        try:
            async for chunk in self.graph.astream(
                payload, config=ctx.config(), stream_mode="updates"
            ):
                if "__interrupt__" in chunk:
                    self.store.finish_run(ctx.run_id, "interrupted")
                    return
                if ctx.cancelled.is_set():
                    break
            if ctx.cancelled.is_set():
                ctx.emit("run.cancelled", {})
                self.store.finish_run(ctx.run_id, "cancelled", "user_requested_stop")
                return
            self.store.finish_run(ctx.run_id, "completed")
        except asyncio.CancelledError:
            ctx.emit("run.cancelled", {})
            self.store.finish_run(ctx.run_id, "cancelled", "user_requested_stop")
            raise
        except Exception as exc:  # 错误码对用户可读，不泄露堆栈与密钥
            code = getattr(exc, "code", "internal_error")
            ctx.emit("run.failed", {"code": code, "message": str(exc)[:300]})
            self.store.finish_run(ctx.run_id, "failed", code)

    async def cancel(self, session_id: str) -> bool:
        runtime = self._sessions.get(session_id)
        if not runtime or not runtime.task or runtime.task.done():
            return False
        if runtime.ctx:
            runtime.ctx.cancelled.set()
        runtime.task.cancel()
        try:
            await runtime.task
        except (asyncio.CancelledError, Exception):
            pass
        return True

    # ------------------------------------------------------------ 中断状态

    async def pending_interrupt(self, session_id: str) -> dict[str, Any] | None:
        """从 checkpoint 读取待回答中断，使应用重启后仍可恢复。"""
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": session_id}})
        interrupts = getattr(snapshot, "interrupts", None) or ()
        for item in interrupts:
            value = getattr(item, "value", None)
            if isinstance(value, dict):
                return value
        return None
