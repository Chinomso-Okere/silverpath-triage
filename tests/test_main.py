"""CLI tests: main() driven in-process. Zero API calls (the Anthropic client
constructor fails the test if called) and a tmp_path database via config.DB_PATH."""
from datetime import datetime, timezone

import anthropic
import pytest

from silverpath_triage import config, main
from silverpath_triage.models.entry import TriageEntry
from silverpath_triage.models.triage import (
    ContactInfo, Intent, KeyDetails, Route, TriageRecord, TriageResult, Urgency,
)
from silverpath_triage.services import storage
from silverpath_triage.services.triage import TriageError, build_record


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "triage.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    return db_path


@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Anthropic client was created")

    monkeypatch.setattr(anthropic, "Anthropic", fail_if_called)


def make_result(confidence: float = 0.87) -> TriageResult:
    return TriageResult(
        intent=Intent.new_enquiry,
        urgency=Urgency.medium,
        summary="Wants a garden clearance quote.",
        key_details=KeyDetails(
            customer_name="Test Person",
            requested_service="garden clearance",
            deadline_or_date="next month",
            location_or_postcode="AB1 2CD",
            contact_info=ContactInfo(phone="01234 567890", email="test@example.com"),
        ),
        suggested_route=Route.sales,
        confidence=confidence,
        reasoning="Clear request for a new service.",
    )


def save(record: TriageRecord, source: str = "data/samples/enquiry_01.txt") -> int:
    entry = TriageEntry(
        created_at=datetime.now(timezone.utc),
        source=source,
        enquiry_text="Hi, could you quote for a garden clearance?",
        model=config.MODEL,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        record=record,
    )
    return storage.save_entry(entry, db_path=config.DB_PATH)


@pytest.fixture
def enquiry_file(tmp_path):
    path = tmp_path / "enquiry.txt"
    path.write_text("Hi, could you quote for a garden clearance?\n", encoding="utf-8")
    return path


@pytest.fixture
def fake_triage(monkeypatch):
    calls = []

    def fake(text):
        calls.append(text)
        return make_result()

    monkeypatch.setattr(main, "triage_enquiry", fake)
    return calls


def run_exit(argv) -> SystemExit:
    with pytest.raises(SystemExit) as exc:
        main.main(argv)
    return exc.value


def test_no_command_prints_help(capsys):
    main.main([])
    out = capsys.readouterr().out
    for command in ("triage", "list", "show"):
        assert command in out


def test_triage_prints_result_then_saves(capsys, enquiry_file, fake_triage):
    main.main(["triage", str(enquiry_file)])

    record = build_record(make_result())
    assert capsys.readouterr().out == main.format_record(record) + "\n\nSaved as entry 1\n"

    entry = storage.get_entry(1, db_path=config.DB_PATH)
    assert entry.source == str(enquiry_file)
    assert entry.enquiry_text == enquiry_file.read_text(encoding="utf-8")
    assert entry.model == config.MODEL
    assert entry.confidence_threshold == config.CONFIDENCE_THRESHOLD
    assert entry.record == record
    assert entry.created_at.utcoffset().total_seconds() == 0
    assert entry.verdict.reviewed_at is None


def test_triage_writes_no_json(enquiry_file, fake_triage):
    data_dir = config.PROJECT_ROOT / "data"
    before = set(data_dir.rglob("*.json"))
    main.main(["triage", str(enquiry_file)])
    assert set(data_dir.rglob("*.json")) == before


def test_triage_failure_saves_nothing(monkeypatch, enquiry_file):
    def failing(text):
        raise TriageError("The model refused to triage this enquiry.")

    monkeypatch.setattr(main, "triage_enquiry", failing)
    assert run_exit(["triage", str(enquiry_file)]).code == (
        "Error: The model refused to triage this enquiry."
    )
    assert storage.list_entries(db_path=config.DB_PATH) == []


def test_triage_missing_file(tmp_path, fake_triage):
    exit_ = run_exit(["triage", str(tmp_path / "missing.txt")])
    assert exit_.code.startswith("Error: ")
    assert fake_triage == []
    assert storage.list_entries(db_path=config.DB_PATH) == []


def test_list_newest_first_and_columns(capsys):
    ids = [save(build_record(make_result()), source=f"file_{n}.txt") for n in range(3)]
    main.main(["list"])
    lines = capsys.readouterr().out.splitlines()

    assert lines[0].split()[:2] == ["ID", "Created"]
    assert [int(line.split()[0]) for line in lines[1:]] == list(reversed(ids))
    first = lines[1].split()
    assert first[3:] == ["new_enquiry", "sales", "0.87", "no", "no", "file_2.txt"]


def test_list_needs_review_and_limit(capsys):
    low = build_record(make_result(confidence=0.3))   # below threshold: needs review
    high = build_record(make_result(confidence=0.9))
    ids = [save(r) for r in (low, high, low, high)]

    main.main(["list", "--needs-review"])
    lines = capsys.readouterr().out.splitlines()[1:]
    assert [int(line.split()[0]) for line in lines] == [ids[2], ids[0]]

    main.main(["list", "--limit", "2"])
    lines = capsys.readouterr().out.splitlines()[1:]
    assert [int(line.split()[0]) for line in lines] == [ids[3], ids[2]]


def test_list_empty(capsys):
    main.main(["list"])
    assert capsys.readouterr().out == "No entries.\n"
    main.main(["list", "--needs-review"])
    assert capsys.readouterr().out == "No entries need review.\n"


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_limit_must_be_positive(capsys, bad):
    assert run_exit(["list", "--limit", bad]).code == 2
    assert "--limit" in capsys.readouterr().err


def test_show_entry(capsys):
    record = build_record(make_result())
    entry_id = save(record)
    main.main(["show", str(entry_id)])
    out = capsys.readouterr().out

    assert f"=== Entry {entry_id} ===" in out
    assert "Source:         data/samples/enquiry_01.txt" in out
    assert f"Model:          {config.MODEL}" in out
    assert main.format_record(record, config.CONFIDENCE_THRESHOLD) in out
    assert "=== Original enquiry ===\nHi, could you quote for a garden clearance?" in out
    assert out.rstrip().endswith("=== Human verdict ===\nNot yet verified.")


def test_show_with_verdict(capsys):
    entry_id = save(build_record(make_result()))
    storage.set_verdict(entry_id, Intent.complaint, Route.support, db_path=config.DB_PATH)
    main.main(["show", str(entry_id)])
    out = capsys.readouterr().out

    assert "Not yet verified." not in out
    assert "Correct intent: complaint" in out
    assert "Correct route:  support" in out


def test_show_unknown_id():
    exit_ = run_exit(["show", "999"])
    assert exit_.code == "No entry with id 999"


def test_show_non_integer_id(capsys):
    assert run_exit(["show", "abc"]).code == 2
    assert "invalid int value" in capsys.readouterr().err


def test_list_and_show_never_create_client(capsys):
    # The no_client fixture fails the test if anthropic.Anthropic is called.
    entry_id = save(build_record(make_result()))
    main.main(["list"])
    main.main(["show", str(entry_id)])
    assert "Saved" not in capsys.readouterr().out


def test_database_problem_is_clean_error(temp_db):
    temp_db.write_bytes(b"this is not a sqlite database " * 100)
    exit_ = run_exit(["list"])
    assert exit_.code.startswith("Error: Database problem")
