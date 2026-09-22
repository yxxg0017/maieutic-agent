"""存储层：迁移、事件唯一性与断点续传。"""

from __future__ import annotations

from kel.store import SCHEMA, Store


def _event(run_id: str, sequence: int, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or f"evt_{run_id}_{sequence}",
        "run_id": run_id,
        "session_id": "sess_1",
        "sequence": sequence,
        "type": "phase.changed",
        "timestamp": "2026-09-22T00:00:00.000Z",
        "payload": {"phase": "task_frame"},
    }


def test_migrate_is_idempotent(store: Store):
    assert store.migrate() == SCHEMA[-1][0]
    assert store.migrate() == SCHEMA[-1][0]


def test_migrate_preserves_existing_data(settings):
    first = Store(settings.db_path)
    first.create_session("sess_1")
    first.close()
    second = Store(settings.db_path)  # 重新打开不得重建用户数据库
    assert second.get_session("sess_1") is not None


def test_duplicate_event_is_rejected(store: Store):
    store.create_session("sess_1")
    store.create_run("run_1", "sess_1", "sess_1")
    assert store.append_event(_event("run_1", 1)) is True
    assert store.append_event(_event("run_1", 1)) is False
    assert store.append_event(_event("run_1", 1, event_id="evt_other")) is False
    assert store.max_sequence("run_1") == 1


def test_events_after_resumes_from_last_event_id(store: Store):
    store.create_session("sess_1")
    store.create_run("run_1", "sess_1", "sess_1")
    for sequence in (1, 2, 3):
        store.append_event(_event("run_1", sequence))
    rest = store.events_after("sess_1", "evt_run_1_2")
    assert [e["sequence"] for e in rest] == [3]
    assert len(store.events_after("sess_1", None)) == 3
    assert len(store.events_after("sess_1", "unknown_id")) == 3


def test_delete_session_cascades_and_reports_orphan_files(store: Store, tmp_path):
    store.create_session("sess_1")
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    store.add_attachment(
        {
            "attachment_id": "att_1",
            "session_id": "sess_1",
            "filename": "a.txt",
            "mime": "text/plain",
            "size": 1,
            "sha256": "abc",
            "stored_path": str(path),
        }
    )
    orphans = store.delete_session("sess_1")
    assert orphans == [str(path)]
    assert store.get_session("sess_1") is None


def test_domain_upsert_is_idempotent(store: Store):
    store.create_session("sess_1")
    payload = {"id": "cand_1", "text": "a", "status": "generated"}
    store.upsert_domain("candidates", "sess_1", "cand_1", payload)
    payload["status"] = "kept"
    store.upsert_domain("candidates", "sess_1", "cand_1", payload)
    rows = store.list_domain("candidates", "sess_1")
    assert len(rows) == 1 and rows[0]["status"] == "kept"
