"""CLI tests: main() driven in-process. Zero API calls (the Anthropic client
constructor fails the test if called) and a tmp_path database via config.DB_PATH."""
from datetime import datetime, timezone
from types import SimpleNamespace

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
    assert first[3:] == ["new_enquiry", "sales", "0.87", "no", "-", "no", "file_2.txt"]


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


def test_commands_never_create_client(capsys):
    # The no_client fixture fails the test if anthropic.Anthropic is called.
    entry_id = save(build_record(make_result()))
    main.main(["list"])
    main.main(["show", str(entry_id)])
    main.main(["verify", str(entry_id), "--intent", "spam", "--route", "ignore"])
    main.main(["delete", str(entry_id), "--yes"])
    assert f"Deleted entry {entry_id}." in capsys.readouterr().out


def test_database_problem_is_clean_error(temp_db):
    temp_db.write_bytes(b"this is not a sqlite database " * 100)
    exit_ = run_exit(["list"])
    assert exit_.code.startswith("Error: Database problem")


# --- verify -----------------------------------------------------------------

def test_verify_stores_and_show_displays(capsys):
    entry_id = save(build_record(make_result()))
    main.main(["verify", str(entry_id), "--intent", "complaint", "--route", "support"])
    out = capsys.readouterr().out
    assert out.startswith(f"Verified entry {entry_id} (stored):\n")
    assert "Correct intent: complaint" in out
    assert "Correct route:  support" in out
    assert "Replaced previous verdict" not in out

    verdict = storage.get_entry(entry_id, db_path=config.DB_PATH).verdict
    assert (verdict.correct_intent, verdict.correct_route) == (Intent.complaint, Route.support)

    main.main(["show", str(entry_id)])
    out = capsys.readouterr().out
    assert "Not yet verified." not in out
    assert "Correct intent: complaint" in out


def test_reverify_overwrites_and_says_so(capsys):
    entry_id = save(build_record(make_result()))
    main.main(["verify", str(entry_id), "--intent", "complaint", "--route", "support"])
    capsys.readouterr()

    main.main(["verify", str(entry_id), "--intent", "billing", "--route", "billing"])
    out = capsys.readouterr().out
    assert out.startswith("Replaced previous verdict: intent=complaint, route=support (reviewed ")
    assert "Correct intent: billing" in out

    verdict = storage.get_entry(entry_id, db_path=config.DB_PATH).verdict
    assert (verdict.correct_intent, verdict.correct_route) == (Intent.billing, Route.billing)


@pytest.mark.parametrize(("flag", "value"), [("--intent", "nonsense"), ("--route", "nonsense")])
def test_verify_invalid_choice(capsys, flag, value):
    entry_id = save(build_record(make_result()))
    args = {"--intent": "spam", "--route": "ignore", flag: value}
    argv = ["verify", str(entry_id), "--intent", args["--intent"], "--route", args["--route"]]

    assert run_exit(argv).code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert storage.get_entry(entry_id, db_path=config.DB_PATH).verdict.reviewed_at is None


@pytest.mark.parametrize("argv", [
    ["verify", "1", "--intent", "spam"],
    ["verify", "1", "--route", "ignore"],
])
def test_verify_requires_intent_and_route(argv):
    assert run_exit(argv).code == 2


def test_verify_unknown_id():
    exit_ = run_exit(["verify", "999", "--intent", "spam", "--route", "ignore"])
    assert exit_.code == "No entry with id 999"


# --- delete -----------------------------------------------------------------

@pytest.fixture
def answer(monkeypatch):
    """Replace input(): set answer.value to a string, or to EOFError."""
    state = SimpleNamespace(value="", prompts=[])

    def fake_input(prompt=""):
        state.prompts.append(prompt)
        if state.value is EOFError:
            raise EOFError
        return state.value

    monkeypatch.setattr("builtins.input", fake_input)
    return state


@pytest.fixture
def no_input(monkeypatch):
    def fail(prompt=""):
        pytest.fail("input() was called")

    monkeypatch.setattr("builtins.input", fail)


def test_delete_shows_entry_and_prompts(capsys, answer):
    entry_id = save(build_record(make_result()), source="data/samples/eval_05_spam_seo.txt")
    answer.value = "n"
    main.main(["delete", str(entry_id)])
    out = capsys.readouterr().out

    assert out.startswith(f"Entry {entry_id}\nCreated: ")
    assert "Source:  data/samples/eval_05_spam_seo.txt" in out
    assert answer.prompts == ["Delete this entry permanently? [y/N] "]


@pytest.mark.parametrize("reply", ["n", "", "no", "maybe"])
def test_delete_declined_keeps(capsys, answer, reply):
    entry_id = save(build_record(make_result()))
    answer.value = reply
    main.main(["delete", str(entry_id)])

    assert f"Kept entry {entry_id}. Nothing was deleted." in capsys.readouterr().out
    assert storage.get_entry(entry_id, db_path=config.DB_PATH) is not None


def test_delete_eof_keeps(capsys, answer):
    entry_id = save(build_record(make_result()))
    answer.value = EOFError
    main.main(["delete", str(entry_id)])

    assert f"Kept entry {entry_id}. Nothing was deleted." in capsys.readouterr().out
    assert storage.get_entry(entry_id, db_path=config.DB_PATH) is not None


@pytest.mark.parametrize("reply", ["y", "yes", " Y "])
def test_delete_confirmed(capsys, answer, reply):
    entry_id = save(build_record(make_result()))
    answer.value = reply
    main.main(["delete", str(entry_id)])

    assert f"Deleted entry {entry_id}." in capsys.readouterr().out
    assert run_exit(["show", str(entry_id)]).code == f"No entry with id {entry_id}"


def test_delete_yes_flag_skips_prompt(capsys, no_input):
    entry_id = save(build_record(make_result()))
    main.main(["delete", str(entry_id), "--yes"])

    assert f"Deleted entry {entry_id}." in capsys.readouterr().out
    assert storage.get_entry(entry_id, db_path=config.DB_PATH) is None


def test_delete_unknown_id_no_prompt(no_input):
    assert run_exit(["delete", "999"]).code == "No entry with id 999"


def test_delete_leaves_other_entries():
    keep_id = save(build_record(make_result()))
    main.main(["verify", str(keep_id), "--intent", "complaint", "--route", "support"])
    before = storage.get_entry(keep_id, db_path=config.DB_PATH)

    gone_id = save(build_record(make_result()))
    main.main(["delete", str(gone_id), "--yes"])

    assert storage.get_entry(keep_id, db_path=config.DB_PATH) == before


# --- escalation (build #3) ---------------------------------------------------

# (needs_review, route, Why value, Escalate: text)
COMBOS = [
    (False, Route.sales, "-", "no"),
    (True, Route.sales, "low conf", "YES (low confidence)"),
    (False, Route.human_review, "routed", "YES (routed to human_review)"),
    (True, Route.human_review, "both", "YES (low confidence and routed to human_review)"),
]


def record_for(needs_review: bool, route: Route) -> TriageRecord:
    # Via build_record(): needs_review comes from confidence (0.3 below, 0.9 above).
    result = TriageResult.model_validate(
        make_result(confidence=0.3 if needs_review else 0.9).model_dump()
        | {"suggested_route": route})
    return build_record(result)


def save_all_combos() -> list[int]:
    return [save(record_for(nr, route)) for nr, route, _, _ in COMBOS]


def why_values(out: str) -> dict[int, str]:
    # By column position: "low conf" contains a space, so split() can't be used.
    header, *lines = out.splitlines()
    assert header == main.LIST_HEADER
    start = header.index("Why")
    return {int(line.split()[0]): line[start:start + 8].rstrip() for line in lines}


@pytest.mark.parametrize("needs_review, route, reason, _text", COMBOS)
def test_escalation_reason_agrees_with_escalate(needs_review, route, reason, _text):
    record = record_for(needs_review, route)
    assert record.needs_review is needs_review
    assert main.escalation_reason(record) == reason
    assert (main.escalation_reason(record) == "-") is (not record.escalate)


def test_list_why_column(capsys):
    ids = save_all_combos()
    main.main(["list"])
    assert why_values(capsys.readouterr().out) == {
        entry_id: reason for entry_id, (_, _, reason, _) in zip(ids, COMBOS)}


def test_list_escalated_contents_and_order(capsys):
    ids = save_all_combos()
    main.main(["list", "--escalated"])
    why = why_values(capsys.readouterr().out)
    assert list(why) == [ids[3], ids[2], ids[1]]
    assert list(why.values()) == ["both", "routed", "low conf"]


def test_list_escalated_empty(capsys):
    main.main(["list", "--escalated"])
    assert capsys.readouterr().out == "No entries need escalation.\n"
    save(record_for(False, Route.sales))  # stored, but not escalated
    main.main(["list", "--escalated"])
    assert capsys.readouterr().out == "No entries need escalation.\n"


def test_list_needs_review_ignores_routing(capsys):
    # --needs-review is unchanged: the routed, confident entry (Entry 1's case) is absent.
    ids = save_all_combos()
    main.main(["list", "--needs-review"])
    assert list(why_values(capsys.readouterr().out)) == [ids[3], ids[1]]


def test_list_needs_review_and_escalated_together_is_rejected(capsys, temp_db):
    assert run_exit(["list", "--needs-review", "--escalated"]).code == 2
    err = capsys.readouterr().err
    assert "--needs-review" in err and "--escalated" in err
    assert "not allowed with" in err
    assert not temp_db.exists()  # rejected before any database was opened


def test_list_help_defines_both_flags(capsys):
    assert run_exit(["list", "--help"]).code == 0
    help_text = " ".join(capsys.readouterr().out.split())  # undo argparse line wrapping
    assert "only entries where the model is unsure (confidence below the threshold)" in help_text
    assert "only entries a person must see (model unsure, or routed to human_review)" in help_text


@pytest.mark.parametrize("needs_review, route, _reason, text", COMBOS)
def test_format_record_escalate_line(needs_review, route, _reason, text):
    lines = main.format_record(record_for(needs_review, route)).splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith("Needs review:"))
    assert lines[i + 1] == f"Escalate:       {text}"


def test_show_includes_escalate_line(capsys):
    entry_id = save(record_for(False, Route.human_review))
    main.main(["show", str(entry_id)])
    assert ("Needs review:   no\nEscalate:       YES (routed to human_review)\n"
            in capsys.readouterr().out)


def test_triage_includes_escalate_line(capsys, enquiry_file, fake_triage):
    main.main(["triage", str(enquiry_file)])  # fake result: sales, 0.87
    assert "Needs review:   no\nEscalate:       no\n" in capsys.readouterr().out
