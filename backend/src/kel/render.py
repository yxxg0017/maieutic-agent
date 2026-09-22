"""终端渲染。基于 rich，集中所有展示逻辑，便于测试与替换。

渲染层不做业务判断：候选/来源/边界的语义（来源等级、裁决状态）由后端决定，
这里只负责让这些区别在终端里可见。
"""

from __future__ import annotations

from typing import Any, Iterable

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

PHASE_LABELS = {
    "task_frame": "框定任务",
    "clarify": "澄清关键信息",
    "source": "读取资料",
    "diverge": "生成候选",
    "challenge": "寻找反例与边界",
    "synthesize": "综合结论",
    "learn_check": "学习检查",
    "fast_answer": "直接作答",
    "finalize": "整理输出",
    "completed": "已完成",
}

TIER_STYLE = {
    "primary": ("一手", "bold green"),
    "secondary": ("二手", "yellow"),
    "model_only": ("未核验", "red"),
}

CANDIDATE_STATUS = {
    "generated": ("待裁决", "dim"),
    "kept": ("保留", "bold green"),
    "combined": ("组合", "bold cyan"),
    "rejected": ("淘汰", "red"),
}

CHALLENGE_STATUS = {
    "untested": ("模型提议，未裁决", "yellow"),
    "holds": ("成立", "bold green"),
    "does_not_hold": ("不成立", "red"),
    "conditional": ("仅在某条件成立", "cyan"),
    "not_encountered": ("没遇到过", "dim"),
    "unknown": ("无法判断", "dim"),
}

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def marker(index: int) -> str:
    return CIRCLED[index] if index < len(CIRCLED) else f"({index + 1})"


def tier_text(tier: str) -> Text:
    label, style = TIER_STYLE.get(tier, (tier, "dim"))
    return Text(f"[{label}]", style=style)


def _kv(label: str, value: str) -> Text:
    return Text.assemble((f"{label}：", "dim"), value)


def candidate_panel(index: int, candidate: dict[str, Any]) -> Panel:
    """候选的固定维度。评分分维度展示，不用单一总分掩盖差异。"""
    status, style = CANDIDATE_STATUS.get(
        candidate.get("status", ""), (candidate.get("status", ""), "dim")
    )
    rows: list[RenderableType] = []
    for label, key in (("关键差异", "differentiator"), ("机制", "mechanism")):
        if candidate.get(key):
            rows.append(_kv(label, candidate[key]))
    for label, key in (("假设", "assumptions"), ("失败模式", "failure_modes")):
        for item in candidate.get(key) or []:
            rows.append(_kv(label, item))
    if candidate.get("verification"):
        rows.append(_kv("最低成本验证", candidate["verification"]))
    scores = {
        name: value
        for name, value in (candidate.get("scores") or {}).items()
        if name != "aggregate"
    }
    if scores:
        rendered = "  ".join(f"{k} {float(v):.2f}" for k, v in sorted(scores.items()))
        rows.append(Text(rendered, style="dim"))
    return Panel(
        Group(*rows) if rows else Text("（无维度信息）", style="dim"),
        title=f"{marker(index)} {candidate.get('text', '')}",
        title_align="left",
        subtitle=Text(status, style=style),
        subtitle_align="right",
        border_style="grey37",
    )


def sources_table(sources: Iterable[dict[str, Any]]) -> Table:
    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False)
    table.add_column("等级", width=8)
    table.add_column("标题", overflow="fold")
    table.add_column("定位", overflow="fold", style="dim")
    for source in sources:
        table.add_row(
            tier_text(source.get("source_tier", "model_only")),
            source.get("title") or source.get("locator", ""),
            source.get("locator", ""),
        )
    return table


def challenges_table(challenges: Iterable[dict[str, Any]]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("#", width=3)
    table.add_column("内容", overflow="fold")
    table.add_column("裁决", width=18)
    for index, challenge in enumerate(challenges):
        label, style = CHALLENGE_STATUS.get(
            challenge.get("status", ""), (challenge.get("status", ""), "dim")
        )
        table.add_row(marker(index), challenge.get("text", ""), Text(label, style=style))
    return table


def claims_group(claims: Iterable[dict[str, Any]]) -> Group:
    rows: list[RenderableType] = []
    for claim in claims:
        rows.append(
            Text.assemble(
                tier_text(claim.get("source_tier", "model_only")),
                " ",
                claim.get("text", ""),
            )
        )
        for boundary in claim.get("boundaries") or []:
            rows.append(
                Padding(
                    Text(
                        f"边界（{boundary.get('status', 'untested')}）：{boundary.get('text', '')}",
                        style="dim",
                    ),
                    (0, 0, 0, 4),
                )
            )
        for link in claim.get("evidence_links") or []:
            rows.append(
                Padding(
                    Text(
                        f"证据 {link.get('evidence_id')}（{link.get('relation')}）",
                        style="dim cyan",
                    ),
                    (0, 0, 0, 4),
                )
            )
    return Group(*rows)


def papers_table(refs: list[Any]) -> Table:
    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False)
    table.add_column("#", width=3)
    table.add_column("来源", width=9)
    table.add_column("标题 / 作者 / 时间", overflow="fold")
    table.add_column("全文", width=6)
    for index, ref in enumerate(refs, start=1):
        authors = "、".join(ref.authors[:3]) + ("等" if len(ref.authors) > 3 else "")
        meta = " · ".join(x for x in (ref.published[:10], authors, ref.venue) if x)
        table.add_row(
            str(index),
            ref.source,
            Group(Text(ref.title), Text(meta, style="dim")),
            Text("可下载", style="green") if ref.pdf_url else Text("无", style="dim"),
        )
    return table


def question_panel(payload: dict[str, Any]) -> Panel:
    kind = "需要你确认一件事" if payload.get("kind") == "question" else "学习检查"
    rows: list[RenderableType] = [Text(payload.get("text", ""))]
    options = payload.get("options") or []
    if options:
        rows.append(Text(""))
        for number, option in enumerate(options, start=1):
            rows.append(Text(f"  {number}) {option.get('label', option.get('id'))}"))
        rows.append(
            Text("输入编号；回车=不确定；也可直接写文字补充", style="dim")
        )
    else:
        rows.append(Text("直接输入你的回答；回车留空表示跳过", style="dim"))
    return Panel(
        Group(*rows),
        title=kind,
        title_align="left",
        border_style="bright_blue",
    )


def bullets(title: str, items: list[str], style: str = "") -> Group:
    rows: list[RenderableType] = [Rule(title, style="dim", align="left")]
    rows += [Text(f"  - {item}", style=style) for item in items]
    return Group(*rows)


def sessions_table(sessions: list[dict[str, Any]], active: str | None = None) -> Table:
    table = Table(show_header=True, header_style="dim", box=None, pad_edge=False)
    table.add_column("", width=1)
    table.add_column("会话 ID", width=14)
    table.add_column("深度", width=6)
    table.add_column("阶段", width=12)
    table.add_column("标题", overflow="fold")
    for session in sessions:
        table.add_row(
            "*" if session["session_id"] == active else "",
            session["session_id"],
            session.get("depth", ""),
            PHASE_LABELS.get(session.get("phase", ""), session.get("phase", "")),
            session.get("title") or session.get("topic") or "未命名会话",
        )
    return table


def banner(model: str, base_url: str, data_dir: str, online: bool, configured: bool) -> Panel:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim", width=10)
    table.add_column(overflow="fold")
    table.add_row("模型", f"{model}  {base_url}")
    table.add_row(
        "密钥",
        Text("已配置", style="green") if configured else Text("未配置（将走离线降级）", style="red"),
    )
    table.add_row(
        "论文检索",
        Text("已开启（检索词会发往 arXiv / OpenAlex）", style="yellow")
        if online
        else Text("关闭（/online on 开启）", style="dim"),
    )
    table.add_row("数据目录", data_dir)
    return Panel(table, title="知识激发智能体", title_align="left", border_style="cyan")


def make_console() -> Console:
    return Console(soft_wrap=False, highlight=False)


def render_to_text(renderable: RenderableType, width: int = 100) -> str:
    """测试辅助：把渲染结果转成纯文本。"""
    import io

    console = Console(file=io.StringIO(), width=width, no_color=True, highlight=False)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[union-attr]


def answer_markdown(text: str) -> Markdown:
    return Markdown(text)
