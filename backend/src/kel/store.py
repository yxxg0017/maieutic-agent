"""SQLite 持久化与顺序迁移。

sidecar 是唯一写入方；前端不得直接打开数据库。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE sessions (
            session_id   TEXT PRIMARY KEY,
            title        TEXT NOT NULL DEFAULT '',
            topic        TEXT NOT NULL DEFAULT '',
            task_type    TEXT NOT NULL DEFAULT 'learn',
            depth        TEXT NOT NULL DEFAULT 'fast',
            phase        TEXT NOT NULL DEFAULT 'task_frame',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE TABLE runs (
            run_id        TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            thread_id     TEXT NOT NULL,
            checkpoint_id TEXT,
            status        TEXT NOT NULL DEFAULT 'running',
            stop_reason   TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE events (
            event_id   TEXT PRIMARY KEY,
            run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            sequence   INTEGER NOT NULL,
            type       TEXT NOT NULL,
            timestamp  TEXT NOT NULL,
            payload    TEXT NOT NULL,
            UNIQUE (run_id, sequence)
        );

        CREATE TABLE messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            run_id     TEXT,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE evidence_items (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE candidates (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            run_id     TEXT,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE claims (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE challenges (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE hypothesis_sets (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            version    INTEGER NOT NULL,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE questions (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE likelihoods (
            question_id   TEXT NOT NULL,
            hypothesis_id TEXT NOT NULL,
            session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            data          TEXT NOT NULL,
            PRIMARY KEY (question_id, hypothesis_id)
        );

        CREATE TABLE entropy_records (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            run_id     TEXT,
            data       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE attachments (
            attachment_id TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            filename      TEXT NOT NULL,
            mime          TEXT NOT NULL,
            size          INTEGER NOT NULL,
            sha256        TEXT NOT NULL,
            stored_path   TEXT NOT NULL,
            imported_at   TEXT NOT NULL
        );

        CREATE TABLE attachment_chunks (
            chunk_id      TEXT PRIMARY KEY,
            attachment_id TEXT NOT NULL REFERENCES attachments(attachment_id) ON DELETE CASCADE,
            ordinal       INTEGER NOT NULL,
            locator       TEXT NOT NULL,
            text          TEXT NOT NULL
        );

        CREATE TABLE model_profiles (
            profile_id  TEXT PRIMARY KEY,
            provider    TEXT NOT NULL,
            base_url    TEXT NOT NULL,
            model       TEXT NOT NULL,
            is_default  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX idx_events_session ON events(session_id, sequence);
        CREATE INDEX idx_messages_session ON messages(session_id, created_at);
        CREATE INDEX idx_chunks_attachment ON attachment_chunks(attachment_id, ordinal);
        """,
    ),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class Store:
    """线程安全的轻量数据访问层。写操作使用短事务。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    # ---------------------------------------------------------------- 迁移

    def migrate(self) -> int:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            current = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations"
            ).fetchone()["v"]
            for version, ddl in SCHEMA:
                if version <= current:
                    continue
                self._conn.executescript(ddl)
                self._conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, _now()),
                )
                current = version
        return current

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- 会话

    def create_session(self, session_id: str, title: str = "") -> dict[str, Any]:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions(session_id, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        return self.get_session(session_id)  # type: ignore[return-value]

    def update_session(self, session_id: str, **fields: Any) -> None:
        allowed = {"title", "topic", "task_type", "depth", "phase"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return
        assignments = ", ".join(f"{k} = ?" for k in sets)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE sessions SET {assignments}, updated_at = ? WHERE session_id = ?",
                (*sets.values(), _now(), session_id),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> list[str]:
        """删除会话，返回不再被引用、可以清理的附件存储路径。"""
        with self._lock, self._conn:
            paths = [
                r["stored_path"]
                for r in self._conn.execute(
                    "SELECT stored_path FROM attachments WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
            ]
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            still_used: set[str] = set()
            if paths:
                placeholders = ",".join("?" * len(paths))
                still_used = {
                    r["stored_path"]
                    for r in self._conn.execute(
                        "SELECT stored_path FROM attachments"
                        f" WHERE stored_path IN ({placeholders})",
                        tuple(paths),
                    ).fetchall()
                }
        return [p for p in paths if p not in still_used]

    # ---------------------------------------------------------------- run

    def create_run(self, run_id: str, session_id: str, thread_id: str) -> None:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runs(run_id, session_id, thread_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (run_id, session_id, thread_id, now, now),
            )

    def finish_run(
        self, run_id: str, status: str, stop_reason: str | None = None,
        checkpoint_id: str | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE runs SET status = ?, stop_reason = ?,"
                " checkpoint_id = COALESCE(?, checkpoint_id), updated_at = ?"
                " WHERE run_id = ?",
                (status, stop_reason, checkpoint_id, _now(), run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def latest_run(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    # ---------------------------------------------------------------- 事件

    def append_event(self, event: dict[str, Any]) -> bool:
        """幂等写入。重复 event_id 或 (run_id, sequence) 返回 False。"""
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO events(event_id, run_id, session_id, sequence, type,"
                    " timestamp, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event["event_id"],
                        event["run_id"],
                        event["session_id"],
                        event["sequence"],
                        event["type"],
                        event["timestamp"],
                        json.dumps(event["payload"], ensure_ascii=False),
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def events_after(
        self, session_id: str, last_event_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY rowid", (session_id,)
            ).fetchall()
        events = [self._event_row(r) for r in rows]
        if last_event_id is None:
            return events
        for index, event in enumerate(events):
            if event["event_id"] == last_event_id:
                return events[index + 1 :]
        return events

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        data["schema_version"] = "1"
        return data

    def max_sequence(self, run_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS s FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["s"])

    # ---------------------------------------------------------------- 消息

    def add_message(
        self, message_id: str, session_id: str, role: str, content: str,
        run_id: str | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO messages(message_id, session_id, run_id, role,"
                " content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, session_id, run_id, role, content, _now()),
            )

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, rowid",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------- 领域对象（幂等 upsert）

    def upsert_domain(
        self, table: str, session_id: str, obj_id: str, data: dict[str, Any],
        run_id: str | None = None,
    ) -> None:
        if table not in {
            "evidence_items", "candidates", "claims", "challenges", "questions",
        }:
            raise ValueError(f"unsupported table: {table}")
        payload = json.dumps(data, ensure_ascii=False)
        columns = "(id, session_id, data, created_at)"
        values: tuple[Any, ...] = (obj_id, session_id, payload, _now())
        if table == "candidates":
            columns = "(id, session_id, run_id, data, created_at)"
            values = (obj_id, session_id, run_id, payload, _now())
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT INTO {table} {columns} VALUES ({','.join('?' * len(values))})"
                " ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                values,
            )

    def list_domain(self, table: str, session_id: str) -> list[dict[str, Any]]:
        if table not in {
            "evidence_items", "candidates", "claims", "challenges", "questions",
        }:
            raise ValueError(f"unsupported table: {table}")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT data FROM {table} WHERE session_id = ? ORDER BY rowid",
                (session_id,),
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def save_hypothesis_set(self, session_id: str, data: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO hypothesis_sets(id, session_id, version, data, created_at)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
                " data = excluded.data, version = excluded.version",
                (
                    data["id"],
                    session_id,
                    data.get("version", 1),
                    json.dumps(data, ensure_ascii=False),
                    _now(),
                ),
            )

    def save_likelihoods(self, session_id: str, rows: Iterable[dict[str, Any]]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO likelihoods(question_id, hypothesis_id, session_id, data)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(question_id, hypothesis_id)"
                " DO UPDATE SET data = excluded.data",
                [
                    (
                        r["question_id"],
                        r["hypothesis_id"],
                        session_id,
                        json.dumps(r, ensure_ascii=False),
                    )
                    for r in rows
                ],
            )

    def add_entropy_record(
        self, session_id: str, run_id: str | None, data: dict[str, Any]
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO entropy_records(session_id, run_id, data, created_at)"
                " VALUES (?, ?, ?, ?)",
                (session_id, run_id, json.dumps(data, ensure_ascii=False), _now()),
            )

    def list_entropy_records(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM entropy_records WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # ---------------------------------------------------------------- 附件

    def add_attachment(self, record: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO attachments(attachment_id, session_id, filename, mime,"
                " size, sha256, stored_path, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["attachment_id"],
                    record["session_id"],
                    record["filename"],
                    record["mime"],
                    record["size"],
                    record["sha256"],
                    record["stored_path"],
                    _now(),
                ),
            )

    def add_chunks(self, attachment_id: str, chunks: Iterable[dict[str, Any]]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO attachment_chunks(chunk_id, attachment_id,"
                " ordinal, locator, text) VALUES (?, ?, ?, ?, ?)",
                [
                    (c["chunk_id"], attachment_id, c["ordinal"], c["locator"], c["text"])
                    for c in chunks
                ],
            )

    def list_chunks(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.* , a.filename FROM attachment_chunks c"
                " JOIN attachments a ON a.attachment_id = c.attachment_id"
                " WHERE a.session_id = ? ORDER BY c.attachment_id, c.ordinal",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_attachments(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM attachments WHERE session_id = ? ORDER BY imported_at",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]
