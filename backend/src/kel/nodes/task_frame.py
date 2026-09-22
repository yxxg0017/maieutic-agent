"""task_frame：识别目标、任务类型、深度、期望产物和价值标准。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from .. import prompts
from ..contracts import TaskFrameOut
from ..models import ValueCriterion
from ..runtime import ctx_of
from ..state import default_criteria
from .common import enter, model_failure_reason, note_degradation, request

DEEP_HINTS = (
    "比较", "对比", "选型", "设计", "架构", "为什么", "机制", "深入", "系统学",
    "诊断", "排查", "头脑风暴", "研究", "方案", "权衡", "复盘",
)


def heuristic_frame(user_text: str) -> TaskFrameOut:
    """模型不可用时的确定性降级：只依据显式信号，不编造目标。"""
    deep = any(hint in user_text for hint in DEEP_HINTS) or len(user_text) > 120
    task_type = "compare" if ("比较" in user_text or "对比" in user_text) else "learn"
    return TaskFrameOut(
        topic=user_text[:200],
        task_type=task_type,  # type: ignore[arg-type]
        depth="deep" if deep else "fast",
        desired_output="（未经模型框定，按关键词启发式判定）",
        missing_information=[],
        need_fresh_sources=False,
    )


async def task_frame(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "task_frame")
    user_text = state.get("topic", "")
    degradations = state.get("degradations", [])
    try:
        out = await ctx.model.structured(
            request("task_frame", prompts.TASK_FRAME, user_text),
            TaskFrameOut,
        )
    except Exception as exc:  # 模型不可用不阻塞整个会话
        out = heuristic_frame(user_text)
        degradations = note_degradation(state, f"task_frame 降级（{model_failure_reason(exc)}）")

    criteria = [
        ValueCriterion.model_validate(c)
        for c in out.value_criteria
        if isinstance(c, dict) and "name" in c and "weight" in c
    ] or default_criteria(out.task_type)

    ctx.store.update_session(
        ctx.session_id,
        topic=out.topic,
        task_type=out.task_type,
        depth=out.depth,
        phase="task_frame",
        title=out.topic[:80],
    )
    return {
        "phase": "task_frame",
        "topic": out.topic,
        "task_type": out.task_type,
        "depth": out.depth,
        "desired_output": out.desired_output,
        "value_criteria": criteria,
        "user_context": {
            "missing_information": [m.model_dump() for m in out.missing_information],
            "need_fresh_sources": out.need_fresh_sources,
        },
        "degradations": degradations,
    }


def depth_router(state: dict[str, Any]) -> str:
    """条件边：fast 直接作答，deep 进入完整流程。"""
    return "fast_answer" if state.get("depth") == "fast" else "clarify"
