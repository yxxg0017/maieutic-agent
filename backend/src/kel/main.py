"""sidecar 入口。绑定端口 0 后在 stdout 输出一行 ready 事件（不含 token）。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import threading
import time

import uvicorn

from .api import create_app
from .config import Settings
from .security import new_session_token
from .store import Store


def _bind_loopback(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))  # 仅回环，禁止 0.0.0.0
    sock.listen(128)
    return sock


def _watch_parent(parent_pid: int) -> None:
    """父进程消失后退出，避免残留 sidecar。"""

    def loop() -> None:
        while True:
            time.sleep(2)
            try:
                os.kill(parent_pid, 0)
            except OSError:
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kel-sidecar")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--log-level", default=None)
    parser.add_argument("--parent-pid", type=int, default=None)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.data_dir:
        settings.data_dir = __import__("pathlib").Path(args.data_dir).expanduser()
    if args.log_level:
        settings.log_level = args.log_level
    if args.port is not None:
        settings.port = args.port
    if not settings.session_token:
        settings.session_token = new_session_token()

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.db_path)  # 启动时完成迁移

    sock = _bind_loopback(settings.port)
    actual_port = sock.getsockname()[1]
    if args.parent_pid:
        _watch_parent(args.parent_pid)

    app = create_app(settings, store)
    config = uvicorn.Config(
        app,
        log_level=settings.log_level,
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)

    async def run() -> None:
        ready = {
            "event": "ready",
            "port": actual_port,
            "pid": os.getpid(),
            "data_dir": str(settings.data_dir),
            "schema_version": "1",
        }
        task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started and not task.done():
            await asyncio.sleep(0.02)
        print(json.dumps(ready), flush=True)  # 不输出 token
        await task

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
