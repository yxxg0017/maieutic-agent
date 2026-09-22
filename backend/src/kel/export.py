"""导出：summary.md、graph.json、replay.jsonl。自动剔除密钥与绝对路径。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .store import Store

_HOME = re.compile(re.escape(str(Path.home())))


def _sanitize(text: str) -> str:
    return _HOME.sub("~", text)


def build_summary(store: Store, session_id: str) -> str:
    session = store.get_session(session_id) or {}
    claims = store.list_domain("claims", session_id)
    candidates = store.list_domain("candidates", session_id)
    evidence = store.list_domain("evidence_items", session_id)
    challenges = store.list_domain("challenges", session_id)
    messages = store.list_messages(session_id)

    lines = [
        f"# {session.get('title') or session.get('topic') or session_id}",
        "",
        f"- 任务类型：{session.get('task_type')}",
        f"- 深度：{session.get('depth')}",
        f"- 阶段：{session.get('phase')}",
        "",
        "## 结论",
        "",
    ]
    final = [m for m in messages if m["role"] == "assistant"]
    lines.append(final[-1]["content"] if final else "（无结论）")

    lines += ["", "## Claim 与边界", ""]
    for claim in claims:
        tier = claim.get("source_tier", "model_only")
        lines.append(f"- [{tier}] {claim['text']}（confidence {claim.get('confidence')}）")
        for boundary in claim.get("boundaries", []):
            lines.append(f"  - 边界（{boundary.get('status')}）：{boundary['text']}")
        for link in claim.get("evidence_links", []):
            lines.append(f"  - 证据：{link['evidence_id']}（{link['relation']}）")

    lines += ["", "## 候选取舍", ""]
    for candidate in candidates:
        lines.append(f"- [{candidate.get('status')}] {candidate['text']}")
        if candidate.get("differentiator"):
            lines.append(f"  - 关键差异：{candidate['differentiator']}")
        for mode in candidate.get("failure_modes", []):
            lines.append(f"  - 失败模式：{mode}")
        if candidate.get("verification"):
            lines.append(f"  - 验证：{candidate['verification']}")

    lines += ["", "## 来源", ""]
    for item in evidence:
        lines.append(
            f"- [{item['source_tier']}] {item.get('title') or item['locator']} — {item['locator']}"
        )
    if not evidence:
        lines.append("- 无可定位来源：内容为模型已有知识，未核验")

    lines += ["", "## 未裁决的边界探针", ""]
    for challenge in challenges:
        lines.append(f"- [{challenge['status']}] {challenge['text']}")

    return _sanitize("\n".join(lines) + "\n")


def build_graph_json(store: Store, session_id: str) -> dict[str, Any]:
    evidence = store.list_domain("evidence_items", session_id)
    claims = store.list_domain("claims", session_id)
    challenges = store.list_domain("challenges", session_id)
    nodes = [
        {"id": e["id"], "kind": "evidence", "tier": e["source_tier"], "label": e.get("title") or e["locator"]}
        for e in evidence
    ] + [
        {"id": c["id"], "kind": "claim", "tier": c.get("source_tier"), "label": c["text"]}
        for c in claims
    ]
    edges = []
    for claim in claims:
        for link in claim.get("evidence_links", []):
            edges.append(
                {"from": link["evidence_id"], "to": claim["id"], "relation": link["relation"]}
            )
        for index, boundary in enumerate(claim.get("boundaries", [])):
            boundary_id = f"{claim['id']}_b{index}"
            nodes.append(
                {
                    "id": boundary_id,
                    "kind": "boundary",
                    "tier": None,
                    "label": boundary["text"],
                    "status": boundary.get("status"),
                }
            )
            edges.append({"from": claim["id"], "to": boundary_id, "relation": "bounded_by"})
    for challenge in challenges:
        nodes.append(
            {
                "id": challenge["id"],
                "kind": "challenge",
                "tier": None,
                "label": challenge["text"],
                "status": challenge["status"],
            }
        )
        target = challenge.get("claim_id") or challenge.get("candidate_id")
        if target:
            edges.append({"from": challenge["id"], "to": target, "relation": "challenges"})
    return {"session_id": session_id, "nodes": nodes, "edges": edges}


def build_replay(store: Store, session_id: str) -> str:
    records = [
        {"kind": "event", **event} for event in store.events_after(session_id)
    ] + [
        {"kind": "entropy", **record}
        for record in store.list_entropy_records(session_id)
    ]
    return _sanitize(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    )


def export_session(store: Store, session_id: str, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = out_dir / f"{session_id}_summary.md"
    graph = out_dir / f"{session_id}_graph.json"
    replay = out_dir / f"{session_id}_replay.jsonl"
    summary.write_text(build_summary(store, session_id), encoding="utf-8")
    graph.write_text(
        json.dumps(build_graph_json(store, session_id), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    replay.write_text(build_replay(store, session_id), encoding="utf-8")
    return [str(summary), str(graph), str(replay)]
