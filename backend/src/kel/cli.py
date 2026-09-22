"""对话式 CLI。形态参考 Codex CLI：底部组合输入 + 流式输出 + 斜杠命令。

    kel                      新建会话
    kel "比较三种方案…"       新建会话并直接提问
    kel --list               列出历史会话
    kel --session <id>       恢复会话（含未回答的 interrupt）
    kel --online             允许论文检索（检索词会发往 arXiv / OpenAlex）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.text import Text

from .adapters import OpenAICompatibleAdapter, ScriptedAdapter
from .config import ModelProfile, Settings, get_api_key
from .events import Event, new_id
from .graph import build_graph
from .render import (
    PHASE_LABELS,
    banner,
    bullets,
    candidate_panel,
    challenges_table,
    claims_group,
    make_console,
    papers_table,
    question_panel,
    sessions_table,
    sources_table,
)
from .runs import RunManager
from .store import Store

COMMANDS = [
    "/help",
    "/workspace",
    "/sources",
    "/papers",
    "/get",
    "/online",
    "/import",
    "/export",
    "/sessions",
    "/decide",
    "/rule",
    "/history",
    "/quit",
]

DECISION_WORDS = {"保留": "kept", "组合": "combined", "淘汰": "rejected"}
RULING_WORDS = {
    "成立": "holds",
    "不成立": "does_not_hold",
    "条件": "conditional",
    "没遇到": "not_encountered",
    "无法判断": "unknown",
}

HELP_ROWS = [
    ("/workspace", "本轮的候选对比、边界探针与 Claim"),
    ("/sources", "本会话的全部来源及其等级"),
    ("/papers <关键词>", "检索论文（arXiv + OpenAlex）"),
    ("/get <编号>", "下载该论文全文并切片为一手来源"),
    ("/online on|off", "开关论文检索；开启后检索词会离开本机"),
    ("/import <路径>", "导入本地资料（txt/md/pdf/源码）"),
    ("/decide <编号> 保留|组合|淘汰", "裁决候选"),
    ("/rule <编号> 成立|不成立|条件|没遇到|无法判断", "裁决边界探针"),
    ("/history", "查看历次轮次的候选数量"),
    ("/export", "导出 summary.md、graph.json、replay.jsonl"),
    ("/sessions", "列出历史会话"),
    ("/quit", "退出（数据保留，--session 可恢复）"),
]

PROMPT_STYLE = Style.from_dict({"prompt": "bold", "": ""})


def model_factory(settings: Settings, profile: ModelProfile):
    """密钥缺失或离线时用离线适配器，让节点走显式降级而不是编造内容。"""

    def factory():
        api_key = get_api_key()
        if settings.offline or not api_key:
            return ScriptedAdapter()
        return OpenAICompatibleAdapter(profile.base_url, api_key, profile.model)

    return factory


def parse_interrupt_answer(raw: str, payload: dict[str, Any]) -> dict[str, Any]:
    """终端输入 → resume body。编号、选项 id 或自由文本都接受。"""
    options = payload.get("options") or []
    stripped = raw.strip()
    if not stripped:
        return {"option_id": "uncertain", "free_text": ""}
    if stripped.isdigit():
        index = int(stripped) - 1
        if 0 <= index < len(options):
            return {"option_id": options[index]["id"], "free_text": ""}
    for option in options:
        if stripped.lower() == str(option["id"]).lower():
            return {"option_id": option["id"], "free_text": ""}
    return {"option_id": None, "free_text": stripped}


def parse_index_command(raw: str, words: dict[str, str]) -> tuple[int, str] | None:
    """解析 `/decide 2 淘汰`，返回 (序号从 0 起, 状态)。"""
    parts = raw.split()
    if len(parts) < 3 or not parts[1].isdigit():
        return None
    status = words.get(parts[2])
    if status is None:
        return None
    return int(parts[1]) - 1, status


class Shell:
    """一个终端会话。事件订阅先于 run 启动，避免漏掉早期事件。"""

    def __init__(
        self,
        manager: RunManager,
        store: Store,
        session_id: str,
        settings: Settings,
        profile: ModelProfile,
    ) -> None:
        self.manager = manager
        self.store = store
        self.session_id = session_id
        self.settings = settings
        self.profile = profile
        self.console = make_console()
        self.run_summary: dict[str, Any] = {}
        self.last_papers: list[Any] = []
        # 非交互终端（管道、CI）下用朴素输入，避免 prompt_toolkit 的回显噪声。
        self.interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self.prompt: PromptSession | None = None
        if self.interactive:
            self.prompt = PromptSession(
                history=FileHistory(str(settings.data_dir / "cli_history")),
                completer=WordCompleter(COMMANDS, sentence=True),
                complete_while_typing=True,
                style=PROMPT_STYLE,
            )

    # ---------------------------------------------------------------- 输出

    def print(self, *args: Any, **kwargs: Any) -> None:
        self.console.print(*args, **kwargs)

    def notice(self, message: str) -> None:
        self.print(Text(message, style="dim"))

    def warn(self, message: str) -> None:
        self.print(Text(message, style="yellow"))

    def error(self, message: str) -> None:
        self.print(Text(message, style="red"))

    def ok(self, message: str) -> None:
        self.print(Text(f"✓ {message}", style="green"))

    # ---------------------------------------------------------------- 事件

    async def run_and_render(self, start) -> dict[str, Any] | None:
        """订阅 → 启动 → 渲染。返回待回答的 interrupt（若有）。"""
        queue = self.manager.runtime(self.session_id).channel.subscribe()
        pending: dict[str, Any] | None = None
        streaming = False
        try:
            await start()
            while True:
                try:
                    event: Event = await asyncio.wait_for(queue.get(), timeout=180.0)
                except asyncio.TimeoutError:
                    self.error("等待模型响应超时")
                    break
                except (KeyboardInterrupt, asyncio.CancelledError):
                    await self.manager.cancel(self.session_id)
                    self.warn("已取消本轮")
                    break

                payload = event.payload or {}
                if event.type == "phase.changed":
                    streaming = self._end_stream(streaming)
                    label = PHASE_LABELS.get(payload.get("phase", ""), payload.get("phase", ""))
                    self.notice(f"· {label}")
                elif event.type == "message.delta":
                    sys.stdout.write(payload.get("delta", ""))
                    sys.stdout.flush()
                    streaming = True
                elif event.type == "message.completed":
                    if not streaming and payload.get("content"):
                        self.print()
                        self.print(payload["content"])
                    streaming = self._end_stream(streaming)
                elif event.type == "source.added":
                    self.notice(f"  ◆ {payload.get('title') or payload.get('locator')}")
                elif event.type == "candidate.created":
                    self.notice(f"  + 候选：{payload.get('text', '')[:60]}")
                elif event.type == "challenge.created":
                    self.notice(f"  + 边界：{payload.get('text', '')[:60]}")
                elif event.type == "interrupt.requested":
                    streaming = self._end_stream(streaming)
                    pending = payload
                    break
                elif event.type == "run.failed":
                    streaming = self._end_stream(streaming)
                    self.error(
                        f"运行失败：{payload.get('code', '')} {payload.get('message', '')}"
                    )
                    break
                elif event.type == "run.cancelled":
                    streaming = self._end_stream(streaming)
                    self.warn("已取消")
                    break
                elif event.type == "run.completed":
                    streaming = self._end_stream(streaming)
                    self.run_summary = payload
                    break
        finally:
            self.manager.runtime(self.session_id).channel.unsubscribe(queue)
        return pending

    @staticmethod
    def _end_stream(streaming: bool) -> bool:
        if streaming:
            sys.stdout.write("\n")
            sys.stdout.flush()
        return False

    # ---------------------------------------------------------------- 展示

    def print_workspace(self) -> None:
        """默认只展示最近一轮，避免多轮结果混在一起。"""
        candidates = self.store.latest_run_domain("candidates", self.session_id)
        challenges = self.store.latest_run_domain("challenges", self.session_id)
        claims = self.store.latest_run_domain("claims", self.session_id)
        sources = self.store.list_domain("evidence_items", self.session_id)

        if candidates:
            total = len(self.store.list_domain("candidates", self.session_id))
            suffix = f"（本轮 {len(candidates)} 个，历史合计 {total} 个）"
            self.print(Text(f"候选对比{suffix}", style="bold cyan"))
            for index, candidate in enumerate(candidates):
                self.print(candidate_panel(index, candidate))
        if challenges:
            self.print(Text("边界探针", style="bold cyan"))
            self.print(challenges_table(challenges))
        if claims:
            self.print(Text("Claim", style="bold cyan"))
            self.print(claims_group(claims))
        if not sources and candidates:
            self.warn("无可定位来源：以上内容为模型已有知识，未核验")

        summary = self.run_summary
        for title, key in (("未知项", "unknowns"), ("下一步", "next_steps")):
            items = summary.get(key) or []
            if items:
                self.print(bullets(title, items))
        degradations = summary.get("degradations") or []
        if degradations:
            self.print(bullets(f"{len(degradations)} 项降级", degradations, style="yellow"))

    def print_sources(self) -> None:
        """已引用的来源与已导入待检索的附件分开展示，避免"导入了却看不到"。"""
        sources = self.store.list_domain("evidence_items", self.session_id)
        attachments = self.store.list_attachments(self.session_id)
        if sources:
            self.print(Text("已被引用的来源", style="bold cyan"))
            self.print(sources_table(sources))
        if attachments:
            chunk_counts: dict[str, int] = {}
            for chunk in self.store.list_chunks(self.session_id):
                chunk_counts[chunk["attachment_id"]] = (
                    chunk_counts.get(chunk["attachment_id"], 0) + 1
                )
            self.print(Text("已导入的资料（下一轮提问时参与检索）", style="bold cyan"))
            for attachment in attachments:
                count = chunk_counts.get(attachment["attachment_id"], 0)
                self.print(
                    Text(f"  ◆ {attachment['filename']}  {count} 个片段", style="dim")
                )
        if not sources and not attachments:
            self.warn("本会话没有资料。用 /import 导入本地文件，或 /papers 检索论文。")
        elif not sources:
            self.notice("附件尚未被引用：下一轮提问时检索命中后会标为一手来源。")

    def print_history(self) -> None:
        """按轮次列出候选数量，说明哪些属于同一次对比。"""
        rows: dict[str, int] = {}
        with self.store._lock:  # noqa: SLF001 - 只读统计
            for row in self.store._conn.execute(
                "SELECT COALESCE(run_id, '(早期数据)') AS run_id, COUNT(*) AS n"
                " FROM candidates WHERE session_id = ? GROUP BY run_id ORDER BY MIN(rowid)",
                (self.session_id,),
            ).fetchall():
                rows[row["run_id"]] = row["n"]
        if not rows:
            self.notice("本会话还没有候选。")
            return
        for run_id, count in rows.items():
            self.print(Text(f"  {run_id}：{count} 个候选", style="dim"))

    # ---------------------------------------------------------------- 论文

    async def search_papers(self, raw: str) -> None:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            self.warn("用法：/papers retrieval augmented generation")
            return
        if not self.manager.online_retrieval:
            self.warn("论文检索未开启。先执行 /online on（检索词会发往 arXiv / OpenAlex）。")
            return
        query = parts[1].strip()
        from .papers import search_with_outcome

        self.notice(f"检索中：{query}")
        outcome = await asyncio.to_thread(search_with_outcome, query, 8)
        for name, message in outcome.errors.items():
            self.warn(f"{name} 未返回结果：{message}")
        if not outcome.refs:
            self.error("没有检索到论文。")
            return
        self.last_papers = outcome.refs
        self.print(papers_table(outcome.refs))
        self.notice("用 /get <编号> 下载全文并作为一手来源导入")

    async def fetch_paper(self, raw: str) -> None:
        parts = raw.split()
        if len(parts) < 2 or not parts[1].isdigit():
            self.warn("用法：/get 2")
            return
        index = int(parts[1]) - 1
        if not 0 <= index < len(self.last_papers):
            self.warn("请先用 /papers 检索，再按编号下载。")
            return
        ref = self.last_papers[index]
        from .ingest import IngestError, store_attachment
        from .papers import PaperError, download_pdf

        self.notice(f"下载中：{ref.title[:60]}")
        try:
            data = await asyncio.to_thread(download_pdf, ref)
            record, chunks = store_attachment(
                session_id=self.session_id,
                filename=ref.filename,
                data=data,
                attachments_dir=Path(self.store.db_path).parent / "attachments",
            )
        except (PaperError, IngestError) as error:
            self.error(f"失败：{error}")
            if ref.landing_url:
                self.notice(f"可手动打开：{ref.landing_url}")
            return
        self.store.add_attachment(record)
        self.store.add_chunks(record["attachment_id"], chunks)
        self.ok(
            f"已导入 {ref.locator}，{len(chunks)} 个片段，"
            f"{len(data) // 1024} KB（后续检索命中后标为一手来源）"
        )

    def toggle_online(self, raw: str) -> None:
        parts = raw.split()
        if len(parts) < 2 or parts[1] not in ("on", "off"):
            state = "开启" if self.manager.online_retrieval else "关闭"
            self.notice(f"论文检索当前{state}。用法：/online on|off")
            return
        self.manager.online_retrieval = parts[1] == "on"
        if self.manager.online_retrieval:
            self.warn("论文检索已开启：检索词会发往 arXiv / OpenAlex，本地文件不会被上传。")
        else:
            self.ok("论文检索已关闭")

    # ---------------------------------------------------------------- 裁决

    def decide_candidate(self, raw: str) -> None:
        parsed = parse_index_command(raw, DECISION_WORDS)
        if parsed is None:
            self.warn("用法：/decide 2 保留|组合|淘汰")
            return
        index, status = parsed
        candidates = self.store.latest_run_domain("candidates", self.session_id)
        if not 0 <= index < len(candidates):
            self.warn(f"本轮没有第 {index + 1} 个候选")
            return
        candidate = candidates[index]
        candidate["status"] = status
        self.store.upsert_domain(
            "candidates", self.session_id, candidate["id"], candidate
        )
        self.ok(f"候选 {index + 1} → {status}")

    def rule_challenge(self, raw: str) -> None:
        parsed = parse_index_command(raw, RULING_WORDS)
        if parsed is None:
            self.warn("用法：/rule 1 成立|不成立|条件|没遇到|无法判断")
            return
        index, status = parsed
        challenges = self.store.latest_run_domain("challenges", self.session_id)
        if not 0 <= index < len(challenges):
            self.warn(f"本轮没有第 {index + 1} 条边界探针")
            return
        challenge = challenges[index]
        challenge["status"] = status  # 用户裁决与模型提议分别标识
        self.store.upsert_domain(
            "challenges", self.session_id, challenge["id"], challenge
        )
        self.ok(f"边界 {index + 1} → {status}")

    def import_file(self, raw: str) -> None:
        from .ingest import IngestError, store_attachment

        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            self.warn("用法：/import ~/notes.md")
            return
        path = Path(parts[1].strip().strip('"').strip("'")).expanduser()
        if not path.is_file():
            self.warn(f"找不到文件：{path}")
            return
        try:
            record, chunks = store_attachment(
                session_id=self.session_id,
                filename=path.name,
                data=path.read_bytes(),
                attachments_dir=Path(self.store.db_path).parent / "attachments",
            )
        except IngestError as error:
            self.error(f"导入失败：{error}")
            return
        self.store.add_attachment(record)
        self.store.add_chunks(record["attachment_id"], chunks)
        self.ok(f"已导入 {path.name}，{len(chunks)} 个片段")

    def export(self) -> None:
        from . import export as export_service

        files = export_service.export_session(
            self.store, self.session_id, Path(self.store.db_path).parent / "exports"
        )
        for filepath in files:
            self.ok(filepath)

    def print_help(self) -> None:
        from rich.table import Table

        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column(style="bold", overflow="fold")
        table.add_column(overflow="fold")
        for command, description in HELP_ROWS:
            table.add_row(command, description)
        self.print(table)
        self.notice("直接输入文字发送消息；出现问题时输入编号或直接写文字回答")

    # ---------------------------------------------------------------- 主循环

    async def ask(self, prompt: str) -> str:
        try:
            if self.prompt is not None:
                return await self.prompt.prompt_async(prompt)
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                return "/quit"
            self.print(Text(f"{prompt}{line.rstrip()}", style="dim"))
            return line.rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            return "/quit"

    async def answer_pending(self, pending: dict[str, Any]) -> dict[str, Any] | None:
        self.print(question_panel(pending))
        raw = await self.ask("答> ")
        if raw.strip().lower() in ("/quit", "/exit"):
            return None
        body = parse_interrupt_answer(raw, pending) | {
            "question_id": pending.get("question_id"),
            "learning_check_id": pending.get("learning_check_id"),
        }
        return await self.run_and_render(
            lambda: self.manager.resume_run(self.session_id, body)
        )

    async def handle_command(self, stripped: str) -> bool:
        """返回 False 表示要退出。"""
        lowered = stripped.lower()
        if lowered in ("/quit", "/exit"):
            return False
        if lowered == "/help":
            self.print_help()
        elif lowered == "/workspace":
            self.print_workspace()
        elif lowered == "/sources":
            self.print_sources()
        elif lowered == "/history":
            self.print_history()
        elif lowered == "/export":
            self.export()
        elif lowered == "/sessions":
            self.print(sessions_table(self.store.list_sessions(), self.session_id))
        elif lowered.startswith("/papers"):
            await self.search_papers(stripped)
        elif lowered.startswith("/get"):
            await self.fetch_paper(stripped)
        elif lowered.startswith("/online"):
            self.toggle_online(stripped)
        elif lowered.startswith("/decide"):
            self.decide_candidate(stripped)
        elif lowered.startswith("/rule"):
            self.rule_challenge(stripped)
        elif lowered.startswith("/import"):
            self.import_file(stripped)
        else:
            self.warn("未知命令，/help 查看可用命令")
        return True

    async def loop(self, first_message: str = "") -> None:
        self.print(
            banner(
                self.profile.model,
                self.profile.base_url,
                str(self.settings.data_dir),
                self.manager.online_retrieval,
                bool(get_api_key()) and not self.settings.offline,
            )
        )
        self.notice(f"会话 {self.session_id} · /help 查看命令 · Ctrl+C 取消当轮 · /quit 退出")

        pending = await self.manager.pending_interrupt(self.session_id)
        message = first_message

        while True:
            if pending:
                pending = await self.answer_pending(pending)
                if pending is None:
                    self.print_workspace()
                continue

            if not message:
                raw = await self.ask("你> ")
                stripped = raw.strip()
                if not stripped:
                    continue
                if stripped.startswith("/"):
                    if not await self.handle_command(stripped):
                        return
                    continue
                message = stripped

            self.store.add_message(new_id("msg"), self.session_id, "user", message)
            text = message
            message = ""
            pending = await self.run_and_render(
                lambda: self.manager.start_run(self.session_id, text)
            )
            if pending is None:
                self.print_workspace()


async def async_main(argv: list[str] | None = None) -> int:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .api import CHECKPOINTED_MODELS

    parser = argparse.ArgumentParser(prog="kel", description="知识激发智能体 CLI")
    parser.add_argument("prompt", nargs="*", help="首条消息，留空则进入交互输入")
    parser.add_argument("--session", "-s", help="恢复指定会话")
    parser.add_argument("--list", "-l", action="store_true", help="列出历史会话")
    parser.add_argument("--data-dir", help="数据目录")
    parser.add_argument("--offline", action="store_true", help="不调用模型服务")
    parser.add_argument(
        "--online", action="store_true", help="允许论文检索（检索词会离开本机）"
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.data_dir:
        settings.data_dir = Path(args.data_dir).expanduser()
    settings.offline = settings.offline or args.offline
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    store = Store(settings.db_path)
    saved = store.get_model_profile()
    profile = ModelProfile(**saved) if saved else ModelProfile()
    console = make_console()

    if args.list:
        sessions = store.list_sessions()
        if not sessions:
            console.print("暂无会话。")
        else:
            console.print(sessions_table(sessions))
        store.close()
        return 0

    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[("kel.models", name) for name in CHECKPOINTED_MODELS]
    )
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
        saver.serde = serde
        manager = RunManager(
            store,
            build_graph(saver),
            model_factory(settings, profile),
            online_retrieval=args.online and not settings.offline,
        )

        session_id = args.session
        if session_id and not store.get_session(session_id):
            console.print(f"[red]会话不存在：{session_id}[/red]")
            store.close()
            return 1
        if not session_id:
            session_id = new_id("sess")
            store.create_session(session_id)

        shell = Shell(manager, store, session_id, settings, profile)
        await shell.loop(" ".join(args.prompt).strip())

        # 等后台 checkpoint 写入结束再关闭连接
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task() and not task.done():
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass

    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(async_main(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
