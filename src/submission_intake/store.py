from __future__ import annotations

import uuid
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .email_parser import ParsedEmail
from .models import Document, SubmissionResult

# Processing that stopped without finishing (a Lambda timeout, for example) can be claimed again after this.
STALE_AFTER = "15 minutes"


@dataclass(frozen=True)
class Received:
    id: str
    created: bool


class SubmissionStore:
    """Postgres is the record of every submission and its state; S3 keeps the raw email."""

    def __init__(self, conn: Connection[Any]) -> None:
        self._conn = conn

    def migrate(self) -> None:
        self._conn.execute(files("submission_intake").joinpath("schema.sql").read_text())
        self._conn.commit()

    def record_received(self, email: ParsedEmail, raw_key: str) -> Received:
        """Idempotent per Message-ID: S3 can deliver the same event twice, and brokers resend."""
        new_id = str(uuid.uuid4())
        row = self._conn.execute(
            """INSERT INTO submissions (id, message_id, content_hash, raw_key, sender, subject, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'received')
               ON CONFLICT (message_id) DO NOTHING RETURNING id""",
            (new_id, email.message_id, email.content_hash, raw_key, email.sender, email.subject),
        ).fetchone()
        if row is None:
            existing = self._conn.execute(
                "SELECT id FROM submissions WHERE message_id = %s", (email.message_id,)
            ).fetchone()
            self._conn.commit()
            assert existing is not None
            return Received(str(existing[0]), created=False)
        self._conn.commit()
        return Received(new_id, created=True)

    def claim(self, submission_id: str) -> bool:
        """Starts processing unless it's done, or another worker is on it and hasn't gone stale."""
        row = self._conn.execute(
            f"""UPDATE submissions SET status = 'processing', attempts = attempts + 1, processed_at = now()
                WHERE id = %s AND (status IN ('received', 'failed')
                                   OR (status = 'processing' AND processed_at < now() - interval '{STALE_AFTER}'))
                RETURNING id""",
            (submission_id,),
        ).fetchone()
        self._conn.commit()
        return row is not None

    def save_result(self, submission_id: str, documents: list[Document], result: SubmissionResult) -> None:
        with self._conn.transaction():
            self._conn.execute("DELETE FROM documents WHERE submission_id = %s", (submission_id,))
            for d in documents:
                self._conn.execute(
                    "INSERT INTO documents (submission_id, id, filename, kind, chars) VALUES (%s, %s, %s, %s, %s)",
                    (submission_id, d.id, d.filename, d.kind.value, len(d.text)),
                )
            self._conn.execute(
                "UPDATE submissions SET status = %s, result = %s, error = NULL, processed_at = now() WHERE id = %s",
                (result.status, Jsonb(result.model_dump(mode="json")), submission_id),
            )
        self._conn.commit()

    def mark_failed(self, submission_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE submissions SET status = 'failed', error = %s, processed_at = now() WHERE id = %s",
            (error[:2000], submission_id),
        )
        self._conn.commit()

    def get(self, submission_id: str) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute("SELECT * FROM submissions WHERE id = %s", (submission_id,)).fetchone()
            if row is not None:
                row["documents"] = cur.execute(
                    "SELECT id, filename, kind, chars FROM documents WHERE submission_id = %s ORDER BY id",
                    (submission_id,),
                ).fetchall()
        self._conn.commit()
        return row

    def review_queue(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                """SELECT id, subject, sender, received_at, result->'review_reasons' AS reasons
                   FROM submissions WHERE status = 'needs_review' ORDER BY received_at LIMIT %s""",
                (limit,),
            ).fetchall()
        self._conn.commit()
        return rows
