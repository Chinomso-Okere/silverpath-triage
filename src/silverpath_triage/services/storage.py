"""All database code lives here and nowhere else (SQLite via sqlite3).
Every query uses ? placeholders; record_json is the source of truth."""
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from silverpath_triage import config
from silverpath_triage.models.entry import HumanVerdict, TriageEntry
from silverpath_triage.models.triage import Intent, Route, TriageRecord


class StorageError(Exception):
    """The database could not be opened, read or written."""


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS entries (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT    NOT NULL,
    source               TEXT    NOT NULL,
    enquiry_text         TEXT    NOT NULL,
    model                TEXT    NOT NULL,
    confidence_threshold REAL    NOT NULL,
    schema_version       INTEGER NOT NULL,
    record_json          TEXT    NOT NULL,
    intent               TEXT    NOT NULL,
    suggested_route      TEXT    NOT NULL,
    urgency              TEXT    NOT NULL,
    confidence           REAL    NOT NULL,
    needs_review         INTEGER NOT NULL,
    verdict_intent       TEXT,
    verdict_route        TEXT,
    verdict_reviewed_at  TEXT
)
"""

# The copied columns (intent .. needs_review) are written from the same record
# as record_json, in this one statement, and never updated afterwards.
_INSERT = """
INSERT INTO entries (
    created_at, source, enquiry_text, model, confidence_threshold,
    schema_version, record_json,
    intent, suggested_route, urgency, confidence, needs_review
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_ONE = """
SELECT id, created_at, source, enquiry_text, model, confidence_threshold,
       schema_version, record_json,
       verdict_intent, verdict_route, verdict_reviewed_at
FROM entries
WHERE id = ?
"""

# Newest first by id, not by the created_at text.
_SELECT_LIST = """
SELECT id, created_at, source, enquiry_text, model, confidence_threshold,
       schema_version, record_json,
       verdict_intent, verdict_route, verdict_reviewed_at
FROM entries
WHERE (? = 0 OR needs_review = 1)
ORDER BY id DESC
LIMIT ?
"""

_SET_VERDICT = """
UPDATE entries
SET verdict_intent = ?, verdict_route = ?, verdict_reviewed_at = ?
WHERE id = ?
"""

_DELETE = "DELETE FROM entries WHERE id = ?"


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    # The only place a connection is opened. Commits if the caller's block
    # succeeds, rolls back if it fails, and always closes.
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
    except (OSError, sqlite3.Error) as e:
        raise StorageError(f"Database problem at {db_path}: {e}") from e
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA secure_delete = ON")  # overwrite deleted content
        conn.execute(_CREATE_TABLE)
        with conn:
            yield conn
    except sqlite3.Error as e:
        raise StorageError(f"Database problem at {db_path}: {e}") from e
    finally:
        conn.close()


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _row_to_entry(row: sqlite3.Row) -> TriageEntry:
    return TriageEntry(
        id=row["id"],
        created_at=row["created_at"],
        source=row["source"],
        enquiry_text=row["enquiry_text"],
        model=row["model"],
        confidence_threshold=row["confidence_threshold"],
        schema_version=row["schema_version"],
        record=TriageRecord.model_validate_json(row["record_json"]),
        verdict=HumanVerdict(
            correct_intent=row["verdict_intent"],
            correct_route=row["verdict_route"],
            reviewed_at=row["verdict_reviewed_at"],
        ),
    )


def init_db(db_path: Path = config.DB_PATH) -> None:
    with _connect(db_path):
        pass


def save_entry(entry: TriageEntry, db_path: Path = config.DB_PATH) -> int:
    if entry.id is not None:
        raise ValueError(f"Entry already has id {entry.id}; only new entries can be saved.")
    record = entry.record
    with _connect(db_path) as conn:
        cursor = conn.execute(_INSERT, (
            _utc_text(entry.created_at),
            entry.source,
            entry.enquiry_text,
            entry.model,
            entry.confidence_threshold,
            entry.schema_version,
            record.model_dump_json(),
            record.intent.value,
            record.suggested_route.value,
            record.urgency.value,
            record.confidence,
            int(record.needs_review),
        ))
        return cursor.lastrowid


def get_entry(entry_id: int, db_path: Path = config.DB_PATH) -> TriageEntry | None:
    with _connect(db_path) as conn:
        row = conn.execute(_SELECT_ONE, (entry_id,)).fetchone()
        return _row_to_entry(row) if row else None


def list_entries(
    limit: int = 20, needs_review_only: bool = False, db_path: Path = config.DB_PATH
) -> list[TriageEntry]:
    with _connect(db_path) as conn:
        rows = conn.execute(_SELECT_LIST, (int(needs_review_only), limit)).fetchall()
        return [_row_to_entry(row) for row in rows]


def set_verdict(
    entry_id: int, intent: Intent, route: Route, db_path: Path = config.DB_PATH
) -> bool:
    reviewed_at = _utc_text(datetime.now(timezone.utc))
    with _connect(db_path) as conn:
        cursor = conn.execute(
            _SET_VERDICT, (Intent(intent).value, Route(route).value, reviewed_at, entry_id)
        )
        return cursor.rowcount == 1


def delete_entry(entry_id: int, db_path: Path = config.DB_PATH) -> bool:
    with _connect(db_path) as conn:
        cursor = conn.execute(_DELETE, (entry_id,))
        return cursor.rowcount == 1
