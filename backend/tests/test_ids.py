"""ID 生成：持久化 ID 必须跨进程唯一，否则多次运行 CLI 会撞主键或覆盖数据。"""

from __future__ import annotations

import subprocess
import sys

from kel.events import new_id


def test_ids_are_ordered_within_process():
    a = new_id("cand")
    b = new_id("cand")
    assert a != b
    assert a.startswith("cand_") and b.startswith("cand_")


def test_ids_differ_across_processes():
    """两个进程各自从计数器 1 开始，若无进程前缀就会生成相同的 sess_000001。"""
    code = "from kel.events import new_id; print(new_id('sess'))"
    first = subprocess.check_output([sys.executable, "-c", code], cwd="src").decode().strip()
    second = subprocess.check_output([sys.executable, "-c", code], cwd="src").decode().strip()
    assert first != second, "跨进程 ID 必须不同，否则会撞 sessions.session_id 主键"
