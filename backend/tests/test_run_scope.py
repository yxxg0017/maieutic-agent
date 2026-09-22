"""按轮次（run）分组的领域对象查询。

多轮对话会产生多批候选；混在一起展示会破坏"同一次对比"的语义。
"""

from __future__ import annotations

from kel.store import Store


def _candidate(obj_id: str, text: str = "c") -> dict:
    return {"id": obj_id, "text": text, "status": "generated"}


def test_migration_adds_run_id_to_challenges_and_claims(store: Store):
    columns = {
        table: {
            row[1]
            for row in store._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for table in ("candidates", "challenges", "claims")
    }
    for table in ("candidates", "challenges", "claims"):
        assert "run_id" in columns[table], table


def test_migration_from_v1_keeps_rows(settings):
    """模拟从上一个正式版本升级：v1 数据必须保留。"""
    import sqlite3

    from kel.store import SCHEMA

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path))
    conn.executescript(SCHEMA[0][1])
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00Z')")
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO sessions(session_id, created_at, updated_at) VALUES ('s1', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO claims(id, session_id, data, created_at) VALUES ('c_old', 's1', '{}', ?)",
        (now,),
    )
    conn.commit()
    conn.close()

    store = Store(settings.db_path)  # 触发 v2 迁移
    assert store.get_session("s1") is not None
    assert len(store.list_domain("claims", "s1")) == 1
    assert store.migrate() == SCHEMA[-1][0]


def test_latest_run_scope_hides_earlier_rounds(store: Store):
    store.create_session("s1")
    store.create_run("run_1", "s1", "s1")
    store.create_run("run_2", "s1", "s1")
    for index in range(3):
        store.upsert_domain(
            "candidates", "s1", f"c1_{index}", _candidate(f"c1_{index}", "第一轮"), "run_1"
        )
    for index in range(2):
        store.upsert_domain(
            "candidates", "s1", f"c2_{index}", _candidate(f"c2_{index}", "第二轮"), "run_2"
        )

    latest = store.latest_run_domain("candidates", "s1")
    assert len(latest) == 2
    assert {c["text"] for c in latest} == {"第二轮"}
    assert len(store.list_domain("candidates", "s1")) == 5
    assert len(store.list_domain_by_run("candidates", "s1", "run_1")) == 3


def test_challenges_and_claims_are_run_scoped(store: Store):
    store.create_session("s1")
    store.create_run("run_1", "s1", "s1")
    store.create_run("run_2", "s1", "s1")
    store.upsert_domain("challenges", "s1", "ch1", {"id": "ch1", "text": "旧"}, "run_1")
    store.upsert_domain("challenges", "s1", "ch2", {"id": "ch2", "text": "新"}, "run_2")
    store.upsert_domain("claims", "s1", "cl1", {"id": "cl1", "text": "旧"}, "run_1")
    store.upsert_domain("claims", "s1", "cl2", {"id": "cl2", "text": "新"}, "run_2")

    assert [c["text"] for c in store.latest_run_domain("challenges", "s1")] == ["新"]
    assert [c["text"] for c in store.latest_run_domain("claims", "s1")] == ["新"]


def test_legacy_rows_without_run_id_still_visible(store: Store):
    """v1 遗留数据没有 run_id，不能因为分组而消失。"""
    store.create_session("s1")
    store.upsert_domain("candidates", "s1", "c_old", _candidate("c_old", "遗留"))
    assert [c["text"] for c in store.latest_run_domain("candidates", "s1")] == ["遗留"]


def test_evidence_items_are_not_run_scoped(store: Store):
    """来源属于整个会话：导入一次后各轮都该看得到。"""
    store.create_session("s1")
    store.upsert_domain(
        "evidence_items", "s1", "ev1", {"id": "ev1", "locator": "attachment:a.md:#0"}
    )
    assert len(store.latest_run_domain("evidence_items", "s1")) == 1
