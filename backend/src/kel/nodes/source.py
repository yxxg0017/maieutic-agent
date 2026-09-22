"""source：读取用户材料与可定位来源，统一为 EvidenceItem。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from ..adapters import SearchQuery
from ..events import new_id
from ..models import EvidenceItem
from ..runtime import ctx_of
from .common import enter, model_failure_reason, note_degradation


def _kind_for(locator: str) -> str:
    if locator.startswith(("arxiv:", "openalex:", "doi:")):
        return "research_paper"
    if locator.startswith("attachment:"):
        return "course_example" if locator.endswith(".md") else "paper_passage"
    if locator.startswith("http"):
        return "official_documentation"
    return "runtime_observation"


async def source(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = ctx_of(config)
    enter(ctx, "source")
    degradations = state.get("degradations", [])
    existing = {
        (item if isinstance(item, dict) else item.model_dump())["locator"]
        for item in state.get("evidence_items", [])
    }
    items = list(state.get("evidence_items", []))

    if ctx.retrieval is None:
        return {
            "phase": "source",
            "degradations": note_degradation(state, "无检索适配器，仅使用模型已有知识（未核验）"),
        }

    try:
        results = await ctx.retrieval.search(
            SearchQuery(text=state.get("topic", ""), limit=6)
        )
    except Exception as exc:
        return {
            "phase": "source",
            "degradations": note_degradation(
                state, f"检索失败，降级为模型已有知识（{model_failure_reason(exc)}）"
            ),
        }

    for result in results:
        if result.locator in existing:
            continue  # 节点重放时不重复创建来源
        item = EvidenceItem(
            id=new_id("ev"),
            kind=_kind_for(result.locator),  # type: ignore[arg-type]
            title=result.title,
            context=result.snippet,
            source_tier=result.tier,  # type: ignore[arg-type]
            locator=result.locator,
            version=result.version,
            status="retrieved",
        )
        items.append(item)
        existing.add(result.locator)
        ctx.store.upsert_domain(
            "evidence_items", ctx.session_id, item.id, item.model_dump()
        )
        ctx.emit("source.added", item.model_dump())

    if not items:
        degradations = note_degradation(state, "未找到可定位来源：以下内容为模型已有知识，未核验")

    return {"phase": "source", "evidence_items": items, "degradations": degradations}
