"""LangGraph 状态图。节点顺序见桌面端实现说明第 6 节。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from . import nodes
from .state import AgentState


def _after_clarify(state: dict[str, Any]) -> str:
    return "finalize" if state.get("stop_reason") else "source"


def _after_diverge(state: dict[str, Any]) -> str:
    if state.get("stop_reason"):
        return "finalize"
    return "challenge" if state.get("candidates") else "finalize"


def _after_synthesize(state: dict[str, Any]) -> str:
    return "finalize" if state.get("stop_reason") else "learn_check"


def build_graph(checkpointer: Any | None = None):
    builder = StateGraph(AgentState)
    builder.add_node("task_frame", nodes.task_frame)
    builder.add_node("clarify", nodes.clarify)
    builder.add_node("source", nodes.source)
    builder.add_node("diverge", nodes.diverge)
    builder.add_node("challenge", nodes.challenge)
    builder.add_node("synthesize", nodes.synthesize)
    builder.add_node("learn_check", nodes.learn_check)
    builder.add_node("fast_answer", nodes.fast_answer)
    builder.add_node("finalize", nodes.finalize)

    builder.set_entry_point("task_frame")
    builder.add_conditional_edges(
        "task_frame",
        nodes.depth_router,
        {"fast_answer": "fast_answer", "clarify": "clarify"},
    )
    builder.add_edge("fast_answer", "finalize")
    builder.add_conditional_edges(
        "clarify", _after_clarify, {"finalize": "finalize", "source": "source"}
    )
    builder.add_edge("source", "diverge")
    builder.add_conditional_edges(
        "diverge", _after_diverge, {"finalize": "finalize", "challenge": "challenge"}
    )
    builder.add_edge("challenge", "synthesize")
    builder.add_conditional_edges(
        "synthesize",
        _after_synthesize,
        {"finalize": "finalize", "learn_check": "learn_check"},
    )
    builder.add_edge("learn_check", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
