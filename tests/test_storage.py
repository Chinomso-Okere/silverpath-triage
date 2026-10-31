"""Storage tests: hand-made records, a tmp_path database per test.
Zero API calls; the real data/triage.db is never opened (see guard below)."""
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from silverpath_triage import config
from silverpath_triage.models.entry import HumanVerdict, TriageEntry
from silverpath_triage.models.triage import (
    ContactInfo, Intent, KeyDetails, Route, TriageRecord, Urgency,
)
from silverpath_triage.services import storage
from silverpath_triage.services.storage import StorageError


@pytest.fixture(autouse=True)
def connections(monkeypatch) -> list[sqlite3.Connection]:
    """Fail any test that opens the real database; record every connection."""
    opened = []
    real_connect = sqlite3.connect
    real_db = config.DB_PATH.resolve()

    def guarded_connect(database, *args, **kwargs):
        if Path(database).resolve() == real_db:
            pytest.fail(f"Test tried to open the real database: {real_db}")
        conn = real_connect(database, *args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    return opened


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "triage.db"


def make_record(needs_review: bool = False, summary: str = "Wants a garden clearance quote.") -> TriageRecord:
    return TriageRecord(
        intent=Intent.new_enquiry,
        urgency=Urgency.medium,
        summary=summary,
        key_details=KeyDetails(
            customer_name="Test Person",
            requested_service="garden clearance",
            deadline_or_date="next month",
            location_or_postcode="AB1 2CD",
            contact_info=ContactInfo(phone="01234 567890", email="test@example.com"),
        ),
        suggested_route=Route.sales,
        confidence=0.87,
        reasoning="Clear request for a new service.",
        needs_review=needs_review,
    )


def make_entry(
    created_at: datetime | None = None,
    source: str = "data/samples/enquiry_01.txt",
    enquiry_text: str = "Hi, could you quote for a garden clearance?",
    record: TriageRecord | None = None,
) -> TriageEntry:
    return TriageEntry(
        created_at=created_at or datetime.now(timezone.utc),
        source=source,
        enquiry_text=enquiry_text,
        model=config.MODEL,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        record=record or make_record(),
    )


def saved(entry: TriageEntry, entry_id: int) -> TriageEntry:
    """What the database should hand back for `entry` once saved as `entry_id`."""
    return entry.model_copy(update={"id": entry_id})


def assert_utc_aware(value: datetime) -> None:
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def is_closed(conn: sqlite3.Connection) -> bool:
    try:
        conn.cursor()
    except sqlite3.ProgrammingError:
        return True
    return False


def test_init_db_creates_folder_and_table(tmp_path):
    db_path = tmp_path / "nested" / "triage.db"
    storage.init_db(db_path)
    assert db_path.is_file()
    storage.init_db(db_path)  # second call is harmless
    assert storage.list_entries(db_path=db_path) == []


def test_round_trip(db):
    entry = make_entry()
    entry_id = storage.save_entry(entry, db)
    fetched = storage.get_entry(entry_id, db)
    assert fetched == saved(entry, entry_id)
    assert fetched.record == entry.record
    assert fetched.record.confidence == entry.record.confidence
    assert fetched.created_at == entry.created_at
    assert_utc_aware(fetched.created_at)


def test_non_utc_created_at_is_stored_as_utc(db):
    plus_five = datetime(2026, 10, 31, 17, 30, tzinfo=timezone(timedelta(hours=5)))
    entry = make_entry(created_at=plus_five)
    fetched = storage.get_entry(storage.save_entry(entry, db), db)
    assert fetched.created_at == plus_five  # same moment
    assert_utc_aware(fetched.created_at)
    assert fetched.created_at.hour == 12


def test_persists_across_separate_connections(db, connections):
    entry = make_entry()
    entry_id = storage.save_entry(entry, db)
    save_conn = connections[-1]
    assert is_closed(save_conn)

    fetched = storage.get_entry(entry_id, db)
    assert connections[-1] is not save_conn
    assert fetched == saved(entry, entry_id)


def test_every_connection_is_closed(db, connections):
    storage.init_db(db)
    entry_id = storage.save_entry(make_entry(), db)
    storage.get_entry(entry_id, db)
    storage.list_entries(db_path=db)
    storage.set_verdict(entry_id, Intent.complaint, Route.support, db)
    storage.delete_entry(entry_id, db)
    assert len(connections) == 6
    assert all(is_closed(conn) for conn in connections)


def test_list_newest_first_by_id(db):
    now = datetime.now(timezone.utc)
    # created_at deliberately out of order: ordering must follow id, not time.
    first = storage.save_entry(make_entry(created_at=now), db)
    second = storage.save_entry(make_entry(created_at=now - timedelta(days=2)), db)
    third = storage.save_entry(make_entry(created_at=now - timedelta(days=1)), db)
    ids = [e.id for e in storage.list_entries(db_path=db)]
    assert ids == [third, second, first]


def test_list_limit(db):
    ids = [storage.save_entry(make_entry(), db) for _ in range(3)]
    listed = storage.list_entries(limit=2, db_path=db)
    assert [e.id for e in listed] == [ids[2], ids[1]]


def test_list_needs_review_only(db):
    flags = [False, True, False, True]
    ids = [storage.save_entry(make_entry(record=make_record(needs_review=f)), db) for f in flags]

    flagged = storage.list_entries(needs_review_only=True, db_path=db)
    assert [e.id for e in flagged] == [ids[3], ids[1]]
    assert all(e.record.needs_review for e in flagged)
    assert len(storage.list_entries(db_path=db)) == 4


def test_new_entry_has_empty_verdict(db):
    fetched = storage.get_entry(storage.save_entry(make_entry(), db), db)
    assert fetched.verdict == HumanVerdict()


def test_set_verdict(db):
    entry = make_entry()
    entry_id = storage.save_entry(entry, db)

    before = datetime.now(timezone.utc)
    assert storage.set_verdict(entry_id, Intent.complaint, Route.support, db) is True
    after = datetime.now(timezone.utc)

    fetched = storage.get_entry(entry_id, db)
    assert fetched.verdict.correct_intent == Intent.complaint
    assert fetched.verdict.correct_route == Route.support
    assert before <= fetched.verdict.reviewed_at <= after
    assert_utc_aware(fetched.verdict.reviewed_at)
    assert fetched.record == entry.record


def test_delete_entry(db):
    keep = make_entry()
    keep_id = storage.save_entry(keep, db)
    gone_id = storage.save_entry(make_entry(), db)

    assert storage.delete_entry(gone_id, db) is True
    assert storage.get_entry(gone_id, db) is None
    assert storage.get_entry(keep_id, db) == saved(keep, keep_id)
    assert storage.delete_entry(gone_id, db) is False


def test_ids_not_reused_after_delete(db):
    first = storage.save_entry(make_entry(), db)
    storage.delete_entry(first, db)
    assert storage.save_entry(make_entry(), db) > first


def test_unknown_ids(db):
    storage.init_db(db)
    assert storage.get_entry(999, db) is None
    assert storage.set_verdict(999, Intent.complaint, Route.support, db) is False
    assert storage.delete_entry(999, db) is False


def test_save_rejects_entry_with_id(db):
    with pytest.raises(ValueError):
        storage.save_entry(make_entry().model_copy(update={"id": 5}), db)
    assert storage.list_entries(db_path=db) == []


def test_sql_like_text_round_trips(db):
    nasty = "'); DROP TABLE entries;--"
    entry = make_entry(
        source=f"data/samples/{nasty}.txt",
        enquiry_text=f"Robert{nasty} said \"hello\" to O'Brien",
        record=make_record(summary=f"Summary with {nasty}"),
    )
    entry_id = storage.save_entry(entry, db)
    assert storage.get_entry(entry_id, db) == saved(entry, entry_id)

    # The table is still there and still works.
    storage.save_entry(make_entry(), db)
    assert len(storage.list_entries(db_path=db)) == 2


def test_secure_delete_overwrites_deleted_content(db):
    marker = f"SECURE-DELETE-MARKER-{uuid.uuid4().hex}".encode()
    entry_id = storage.save_entry(make_entry(enquiry_text=f"Please erase me: {marker.decode()}"), db)
    assert marker in db.read_bytes()  # the check can see stored text

    assert storage.delete_entry(entry_id, db) is True
    assert marker not in db.read_bytes()


def test_database_problem_raises_storage_error(db, connections):
    db.write_bytes(b"this is not a sqlite database " * 100)
    with pytest.raises(StorageError, match="Database problem"):
        storage.list_entries(db_path=db)
    assert all(is_closed(conn) for conn in connections)


def test_real_db_guard_is_active():
    with pytest.raises(pytest.fail.Exception, match="real database"):
        storage.list_entries()  # default db_path is config.DB_PATH
