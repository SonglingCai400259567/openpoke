
import hashlib
import numpy as np

from sentence_transformers import SentenceTransformer

from .store import WorkflowStore


class DenseWorkflowRetriever:

    def __init__(
        self,
        store: WorkflowStore,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        self.store = store
        self.model_name = model_name
        self.model = SentenceTransformer(
            model_name,
            device="cpu"
        )

        with self.store._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_embeddings (
                    workflow_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    embedding BLOB NOT NULL,

                    FOREIGN KEY (workflow_id)
                    REFERENCES workflows(workflow_id)
                    ON DELETE CASCADE
                )
            """)

    def refresh(self, user_id: str) -> int:
        """Encode only new or changed workflows."""

        with self.store._connection() as conn:
            workflows = conn.execute(
                """
                SELECT workflow_id, title, summary
                FROM workflows
                WHERE user_id = ?
                ORDER BY workflow_id
                """,
                (user_id,)
            ).fetchall()

            cached = conn.execute(
                """
                SELECT e.workflow_id, e.model_name, e.text_hash
                FROM workflow_embeddings AS e
                JOIN workflows AS w
                  ON e.workflow_id = w.workflow_id
                WHERE w.user_id = ?
                """,
                (user_id,)
            ).fetchall()

        known = {
            row["workflow_id"]: (
                row["model_name"],
                row["text_hash"]
            )
            for row in cached
        }

        pending = []

        for workflow in workflows:
            text = (
                f"{workflow['title']}\n"
                f"{workflow['summary']}"
            )

            digest = hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest()

            old = known.get(workflow["workflow_id"])

            if old != (self.model_name, digest):
                pending.append((
                    workflow["workflow_id"],
                    text,
                    digest
                ))

        if not pending:
            return 0

        vectors = self.model.encode_document(
            [item[1] for item in pending],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False
        ).astype(np.float32)

        with self.store._connection() as conn:
            conn.executemany(
                """
                INSERT INTO workflow_embeddings (
                    workflow_id,
                    model_name,
                    text_hash,
                    embedding
                )
                VALUES (?, ?, ?, ?)

                ON CONFLICT(workflow_id)
                DO UPDATE SET
                    model_name = excluded.model_name,
                    text_hash = excluded.text_hash,
                    embedding = excluded.embedding
                """,
                [
                    (
                        item[0],
                        self.model_name,
                        item[2],
                        vector.tobytes()
                    )
                    for item, vector in zip(pending, vectors)
                ]
            )

        return len(pending)

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5
    ) -> list[dict]:

        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")

        if not query.strip():
            return []

        self.refresh(user_id)

        query_vector = self.model.encode_query(
            query,
            normalize_embeddings=True,
            convert_to_numpy=True
        ).astype(np.float32)

        with self.store._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.workflow_id,
                    w.title,
                    w.summary,
                    w.task_type,
                    w.status,
                    e.embedding
                FROM workflow_embeddings AS e
                JOIN workflows AS w
                  ON e.workflow_id = w.workflow_id
                WHERE w.user_id = ?
                  AND e.model_name = ?
                """,
                (user_id, self.model_name)
            ).fetchall()

        results = []

        for row in rows:
            vector = np.frombuffer(
                row["embedding"],
                dtype=np.float32
            )

            if vector.shape != query_vector.shape:
                raise ValueError("Invalid embedding dimensions")

            score = float(np.dot(query_vector, vector))

            results.append({
                "workflow_id": row["workflow_id"],
                "title": row["title"],
                "summary": row["summary"],
                "task_type": row["task_type"],
                "status": row["status"],
                "dense_score": score
            })

        results.sort(
            key=lambda item: (
                -item["dense_score"],
                item["workflow_id"]
            )
        )

        return results[:top_k]
