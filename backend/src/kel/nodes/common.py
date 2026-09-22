"""节点共享工具。"""

from __future__ import annotations

from typing import Any

from ..adapters import ModelError, ModelRequest
from ..prompts import GLOBAL_CONSTRAINTS
from ..runtime import RunContext


def request(contract: str, instruction: str, user: str, **kwargs: Any) -> ModelRequest:
    return ModelRequest(
        system=f"{GLOBAL_CONSTRAINTS}\n\n{instruction}",
        user=user,
        metadata={"contract": contract},
        **kwargs,
    )


def enter(ctx: RunContext, phase: str) -> None:
    ctx.emit("phase.changed", {"phase": phase})


def note_degradation(state: dict[str, Any], reason: str) -> list[str]:
    """记录降级原因。降级必须对用户可见，不能静默伪装成正常结果。"""
    return [*state.get("degradations", []), reason]


def model_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ModelError):
        return f"{exc.code}: {exc}"
    return f"model_error: {type(exc).__name__}"


def evidence_digest(state: dict[str, Any], limit: int = 12) -> str:
    """把证据压成模型可引用的紧凑列表，保留 ID 与来源等级。"""
    lines = []
    for item in state.get("evidence_items", [])[:limit]:
        data = item if isinstance(item, dict) else item.model_dump()
        lines.append(
            f"- {data['id']} [{data['source_tier']}] {data.get('title') or data['locator']}: "
            f"{(data.get('context') or '')[:300]}"
        )
    return "\n".join(lines) or "（无可定位来源）"


def candidate_digest(state: dict[str, Any]) -> str:
    lines = []
    for index, item in enumerate(state.get("candidates", [])):
        data = item if isinstance(item, dict) else item.model_dump()
        lines.append(
            f"[{index}] {data['text']}\n    机制：{data.get('mechanism', '')}\n"
            f"    关键差异：{data.get('differentiator', '')}"
        )
    return "\n".join(lines) or "（无候选）"


def as_dict(obj: Any) -> dict[str, Any]:
    return obj if isinstance(obj, dict) else obj.model_dump()
