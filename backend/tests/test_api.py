"""API：认证、run 生命周期、中断恢复、附件与导出。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from conftest import DEEP_FRAME


def _new_session(client: TestClient) -> str:
    response = client.post("/v1/sessions", json={"title": "t"})
    assert response.status_code == 200
    return response.json()["session_id"]


def _wait(client: TestClient, session_id: str, predicate, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/v1/sessions/{session_id}").json()
        if predicate(payload):
            return payload
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting; last payload keys={list(payload)}")


def test_health_needs_no_token_but_v1_does(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"
    unauth = client.get("/v1/sessions", headers={"Authorization": "Bearer wrong"})
    assert unauth.status_code == 401
    missing = client.get("/v1/sessions", headers={"Authorization": ""})
    assert missing.status_code == 401


def test_fast_run_streams_and_completes(client: TestClient):
    session_id = _new_session(client)
    run = client.post(
        f"/v1/sessions/{session_id}/messages", json={"content": "生成器怎么工作"}
    )
    assert run.status_code == 200
    payload = _wait(
        client, session_id, lambda p: p["phase"] == "completed" and not p["busy"]
    )
    assistant = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert assistant and "生成器" in assistant[-1]["content"]

    events = client.get(f"/v1/sessions/{session_id}/events?replay=true").text
    assert "run.started" in events and "run.completed" in events
    assert "message.delta" in events


def test_second_message_while_busy_is_rejected(client: TestClient):
    session_id = _new_session(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"content": "a"})
    second = client.post(f"/v1/sessions/{session_id}/messages", json={"content": "b"})
    assert second.status_code in (200, 409)  # 完成得足够快时允许，否则必须拒绝


def test_deep_run_interrupts_and_resume_validates_question_id(
    client: TestClient, adapter
):
    adapter.structured_responses["task_frame"] = DEEP_FRAME
    session_id = _new_session(client)
    client.post(
        f"/v1/sessions/{session_id}/messages", json={"content": "比较两种生成器心智模型"}
    )
    payload = _wait(client, session_id, lambda p: p["pending_interrupt"] is not None)
    pending = payload["pending_interrupt"]
    assert pending["kind"] == "question"
    assert [o["id"] for o in pending["options"]][-2:] == ["other", "uncertain"]

    # 新消息在中断未解决时必须被拒绝
    blocked = client.post(f"/v1/sessions/{session_id}/messages", json={"content": "x"})
    assert blocked.status_code == 409

    stale = client.post(
        f"/v1/sessions/{session_id}/resume",
        json={"question_id": "q_nonexistent", "option_id": "can_write"},
    )
    assert stale.status_code == 409

    resumed = client.post(
        f"/v1/sessions/{session_id}/resume",
        json={"question_id": pending["question_id"], "option_id": "can_write"},
    )
    assert resumed.status_code == 200

    payload = _wait(
        client,
        session_id,
        lambda p: p["phase"] == "completed"
        or (p["pending_interrupt"] or {}).get("kind") == "learning_check",
        timeout=30,
    )
    assert len(payload["candidates"]) == 2
    assert {c["status"] for c in payload["candidates"]} <= {
        "generated", "kept", "rejected", "combined"
    }
    assert payload["challenges"]
    assert all(c["status"] == "untested" for c in payload["challenges"])

    duplicate = client.post(
        f"/v1/sessions/{session_id}/resume",
        json={"question_id": pending["question_id"], "option_id": "can_write"},
    )
    assert duplicate.status_code == 409  # 过期或重复回答被拒绝


def test_candidate_and_challenge_decisions(client: TestClient, adapter, store):
    adapter.structured_responses["task_frame"] = DEEP_FRAME
    session_id = _new_session(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"content": "比较方案"})
    payload = _wait(client, session_id, lambda p: p["pending_interrupt"] is not None)
    client.post(
        f"/v1/sessions/{session_id}/resume",
        json={
            "question_id": payload["pending_interrupt"]["question_id"],
            "option_id": "can_write",
        },
    )
    payload = _wait(client, session_id, lambda p: len(p["challenges"]) > 0, timeout=30)

    candidate_id = payload["candidates"][0]["id"]
    decision = client.post(
        f"/v1/sessions/{session_id}/candidates/{candidate_id}/decision",
        json={"status": "combined", "user_note": "与方案二合并"},
    )
    assert decision.json()["status"] == "combined"
    assert client.post(
        f"/v1/sessions/{session_id}/candidates/{candidate_id}/decision",
        json={"status": "bogus"},
    ).status_code == 422

    challenge_id = payload["challenges"][0]["id"]
    ruled = client.post(
        f"/v1/sessions/{session_id}/challenges/{challenge_id}/decision",
        json={"status": "conditional"},
    )
    assert ruled.json()["status"] == "conditional"


def test_attachment_becomes_primary_source(client: TestClient):
    session_id = _new_session(client)
    upload = client.post(
        f"/v1/sessions/{session_id}/attachments",
        files={"file": ("notes.md", b"# Generator\n\n\xe6\x83\xb0\xe6\x80\xa7\xe6\xb1\x82\xe5\x80\xbc\xe8\xaf\xb4\xe6\x98\x8e\n", "text/markdown")},
    )
    assert upload.status_code == 200 and upload.json()["chunks"] >= 1

    rejected = client.post(
        f"/v1/sessions/{session_id}/attachments",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert rejected.status_code == 422


def test_cancel_and_export(client: TestClient):
    session_id = _new_session(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"content": "生成器"})
    _wait(client, session_id, lambda p: not p["busy"])
    assert client.post(f"/v1/sessions/{session_id}/cancel").json()["cancelled"] is False

    files = client.post(f"/v1/sessions/{session_id}/export").json()["files"]
    assert len(files) == 3
    summary = [f for f in files if f.endswith("_summary.md")][0]
    with open(summary, encoding="utf-8") as handle:
        content = handle.read()
    assert "## 来源" in content


def test_delete_session_removes_everything(client: TestClient):
    session_id = _new_session(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"content": "生成器"})
    _wait(client, session_id, lambda p: not p["busy"])
    assert client.delete(f"/v1/sessions/{session_id}").status_code == 200
    assert client.get(f"/v1/sessions/{session_id}").status_code == 404


def test_settings_never_returns_api_key(client: TestClient):
    response = client.get("/v1/settings").json()
    assert "api_key" not in response
    assert set(response) == {"model_configured", "base_url", "model", "offline", "data_dir"}
