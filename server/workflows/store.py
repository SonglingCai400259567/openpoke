
import json
import sqlite3
import uuid
import re

from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_STOP_WORDS = {
    "a", "an", "the", "to", "for", "of",
    "with", "about", "on", "in", "my",
    "me", "please", "did", "has", "have",
    "is", "was", "whether", "can", "you",
    "and", "or", "i"
}


def build_fts_query(text: str) -> str:
    tokens = re.findall(
        r"[^\W_]+",
        text.casefold(),
        flags=re.UNICODE
    )

    unique_tokens = list(dict.fromkeys(
        token for token in tokens
        if token not in _STOP_WORDS
    ))

    return " OR ".join(
        f'"{token}"'
        for token in unique_tokens[:12]
    )



class WorkflowStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            self.db_path,
            timeout=5
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    context_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflows_user
                ON workflows(user_id)
            """)


            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,

                    FOREIGN KEY (workflow_id)
                    REFERENCES workflows(workflow_id)
                    ON DELETE CASCADE
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_workflow
                ON workflow_events(workflow_id, event_id)
            """)


            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    instructions TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,

                    FOREIGN KEY (workflow_id)
                    REFERENCES workflows(workflow_id)
                    ON DELETE CASCADE,

                    CHECK (
                        status IN (
                            'running',
                            'completed',
                            'failed'
                        )
                    )
                )
            """)

            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_one_running_run_per_workflow
                ON workflow_runs(workflow_id)
                WHERE status = 'running'
            """)


            # Full-text search index for workflow discovery
            fts_exists = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'workflow_fts'
                """
            ).fetchone() is not None

            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS workflow_fts
                USING fts5(
                    workflow_id UNINDEXED,
                    title,
                    summary,
                    tokenize='unicode61'
                )
            """)

            # Keep the search index synchronized
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS workflow_fts_insert
                AFTER INSERT ON workflows
                BEGIN
                    INSERT INTO workflow_fts (
                        workflow_id, title, summary
                    )
                    VALUES (
                        NEW.workflow_id, NEW.title, NEW.summary
                    );
                END
            """)

            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS workflow_fts_update
                AFTER UPDATE OF title, summary ON workflows
                BEGIN
                    DELETE FROM workflow_fts
                    WHERE workflow_id = OLD.workflow_id;

                    INSERT INTO workflow_fts (
                        workflow_id, title, summary
                    )
                    VALUES (
                        NEW.workflow_id, NEW.title, NEW.summary
                    );
                END
            """)

            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS workflow_fts_delete
                AFTER DELETE ON workflows
                BEGIN
                    DELETE FROM workflow_fts
                    WHERE workflow_id = OLD.workflow_id;
                END
            """)

            # Backfill workflows created before FTS was installed
            if not fts_exists:
                conn.execute("""
                    INSERT INTO workflow_fts (
                        workflow_id, title, summary
                    )
                    SELECT workflow_id, title, summary
                    FROM workflows
                """)






    def create_workflow(
        self,
        user_id: str,
        title: str,
        task_type: str,
        summary: str,
        context: dict | None = None,
    ) -> str:

        workflow_id = str(uuid.uuid4())
        timestamp = utc_now()

        context_json = json.dumps(
            context or {},
            ensure_ascii=False
        )

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO workflows (
                    workflow_id,
                    user_id,
                    title,
                    task_type,
                    summary,
                    context_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    user_id,
                    title,
                    task_type,
                    summary,
                    context_json,
                    timestamp,
                    timestamp
                )
            )

        return workflow_id

    def get_workflow(
        self,
        workflow_id: str,
        user_id: str
    ) -> dict | None:

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM workflows
                WHERE workflow_id = ?
                  AND user_id = ?
                """,
                (workflow_id, user_id)
            ).fetchone()

        if row is None:
            return None

        workflow = dict(row)

        workflow["context"] = json.loads(
            workflow.pop("context_json")
        )

        return workflow


    def append_event(
        self,
        workflow_id: str,
        user_id: str,
        event_type: str,
        payload: dict
    ) -> int:

        payload_json = json.dumps(
            payload,
            ensure_ascii=False
        )

        timestamp = utc_now()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workflow_events (
                    workflow_id,
                    event_type,
                    payload_json,
                    created_at
                )
                SELECT workflow_id, ?, ?, ?
                FROM workflows
                WHERE workflow_id = ?
                  AND user_id = ?
                """,
                (
                    event_type,
                    payload_json,
                    timestamp,
                    workflow_id,
                    user_id
                )
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Workflow not found or access denied"
                )

            event_id = cursor.lastrowid

        return int(event_id)


    def list_events(
        self,
        workflow_id: str,
        user_id: str
    ) -> list[dict]:

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    e.event_id,
                    e.workflow_id,
                    e.event_type,
                    e.payload_json,
                    e.created_at
                FROM workflow_events AS e
                JOIN workflows AS w
                  ON e.workflow_id = w.workflow_id
                WHERE e.workflow_id = ?
                  AND w.user_id = ?
                ORDER BY e.event_id ASC
                """,
                (workflow_id, user_id)
            ).fetchall()

        events = []

        for row in rows:
            event = dict(row)

            event["payload"] = json.loads(
                event.pop("payload_json")
            )

            events.append(event)

        return events


    def start_run(
        self,
        workflow_id: str,
        user_id: str,
        instructions: str
    ) -> str:

        run_id = str(uuid.uuid4())
        timestamp = utc_now()

        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_id,
                        workflow_id,
                        instructions,
                        status,
                        started_at
                    )
                    SELECT ?, workflow_id, ?, 'running', ?
                    FROM workflows
                    WHERE workflow_id = ?
                      AND user_id = ?
                    """,
                    (
                        run_id,
                        instructions,
                        timestamp,
                        workflow_id,
                        user_id
                    )
                )

                if cursor.rowcount != 1:
                    raise ValueError(
                        "Workflow not found or access denied"
                    )

        except sqlite3.IntegrityError as exc:
            raise RuntimeError(
                "Cannot start run: another run may "
                "already be active for this workflow"
            ) from exc

        return run_id


    def complete_run(
        self,
        run_id: str,
        user_id: str,
        result: dict
    ) -> None:

        result_json = json.dumps(
            result,
            ensure_ascii=False
        )

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE workflow_runs
                SET status = 'completed',
                    result_json = ?,
                    finished_at = ?
                WHERE run_id = ?
                  AND status = 'running'
                  AND workflow_id IN (
                      SELECT workflow_id
                      FROM workflows
                      WHERE user_id = ?
                  )
                """,
                (
                    result_json,
                    utc_now(),
                    run_id,
                    user_id
                )
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Run not found, access denied, "
                    "or run is not active"
                )


    def fail_run(
        self,
        run_id: str,
        user_id: str,
        error: str
    ) -> None:

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE workflow_runs
                SET status = 'failed',
                    error = ?,
                    finished_at = ?
                WHERE run_id = ?
                  AND status = 'running'
                  AND workflow_id IN (
                      SELECT workflow_id
                      FROM workflows
                      WHERE user_id = ?
                  )
                """,
                (
                    error,
                    utc_now(),
                    run_id,
                    user_id
                )
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Run not found, access denied, "
                    "or run is not active"
                )


    def get_run(
        self,
        run_id: str,
        user_id: str
    ) -> dict | None:

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT r.*
                FROM workflow_runs AS r
                JOIN workflows AS w
                  ON r.workflow_id = w.workflow_id
                WHERE r.run_id = ?
                  AND w.user_id = ?
                """,
                (run_id, user_id)
            ).fetchone()

        if row is None:
            return None

        run = dict(row)

        run["result"] = (
            json.loads(run.pop("result_json"))
            if run["result_json"] is not None
            else None
        )

        return run


    def search_workflows(
        self,
        user_id: str,
        query: str,
        top_k: int = 5
    ) -> list[dict]:

        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")

        fts_query = build_fts_query(query)

        if not fts_query:
            return []

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.workflow_id,
                    w.title,
                    w.task_type,
                    w.summary,
                    w.status,
                    bm25(workflow_fts, 2.0, 1.0) AS score
                FROM workflow_fts
                JOIN workflows AS w
                  ON workflow_fts.workflow_id = w.workflow_id
                WHERE workflow_fts MATCH ?
                  AND w.user_id = ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (fts_query, user_id, top_k)
            ).fetchall()

        return [dict(row) for row in rows]


    def finish_run(
        self,
        run_id: str,
        user_id: str,
        success: bool,
        result: dict,
        error: str | None = None
    ) -> None:
        """Atomically finish a run and record its event."""

        status = "completed" if success else "failed"
        timestamp = utc_now()

        result_json = json.dumps(
            result,
            ensure_ascii=False
        )

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    result_json = ?,
                    error = ?,
                    finished_at = ?
                WHERE run_id = ?
                  AND status = 'running'
                  AND workflow_id IN (
                      SELECT workflow_id
                      FROM workflows
                      WHERE user_id = ?
                  )
                """,
                (
                    status,
                    result_json,
                    error,
                    timestamp,
                    run_id,
                    user_id
                )
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Run not found, access denied, "
                    "or run is not active"
                )

            row = conn.execute(
                """
                SELECT workflow_id
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (run_id,)
            ).fetchone()

            event_type = (
                "run_completed" if success else "run_failed"
            )

            conn.execute(
                """
                INSERT INTO workflow_events (
                    workflow_id,
                    event_type,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    row["workflow_id"],
                    event_type,
                    json.dumps({
                        "run_id": run_id,
                        "status": status
                    }),
                    timestamp
                )
            )


