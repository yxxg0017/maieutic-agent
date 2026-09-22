"""fast_answer 与 finalize。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from .. import prompts
from ..events import new_id
from ..models import Message
from ..runtime import ctx_of
from .common import enter, evidence_digest, model_failure_reason, note_degradation, request


async def _stream_answer(ctx: Any, instruction: str, user: str) -> str:
    message_id = new_id("msg")
    ctx.emit("message.delta", {"message_id": message_id, "delta": ""})
    chunks: list[str] = []
    async for event in ctx.model.stream(request("answer", instruction, user)):
        if ctx.cancelled.is_set():
            break
        if event.kind == "delta":
            chunks.append(event.text)
            ctx.emit("message.delta", {"message_id": message_id, "delta": event.text})
    text = "".join(chunks)
    ctx.emit(
        "message.completed",
        {"message_id": message_id, "role": "assistant", "content": text},
    )
    ctx.store.add_message(message_id, ctx.session_id, "assistant", text, ctx.run_id)
    return text


async def fast_answer(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "fast_answer")
    degradations = state.get("degradations", [])
    user = (
        f"用户请求：{state.get('topic', '')}\n"
        f"期望产物：{state.get('desired_output', '')}\n"
        f"可用来源：\n{evidence_digest(state)}"
    )
    try:
        text = await _stream_answer(ctx, prompts.FAST_ANSWER, user)
    except Exception as exc:
        text = (
            "当前无法调用模型服务，未生成回答。\n\n"
            "已知本地信息：\n" + evidence_digest(state) + "\n\n"
            "下一步：在设置中配置模型服务后重试。"
        )
        message_id = new_id("msg")
        ctx.emit(
            "message.completed",
            {"message_id": message_id, "role": "assistant", "content": text},
        )
        ctx.store.add_message(message_id, ctx.session_id, "assistant", text, ctx.run_id)
        degradations = note_degradation(state, f"fast_answer 降级（{model_failure_reason(exc)}）")
    return {
        "phase": "fast_answer",
        "answer_markdown": text,
        "messages": [*state.get("messages", []), Message(
            id=new_id("m"), role="assistant", content=text, created_at="",
        )],
        "stop_reason": state.get("stop_reason") or "fast_answer_satisfied",
        "degradations": degradations,
    }


async def finalize(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "finalize")
    stop_reason = state.get("stop_reason") or "completed"
    ctx.store.update_session(ctx.session_id, phase="completed")
    ctx.emit(
        "run.completed",
        {
            "stop_reason": stop_reason,
            "unknowns": state.get("unknowns", []),
            "next_steps": state.get("next_steps", []),
            "degradations": state.get("degradations", []),
        },
    )
    return {"phase": "completed", "stop_reason": stop_reason}
