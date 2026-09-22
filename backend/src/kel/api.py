"""FastAPI transport。仅监听回环地址，所有 /v1 路由要求启动期 token。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import export as export_service
from .adapters import OpenAICompatibleAdapter, ScriptedAdapter
from .config import ModelProfile, Settings, get_api_key, set_api_key
from .events import new_id
from .graph import build_graph
from .ingest import IngestError, store_attachment
from .runs import RunManager
from .security import TokenGuard
from .store import Store


class SessionCreate(BaseModel):
    title: str = ""


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)


class ResumeBody(BaseModel):
    question_id: str | None = None
    learning_check_id: str | None = None
    option_id: str | None = None
    free_text: str = ""


class DecisionBody(BaseModel):
    status: str
    user_note: str = ""


class ChallengeDecisionBody(BaseModel):
    status: str


class ApiKeyBody(BaseModel):
    api_key: str = Field(min_length=8)
    base_url: str | None = None
    model: str | None = None


def make_model_factory(settings: Settings, profile: ModelProfile):
    """密钥缺失或离线时返回离线适配器，让节点走显式降级路径。"""

    def factory():
        api_key = get_api_key()
        if settings.offline or not api_key:
            return ScriptedAdapter()
        return OpenAICompatibleAdapter(profile.base_url, api_key, profile.model)

    return factory


def create_app(
    settings: Settings,
    store: Store | None = None,
    model_factory: Any | None = None,
) -> FastAPI:
    store = store or Store(settings.db_path)
    profile = ModelProfile()
    state: dict[str, Any] = {}
    factory = model_factory or make_model_factory(settings, profile)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
            graph = build_graph(saver)
            state["graph"] = graph
            state["runs"] = RunManager(store, graph, factory)
            yield
        store.close()

    app = FastAPI(title="kel-sidecar", lifespan=lifespan, docs_url=None, redoc_url=None)
    guard = TokenGuard(settings.session_token)
    auth = [Depends(guard)]

    def runs() -> RunManager:
        return state["runs"]

    def require_session(session_id: str) -> dict[str, Any]:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(404, "session_not_found")
        return session

    # ----------------------------------------------------------------- 健康

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "schema_version": "1",
            "model_configured": bool(get_api_key()),
            "offline": settings.offline,
        }

    @app.post("/shutdown", dependencies=auth)
    async def shutdown() -> dict[str, str]:
        asyncio.get_running_loop().call_later(0.2, lambda: __import__("os")._exit(0))
        return {"status": "shutting_down"}

    # ----------------------------------------------------------------- 会话

    @app.post("/v1/sessions", dependencies=auth)
    async def create_session(body: SessionCreate) -> dict[str, Any]:
        session_id = new_id("sess")
        return store.create_session(session_id, body.title)

    @app.get("/v1/sessions", dependencies=auth)
    async def list_sessions() -> list[dict[str, Any]]:
        return store.list_sessions()

    @app.get("/v1/sessions/{session_id}", dependencies=auth)
    async def get_session(session_id: str) -> dict[str, Any]:
        session = require_session(session_id)
        return {
            **session,
            "messages": store.list_messages(session_id),
            "sources": store.list_domain("evidence_items", session_id),
            "candidates": store.list_domain("candidates", session_id),
            "claims": store.list_domain("claims", session_id),
            "challenges": store.list_domain("challenges", session_id),
            "attachments": [
                {k: v for k, v in a.items() if k != "stored_path"}
                for a in store.list_attachments(session_id)
            ],
            "pending_interrupt": await runs().pending_interrupt(session_id),
            "busy": runs().is_busy(session_id),
        }

    @app.delete("/v1/sessions/{session_id}", dependencies=auth)
    async def delete_session(session_id: str) -> dict[str, Any]:
        require_session(session_id)
        await runs().cancel(session_id)
        orphans = store.delete_session(session_id)
        for path in orphans:
            Path(path).unlink(missing_ok=True)
        return {"deleted": session_id, "removed_files": len(orphans)}

    # ----------------------------------------------------------------- run

    @app.post("/v1/sessions/{session_id}/messages", dependencies=auth)
    async def post_message(session_id: str, body: MessageCreate) -> dict[str, str]:
        require_session(session_id)
        if runs().is_busy(session_id):
            raise HTTPException(409, "run_in_progress")
        if await runs().pending_interrupt(session_id):
            raise HTTPException(409, "pending_interrupt_must_be_resumed")
        message_id = new_id("msg")
        store.add_message(message_id, session_id, "user", body.content)
        run_id = await runs().start_run(session_id, body.content)
        return {"run_id": run_id, "message_id": message_id}

    @app.post("/v1/sessions/{session_id}/resume", dependencies=auth)
    async def resume(session_id: str, body: ResumeBody) -> dict[str, str]:
        require_session(session_id)
        manager = runs()
        runtime = manager.runtime(session_id)
        async with runtime.resume_lock:
            pending = await manager.pending_interrupt(session_id)
            if not pending:
                raise HTTPException(409, "no_pending_interrupt")
            if manager.is_busy(session_id):
                raise HTTPException(409, "run_in_progress")
            expected_question = pending.get("question_id")
            expected_check = pending.get("learning_check_id")
            if expected_question and body.question_id != expected_question:
                raise HTTPException(409, "stale_question_id")
            if expected_check and body.learning_check_id != expected_check:
                raise HTTPException(409, "stale_learning_check_id")
            if body.free_text:
                store.add_message(new_id("msg"), session_id, "user", body.free_text)
            run_id = await manager.resume_run(
                session_id,
                {
                    "question_id": body.question_id,
                    "learning_check_id": body.learning_check_id,
                    "option_id": body.option_id,
                    "free_text": body.free_text,
                },
            )
        return {"run_id": run_id}

    @app.post("/v1/sessions/{session_id}/cancel", dependencies=auth)
    async def cancel(session_id: str) -> dict[str, bool]:
        require_session(session_id)
        return {"cancelled": await runs().cancel(session_id)}

    @app.get("/v1/sessions/{session_id}/events", dependencies=auth)
    async def events(
        session_id: str, request: Request, replay: bool = False
    ) -> EventSourceResponse:
        """默认长连接推送；`replay=true` 只回放历史事件后立即结束。"""
        require_session(session_id)
        manager = runs()
        runtime = manager.runtime(session_id)
        last_event_id = request.headers.get("last-event-id")
        backlog = store.events_after(session_id, last_event_id)
        queue = None if replay else runtime.channel.subscribe()

        async def generator():
            try:
                for event in backlog:
                    yield {
                        "id": event["event_id"],
                        "event": event["type"],
                        "data": json.dumps(event, ensure_ascii=False),
                    }
                if queue is None:
                    return
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield {"event": "ping", "data": "{}"}
                        continue
                    yield event.to_sse()
            finally:
                if queue is not None:
                    runtime.channel.unsubscribe(queue)

        return EventSourceResponse(generator())

    # ----------------------------------------------------------- 领域读取与裁决

    @app.get("/v1/sessions/{session_id}/sources", dependencies=auth)
    async def sources(session_id: str) -> list[dict[str, Any]]:
        require_session(session_id)
        return store.list_domain("evidence_items", session_id)

    @app.get("/v1/sessions/{session_id}/candidates", dependencies=auth)
    async def candidates(session_id: str) -> list[dict[str, Any]]:
        require_session(session_id)
        return store.list_domain("candidates", session_id)

    @app.post(
        "/v1/sessions/{session_id}/candidates/{candidate_id}/decision", dependencies=auth
    )
    async def candidate_decision(
        session_id: str, candidate_id: str, body: DecisionBody
    ) -> dict[str, Any]:
        require_session(session_id)
        if body.status not in {"kept", "combined", "rejected", "generated"}:
            raise HTTPException(422, "invalid_status")
        for candidate in store.list_domain("candidates", session_id):
            if candidate["id"] == candidate_id:
                candidate["status"] = body.status
                candidate["user_note"] = body.user_note
                store.upsert_domain("candidates", session_id, candidate_id, candidate)
                return candidate
        raise HTTPException(404, "candidate_not_found")

    @app.post(
        "/v1/sessions/{session_id}/challenges/{challenge_id}/decision", dependencies=auth
    )
    async def challenge_decision(
        session_id: str, challenge_id: str, body: ChallengeDecisionBody
    ) -> dict[str, Any]:
        require_session(session_id)
        allowed = {"holds", "does_not_hold", "conditional", "not_encountered", "unknown"}
        if body.status not in allowed:
            raise HTTPException(422, "invalid_status")
        for challenge in store.list_domain("challenges", session_id):
            if challenge["id"] == challenge_id:
                challenge["status"] = body.status  # 用户裁决与模型提议分别标识
                store.upsert_domain("challenges", session_id, challenge_id, challenge)
                return challenge
        raise HTTPException(404, "challenge_not_found")

    # ----------------------------------------------------------------- 附件

    @app.post("/v1/sessions/{session_id}/attachments", dependencies=auth)
    async def upload(session_id: str, file: UploadFile) -> dict[str, Any]:
        require_session(session_id)
        data = await file.read()
        try:
            record, chunks = store_attachment(
                session_id=session_id,
                filename=file.filename or "unnamed",
                data=data,
                attachments_dir=settings.attachments_dir,
            )
        except IngestError as exc:
            raise HTTPException(422, str(exc)) from exc
        store.add_attachment(record)
        store.add_chunks(record["attachment_id"], chunks)
        return {
            "attachment_id": record["attachment_id"],
            "filename": record["filename"],
            "chunks": len(chunks),
            "sha256": record["sha256"],
        }

    # ----------------------------------------------------------------- 导出

    @app.post("/v1/sessions/{session_id}/export", dependencies=auth)
    async def export(session_id: str) -> dict[str, Any]:
        require_session(session_id)
        out_dir = settings.data_dir / "exports"
        files = export_service.export_session(store, session_id, out_dir)
        return {"files": files}

    # ----------------------------------------------------------------- 设置

    @app.get("/v1/settings", dependencies=auth)
    async def get_settings() -> dict[str, Any]:
        return {
            "model_configured": bool(get_api_key()),
            "base_url": profile.base_url,
            "model": profile.model,
            "offline": settings.offline,
            "data_dir": str(settings.data_dir),
        }

    @app.post("/v1/settings/api_key", dependencies=auth)
    async def put_api_key(body: ApiKeyBody) -> dict[str, bool]:
        set_api_key(body.api_key)
        if body.base_url:
            profile.base_url = body.base_url
        if body.model:
            profile.model = body.model
        return {"model_configured": True}

    @app.exception_handler(IngestError)
    async def ingest_error(_: Request, exc: IngestError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return app
