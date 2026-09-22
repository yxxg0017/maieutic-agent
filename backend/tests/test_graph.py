"""图行为：重启恢复、降级路径与幂等重放。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from conftest import DEEP_FRAME, scripted
from kel.adapters import ScriptedAdapter
from kel.api import create_app
from kel.store import Store


def _wait(client: TestClient, session_id: str, predicate, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        payload = client.get(f"/v1/sessions/{session_id}").json()
        if predicate(payload):
            return payload
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_pending_interrupt_survives_restart(settings, store: Store):
    adapter = scripted({"task_frame": DEEP_FRAME})
    app = create_app(settings, store, model_factory=lambda: adapter)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = f"Bearer {settings.session_token}"
        session_id = client.post("/v1/sessions", json={"title": "t"}).json()["session_id"]
        client.post(f"/v1/sessions/{session_id}/messages", json={"content": "比较方案"})
        payload = _wait(client, session_id, lambda p: p["pending_interrupt"] is not None)
        question_id = payload["pending_interrupt"]["question_id"]
        candidate_count_before = len(payload["candidates"])
    store.close()

    # 模拟应用重启：新的 Store、新的 app，复用同一 checkpoint 文件
    restarted_store = Store(settings.db_path)
    restarted = create_app(settings, restarted_store, model_factory=lambda: adapter)
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = f"Bearer {settings.session_token}"
        payload = client.get(f"/v1/sessions/{session_id}").json()
        assert payload["pending_interrupt"]["question_id"] == question_id

        resumed = client.post(
            f"/v1/sessions/{session_id}/resume",
            json={"question_id": question_id, "option_id": "can_write"},
        )
        assert resumed.status_code == 200
        payload = _wait(
            client,
            session_id,
            lambda p: len(p["candidates"]) > candidate_count_before, timeout=30,
        )
        # 恢复不得重复运行前置节点：来源与候选各只出现一次
        assert len(payload["candidates"]) == 2
        locators = [s["locator"] for s in payload["sources"]]
        assert len(locators) == len(set(locators))


def test_model_unavailable_degrades_without_fabricating(settings, store: Store):
    empty = ScriptedAdapter({})  # 无任何预设响应，等价于模型不可用
    app = create_app(settings, store, model_factory=lambda: empty)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = f"Bearer {settings.session_token}"
        session_id = client.post("/v1/sessions", json={}).json()["session_id"]
        client.post(f"/v1/sessions/{session_id}/messages", json={"content": "为什么要比较这两种架构"})
        payload = _wait(client, session_id, lambda p: p["phase"] == "completed")
        assert payload["claims"] == []  # 不伪造 Claim
        assert payload["sources"] == []  # 不伪造引用
        events = client.get(f"/v1/sessions/{session_id}/events?replay=true").text
        assert "run.completed" in events
        assert "降级" in events or "未核验" in events


def test_attachment_chunks_become_primary_evidence(settings, store: Store):
    adapter = scripted({"task_frame": DEEP_FRAME})
    app = create_app(settings, store, model_factory=lambda: adapter)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = f"Bearer {settings.session_token}"
        session_id = client.post("/v1/sessions", json={}).json()["session_id"]
        client.post(
            f"/v1/sessions/{session_id}/attachments",
            files={"file": ("notes.md", "生成器 惰性求值 说明".encode(), "text/markdown")},
        )
        client.post(f"/v1/sessions/{session_id}/messages", json={"content": "生成器 惰性求值"})
        payload = _wait(client, session_id, lambda p: p["pending_interrupt"] is not None)
        client.post(
            f"/v1/sessions/{session_id}/resume",
            json={
                "question_id": payload["pending_interrupt"]["question_id"],
                "option_id": "can_write",
            },
        )
        payload = _wait(client, session_id, lambda p: len(p["sources"]) > 0, timeout=30)
        assert payload["sources"][0]["source_tier"] == "primary"
        assert payload["sources"][0]["locator"].startswith("attachment:notes.md")
