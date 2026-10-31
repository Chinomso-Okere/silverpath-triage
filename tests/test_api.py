"""API layer tests. Zero API calls (the Anthropic client constructor fails the
test if called; triage is stubbed) and no real database (a temp file, with the
real-database guard). Model checks, the auth dependency on a throwaway app, then
the real app's POST /triage."""
import logging
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

import anthropic
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from silverpath_triage import config, main
from silverpath_triage.api import auth
from silverpath_triage.api.app import app
from silverpath_triage.api.auth import require_api_key
from silverpath_triage.models.api import TriageRequest, TriageResponse
from silverpath_triage.models.triage import (
    ContactInfo, Intent, KeyDetails, Route, TriageRecord, TriageResult, Urgency,
)
from silverpath_triage.services import storage
from silverpath_triage.services import triage as triage_service
from silverpath_triage.services.storage import StorageError
from silverpath_triage.services.triage import TriageError, build_record


@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Anthropic client was created")

    monkeypatch.setattr(anthropic, "Anthropic", fail_if_called)


def make_record(
    route: Route = Route.sales, confidence: float = 0.87, needs_review: bool = False,
) -> TriageRecord:
    return TriageRecord(
        intent=Intent.new_enquiry,
        urgency=Urgency.medium,
        summary="Wants a quote for a garden clearance next month.",
        key_details=KeyDetails(
            customer_name="Test Person",
            requested_service="garden clearance",
            deadline_or_date="next month",
            location_or_postcode="AB1 2CD",
            contact_info=ContactInfo(phone="01234 567890", email="test@example.com"),
        ),
        suggested_route=route,
        confidence=confidence,
        reasoning="Clear request for a new service.",
        needs_review=needs_review,
    )


def to_response(record: TriageRecord, entry_id: int = 7) -> TriageResponse:
    # The exact mapping the route will use (escalate is set by hand).
    return TriageResponse(entry_id=entry_id, **record.model_dump(), escalate=record.escalate)


# --- config ---------------------------------------------------------------

def test_max_enquiry_chars_is_10000():
    assert config.MAX_ENQUIRY_CHARS == 10_000


@pytest.mark.parametrize("value, expected", [("", ""), ("  spaced-key  ", "spaced-key")])
def test_api_key_is_read_from_env_and_stripped(value, expected):
    # A fresh process, because config is already imported here. The variable is
    # set explicitly (load_dotenv doesn't override it), so .env is never used.
    env = {**os.environ, "SILVERPATH_API_KEY": value}
    result = subprocess.run(
        [sys.executable, "-c",
         f"import silverpath_triage.config as c; assert c.API_KEY == {expected!r}"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


# --- TriageRequest --------------------------------------------------------

@pytest.mark.parametrize("text", ["", " ", "   \n\t "])
def test_blank_enquiry_text_is_rejected(text):
    with pytest.raises(ValidationError) as exc:
        TriageRequest(enquiry_text=text)
    assert exc.value.errors()[0]["loc"] == ("enquiry_text",)


def test_missing_enquiry_text_is_rejected():
    with pytest.raises(ValidationError) as exc:
        TriageRequest()
    assert exc.value.errors()[0]["type"] == "missing"


def test_length_cap_boundary():
    assert TriageRequest(enquiry_text="x" * config.MAX_ENQUIRY_CHARS)
    with pytest.raises(ValidationError) as exc:
        TriageRequest(enquiry_text="x" * (config.MAX_ENQUIRY_CHARS + 1))
    assert exc.value.errors()[0]["type"] == "string_too_long"


def test_valid_text_is_kept_unchanged():
    text = "  Hi, could you quote for a garden clearance?\n"
    assert TriageRequest(enquiry_text=text).enquiry_text == text


def test_source_defaults_to_api():
    assert TriageRequest(enquiry_text="Hello").source == "api"


def test_source_supplied_is_kept():
    assert TriageRequest(enquiry_text="Hello", source="web-form").source == "web-form"


def test_overlong_source_is_rejected():
    with pytest.raises(ValidationError):
        TriageRequest(enquiry_text="Hello", source="s" * 201)


def test_error_details_without_input_do_not_contain_the_text():
    # What the 422 handler will emit (location + message only, no input).
    secret = "ZZ-private-enquiry-ZZ " * 1000
    with pytest.raises(ValidationError) as exc:
        TriageRequest(enquiry_text=secret)
    details = [{"loc": e["loc"], "msg": e["msg"]}
               for e in exc.value.errors(include_input=False)]
    assert details
    assert "ZZ-private-enquiry-ZZ" not in repr(details)


# --- TriageResponse -------------------------------------------------------

def test_response_carries_result_flags_and_entry_id():
    record = make_record()
    response = to_response(record, entry_id=42)
    data = response.model_dump(mode="json")
    assert data["entry_id"] == 42
    assert data["needs_review"] is False
    assert "escalate" in data
    for field, value in record.model_dump(mode="json").items():
        assert data[field] == value


@pytest.mark.parametrize("route, confidence, needs_review, expected", [
    (Route.sales, 0.87, False, False),         # confident, routed to a team
    (Route.human_review, 0.9, False, True),    # routed to a person
    (Route.sales, 0.3, True, True),            # model unsure
    (Route.human_review, 0.3, True, True),
])
def test_response_escalate_equals_record_escalate(route, confidence, needs_review, expected):
    record = make_record(route, confidence, needs_review)
    assert record.escalate is expected
    assert to_response(record).escalate is expected


def test_escalate_is_in_the_response_but_not_the_record():
    record = make_record(Route.human_review)
    assert "escalate" not in record.model_dump()  # why it must be set by hand
    assert to_response(record).model_dump()["escalate"] is True


# --- auth dependency ------------------------------------------------------
# require_api_key is mounted on a throwaway app (GET /protected) defined here.
# The real /triage route arrives in step 3. All keys below are fake test values.

TEST_KEY = "test-key-123"


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", TEST_KEY)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected():
        return {"ok": True}

    return TestClient(app)


def with_key(value: str) -> dict:
    return {"X-API-Key": value}


def test_correct_key_is_accepted(client):
    response = client.get("/protected", headers=with_key(TEST_KEY))
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("headers", [
    None,                                  # header missing
    with_key(""),                          # empty
    with_key("wrong-key"),                 # wrong
    with_key(TEST_KEY + "x"),              # right key plus an extra character
    with_key(TEST_KEY[:-1]),               # right key minus a character
    with_key(TEST_KEY.upper()),            # wrong case
], ids=["missing", "empty", "wrong", "extra-char", "short", "wrong-case"])
def test_missing_or_wrong_key_is_rejected_with_401(client, headers):
    response = client.get("/protected", headers=headers)
    assert response.status_code == 401


@pytest.mark.parametrize("headers", [
    None, with_key(""), with_key("wrong-key"), with_key(TEST_KEY),
], ids=["no-header", "empty", "wrong", "plausible-key"])
def test_blank_configured_key_rejects_everything_with_503(client, monkeypatch, headers):
    monkeypatch.setattr(config, "API_KEY", "")
    response = client.get("/protected", headers=headers)
    assert response.status_code == 503


def test_blank_key_and_no_header_is_503_not_a_match(client, monkeypatch):
    # Without the fail-closed check, "" == "" would let a header-less request in.
    monkeypatch.setattr(config, "API_KEY", "")
    assert client.get("/protected").status_code == 503


def test_dependency_raises_http_exception():
    # Raising (not returning) is what lets it resolve before body validation.
    assert require_api_key(TEST_KEY) is None
    with pytest.raises(HTTPException) as missing:
        require_api_key(None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as wrong:
        require_api_key("wrong-key")
    assert wrong.value.status_code == 401


def test_dependency_raises_503_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    for supplied in (None, "wrong-key", TEST_KEY):
        with pytest.raises(HTTPException) as exc:
            require_api_key(supplied)
        assert exc.value.status_code == 503


def test_configured_key_is_read_at_call_time(client, monkeypatch):
    assert client.get("/protected", headers=with_key(TEST_KEY)).status_code == 200
    monkeypatch.setattr(config, "API_KEY", "another-key-456")
    assert client.get("/protected", headers=with_key(TEST_KEY)).status_code == 401
    assert client.get("/protected", headers=with_key("another-key-456")).status_code == 200
    monkeypatch.setattr(config, "API_KEY", "")
    assert client.get("/protected", headers=with_key("another-key-456")).status_code == 503


def test_key_is_compared_with_compare_digest_on_utf8_bytes(client, monkeypatch):
    calls = []
    real = secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.secrets, "compare_digest", spy)
    client.get("/protected", headers=with_key("wrong-key"))
    assert calls == [(b"wrong-key", TEST_KEY.encode("utf-8"))]

    calls.clear()
    monkeypatch.setattr(config, "API_KEY", "")
    client.get("/protected", headers=with_key("wrong-key"))
    assert calls == []  # not configured: rejected before any comparison


def test_non_ascii_header_is_401_not_a_server_error(client):
    # Sent as UTF-8 bytes (the test client refuses a non-ASCII str header).
    response = client.get("/protected", headers={"X-API-Key": "café".encode("utf-8")})
    assert response.status_code == 401


@pytest.mark.parametrize("configured, supplied, status", [
    ("CONFIGURED-key-AAA111", "CONFIGURED-key-AAA111", 200),   # accepted
    ("CONFIGURED-key-AAA111", "SUBMITTED-key-BBB222", 401),    # rejected
    ("", "SUBMITTED-key-BBB222", 503),                         # not configured
])
def test_keys_never_appear_in_responses_or_logs(
    client, monkeypatch, caplog, configured, supplied, status,
):
    monkeypatch.setattr(config, "API_KEY", configured)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/protected", headers=with_key(supplied))
    assert response.status_code == status
    everything = response.text + str(dict(response.headers)) + caplog.text
    for key in ("CONFIGURED-key-AAA111", "SUBMITTED-key-BBB222"):
        assert key not in everything


# --- the /triage route ----------------------------------------------------
# Real app, driven by TestClient. Triage is stubbed (no client), the database is
# a temp file, and the real-database guard is active, as in test_storage.py.

REAL_DB = config.DB_PATH.resolve()  # captured at import, before temp_db patches it
ENQUIRY = "Hi, ENQUIRY-SENTINEL could you quote for a garden clearance?"
GENERIC_502 = "The triage service could not produce a valid result."
GENERIC_500 = "The entry could not be saved."


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path) -> Path:
    db_path = tmp_path / "triage.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    return db_path


@pytest.fixture(autouse=True)
def connections(monkeypatch) -> list[sqlite3.Connection]:
    """Fail any test that opens the real database; record every connection."""
    opened = []
    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        if Path(database).resolve() == REAL_DB:
            pytest.fail(f"Test tried to open the real database: {REAL_DB}")
        conn = real_connect(database, *args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    return opened


def test_real_db_guard_is_active():
    with pytest.raises(pytest.fail.Exception, match="real database"):
        storage.list_entries()  # default db_path is the real database


def make_result(route: Route = Route.sales, confidence: float = 0.87) -> TriageResult:
    data = make_record(route, confidence).model_dump(exclude={"needs_review"})
    return TriageResult(**data)


class StubTriage:
    """Stands in for triage_service.triage_enquiry; records calls, can raise."""

    def __init__(self):
        self.calls: list[str] = []
        self.result = make_result()
        self.error: Exception | None = None

    def __call__(self, text: str) -> TriageResult:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def stub(monkeypatch) -> StubTriage:
    stubbed = StubTriage()
    monkeypatch.setattr(triage_service, "triage_enquiry", stubbed)
    return stubbed


@pytest.fixture
def api() -> TestClient:
    return TestClient(app)


def post(api: TestClient, text: str = ENQUIRY, key: str | None = TEST_KEY, **extra):
    headers = {} if key is None else with_key(key)
    return api.post("/triage", headers=headers, json={"enquiry_text": text, **extra})


def assert_nothing_stored(connections) -> None:
    """Storage was never even opened: no connection, no database file."""
    assert connections == []
    assert not config.DB_PATH.exists()


def stored_entries() -> list:
    return storage.list_entries(limit=100, db_path=config.DB_PATH)


# happy path

def test_valid_request_returns_the_full_response(api, stub):
    response = post(api)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(TriageResponse.model_fields)
    assert isinstance(body["entry_id"], int)
    expected = to_response(build_record(stub.result), entry_id=body["entry_id"])
    assert body == expected.model_dump(mode="json")
    assert stub.calls == [ENQUIRY]


def test_entry_id_refers_to_a_saved_row(api, stub):
    text = "  padded enquiry text\n"
    body = post(api, text).json()
    entry = storage.get_entry(body["entry_id"], db_path=config.DB_PATH)
    assert entry is not None
    assert entry.record == build_record(stub.result)
    assert entry.source == "api"
    assert entry.enquiry_text == text
    assert entry.model == config.MODEL
    assert entry.confidence_threshold == config.CONFIDENCE_THRESHOLD
    assert len(stored_entries()) == 1


def test_source_supplied_is_stored(api, stub):
    entry_id = post(api, source="web-form").json()["entry_id"]
    assert storage.get_entry(entry_id, db_path=config.DB_PATH).source == "web-form"


@pytest.mark.parametrize("route, confidence, expected", [
    (Route.human_review, 0.9, True),    # routed to a person
    (Route.sales, 0.87, False),         # confident, routed to a team
    (Route.sales, 0.3, True),           # model unsure (needs_review)
])
def test_response_escalate_matches_the_record(api, stub, route, confidence, expected):
    stub.result = make_result(route, confidence)
    body = post(api).json()
    assert body["escalate"] is expected
    assert body["needs_review"] is (confidence < config.CONFIDENCE_THRESHOLD)


def test_escalated_entry_appears_in_the_escalated_list(api, stub, capsys):
    stub.result = make_result(Route.human_review, 0.9)
    escalated_id = post(api).json()["entry_id"]
    stub.result = make_result(Route.sales, 0.87)
    calm_id = post(api).json()["entry_id"]

    escalated = storage.list_entries(escalated_only=True, db_path=config.DB_PATH)
    assert [e.id for e in escalated] == [escalated_id]

    main.main(["list", "--escalated"])
    out = capsys.readouterr().out
    assert main.format_list_line(storage.get_entry(escalated_id, db_path=config.DB_PATH)) in out
    assert main.format_list_line(storage.get_entry(calm_id, db_path=config.DB_PATH)) not in out


# auth at the route

@pytest.mark.parametrize("key", [None, "wrong-key"], ids=["missing", "wrong"])
def test_route_rejects_missing_or_wrong_key_with_401(api, stub, connections, key):
    response = post(api, key=key)
    assert response.status_code == 401
    assert stub.calls == []
    assert_nothing_stored(connections)


@pytest.mark.parametrize("key", [None, "wrong-key", TEST_KEY], ids=["none", "wrong", "plausible"])
def test_route_is_503_when_no_key_is_configured(api, stub, connections, monkeypatch, key):
    monkeypatch.setattr(config, "API_KEY", "")
    response = post(api, key=key)
    assert response.status_code == 503
    assert stub.calls == []
    assert_nothing_stored(connections)


# request validation (good key): rejected before any model call or write

INVALID_BODIES = {
    "missing-field": {},
    "empty": {"enquiry_text": ""},
    "blank": {"enquiry_text": "  \n\t "},
    "over-limit": {"enquiry_text": "OVERLONG-SENTINEL-" * 700},      # 12,600 chars
    "way-over-limit": {"enquiry_text": "x" * 20_000},
    "wrong-type": {"enquiry_text": ["TYPE-SENTINEL"]},
    "bad-source-type": {"enquiry_text": "ok", "source": ["SRC-SENTINEL"]},
    "over-long-source": {"enquiry_text": "ok", "source": "SRC-SENTINEL" * 30},
}


@pytest.mark.parametrize("payload", INVALID_BODIES.values(), ids=INVALID_BODIES.keys())
def test_invalid_body_is_422_with_no_work_and_no_echo(api, stub, connections, payload):
    response = api.post("/triage", headers=with_key(TEST_KEY), json=payload)
    assert response.status_code == 422
    details = response.json()["detail"]
    assert details and all(set(item) == {"loc", "msg"} for item in details)
    for sentinel in ("OVERLONG-SENTINEL", "TYPE-SENTINEL", "SRC-SENTINEL"):
        assert sentinel not in response.text
    assert stub.calls == []
    assert_nothing_stored(connections)


def test_malformed_json_with_a_good_key_is_422(api, stub, connections):
    response = api.post(
        "/triage",
        headers={**with_key(TEST_KEY), "Content-Type": "application/json"},
        content=b'{"enquiry_text": "BROKEN-SENTINEL',
    )
    assert response.status_code == 422
    assert "BROKEN-SENTINEL" not in response.text
    assert stub.calls == []
    assert_nothing_stored(connections)


# error mapping: fixed generic messages, nothing leaked, nothing stored

def test_triage_error_is_502(api, stub, connections, caplog):
    stub.error = TriageError("MODEL-OUTPUT-SENTINEL " + ENQUIRY)
    with caplog.at_level(logging.DEBUG):
        response = post(api)
    assert response.status_code == 502
    assert response.json() == {"detail": GENERIC_502}
    assert "MODEL-OUTPUT-SENTINEL" not in response.text + caplog.text
    assert "ENQUIRY-SENTINEL" not in response.text + caplog.text
    assert "TriageError" in caplog.text  # the safe note: the exception type only
    assert_nothing_stored(connections)


@pytest.mark.parametrize("make_error", [
    lambda: anthropic.APIError("UPSTREAM-SENTINEL " + ENQUIRY, request=None,
                               body={"error": "UPSTREAM-SENTINEL"}),
    lambda: anthropic.APIConnectionError(request=None),
], ids=["api-error", "connection-error"])
def test_anthropic_api_error_is_502(api, stub, connections, caplog, make_error):
    stub.error = make_error()
    with caplog.at_level(logging.DEBUG):
        response = post(api)
    assert response.status_code == 502
    assert response.json() == {"detail": GENERIC_502}
    assert "UPSTREAM-SENTINEL" not in response.text + caplog.text
    assert "ENQUIRY-SENTINEL" not in response.text + caplog.text
    assert "APIError" in caplog.text or "APIConnectionError" in caplog.text
    assert_nothing_stored(connections)


def test_storage_error_is_500(api, stub, connections, caplog, monkeypatch):
    def fail(*args, **kwargs):
        raise StorageError("Database problem at /secret/PATH-SENTINEL/triage.db: boom")

    monkeypatch.setattr(storage, "save_entry", fail)
    with caplog.at_level(logging.DEBUG):
        response = post(api)
    assert response.status_code == 500
    assert response.json() == {"detail": GENERIC_500}
    assert "PATH-SENTINEL" not in response.text + caplog.text
    assert "StorageError" in caplog.text
    assert stub.calls == [ENQUIRY]  # triage ran; nothing was saved
    assert_nothing_stored(connections)


def test_real_storage_error_does_not_leak_the_path(api, stub, caplog, monkeypatch, tmp_path):
    bad_db = tmp_path / "a-directory-not-a-database"
    bad_db.mkdir()
    monkeypatch.setattr(config, "DB_PATH", bad_db)  # sqlite cannot open a directory
    with caplog.at_level(logging.DEBUG):
        response = post(api)
    assert response.status_code == 500
    assert response.json() == {"detail": GENERIC_500}
    leaked = response.text + caplog.text
    assert str(bad_db) not in leaked and "a-directory-not-a-database" not in leaked
    assert "unable to open" not in leaked


# surface: docs/openapi open and clean; logs and responses carry no secrets

def test_openapi_and_docs_are_open_and_hold_no_key_or_enquiry(api, stub, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "OPENAPI-SECRET-KEY")
    post(api, "STORED-ENQUIRY-SENTINEL", key="OPENAPI-SECRET-KEY")  # something is stored
    response = api.get("/openapi.json")  # no key sent
    assert response.status_code == 200
    assert "/triage" in response.json()["paths"]
    assert "OPENAPI-SECRET-KEY" not in response.text
    assert "STORED-ENQUIRY-SENTINEL" not in response.text
    assert api.get("/docs").status_code == 200


def test_no_enquiry_text_key_or_path_is_ever_logged(api, stub, caplog, monkeypatch):
    def fail_save(*args, **kwargs):
        raise StorageError("Database problem at PATH-SENTINEL")

    with caplog.at_level(logging.DEBUG):
        assert post(api).status_code == 200
        assert post(api, key="SUBMITTED-WRONG-KEY").status_code == 401
        assert api.post("/triage", headers=with_key(TEST_KEY),
                        json=INVALID_BODIES["over-limit"]).status_code == 422
        stub.error = TriageError("MODEL-OUTPUT-SENTINEL")
        assert post(api).status_code == 502
        stub.error = None
        monkeypatch.setattr(storage, "save_entry", fail_save)
        assert post(api).status_code == 500
    for forbidden in ("ENQUIRY-SENTINEL", "OVERLONG-SENTINEL", TEST_KEY, "SUBMITTED-WRONG-KEY",
                      "MODEL-OUTPUT-SENTINEL", "PATH-SENTINEL", str(config.DB_PATH)):
        assert forbidden not in caplog.text


@pytest.mark.parametrize("configured, supplied, status", [
    ("CONFIGURED-key-AAA111", "CONFIGURED-key-AAA111", 200),
    ("CONFIGURED-key-AAA111", "SUBMITTED-key-BBB222", 401),
    ("", "SUBMITTED-key-BBB222", 503),
])
def test_neither_key_appears_in_route_responses(api, stub, monkeypatch, configured, supplied, status):
    monkeypatch.setattr(config, "API_KEY", configured)
    response = post(api, key=supplied)
    assert response.status_code == status
    everything = response.text + str(dict(response.headers))
    for key in ("CONFIGURED-key-AAA111", "SUBMITTED-key-BBB222"):
        assert key not in everything


def test_validation_errors_do_not_echo_the_key(api, stub):
    response = api.post("/triage", headers=with_key(TEST_KEY), json={})
    assert response.status_code == 422
    assert TEST_KEY not in response.text + str(dict(response.headers))


# --- criterion 23: authentication happens before the body is parsed -------
# FastAPI parses JSON syntax before it resolves dependencies, so a dependency
# alone answers 422/400 to a malformed body even for a bad key. The middleware
# on POST /triage closes that gap. These tests make sure it stays closed.

JSON_CT = {"Content-Type": "application/json"}

# name -> (request kwargs, status the SAME body gets with a good key)
BAD_BODIES = {
    "no-body": (dict(), 422),
    "empty-object": (dict(json={}), 422),
    "empty-text": (dict(json={"enquiry_text": ""}), 422),
    "blank-text": (dict(json={"enquiry_text": "   "}), 422),
    "20000-chars": (dict(json={"enquiry_text": "x" * 20_000}), 422),
    "wrong-type": (dict(json={"enquiry_text": 5}), 422),
    "json-list": (dict(json=[1, 2]), 422),
    "text-plain": (dict(content=b"hello", headers={"Content-Type": "text/plain"}), 422),
    "empty-body-json": (dict(content=b"", headers=JSON_CT), 422),
    "malformed-json": (dict(content=b"{not json", headers=JSON_CT), 422),
    "invalid-utf8": (dict(content=b"\xff\xfe\xfd", headers=JSON_CT), 400),
}


def send(client: TestClient, kwargs: dict, key: str | None, **extra):
    kwargs = dict(kwargs)
    headers = dict(kwargs.pop("headers", {}))
    if key is not None:
        headers.update(with_key(key))
    return client.post("/triage", headers=headers, **kwargs, **extra)


@pytest.mark.parametrize("key", ["wrong-key", None], ids=["wrong-key", "missing-key"])
@pytest.mark.parametrize("name", BAD_BODIES)
def test_bad_key_is_401_whatever_the_body(api, stub, connections, name, key):
    kwargs, _ = BAD_BODIES[name]
    response = send(api, kwargs, key)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key."}
    assert stub.calls == []
    assert_nothing_stored(connections)


@pytest.mark.parametrize("key", ["wrong-key", None, TEST_KEY], ids=["wrong-key", "missing-key", "plausible-key"])
@pytest.mark.parametrize("name", BAD_BODIES)
def test_unconfigured_key_is_503_whatever_the_body(api, stub, connections, monkeypatch, name, key):
    monkeypatch.setattr(config, "API_KEY", "")
    kwargs, _ = BAD_BODIES[name]
    response = send(api, kwargs, key)
    assert response.status_code == 503
    assert stub.calls == []
    assert_nothing_stored(connections)


@pytest.mark.parametrize("name", BAD_BODIES)
def test_control_the_same_bodies_are_rejected_for_a_good_key(api, stub, connections, name):
    # Without this, a 401 above could pass vacuously on a body that was fine.
    kwargs, expected = BAD_BODIES[name]
    response = send(api, kwargs, TEST_KEY)
    assert response.status_code == expected
    assert stub.calls == []
    assert_nothing_stored(connections)


def test_trailing_slash_does_not_get_past_the_auth_check(api, stub, connections):
    response = api.post("/triage/", headers=with_key("wrong-key"),
                        json={"enquiry_text": "hello"}, follow_redirects=False)
    assert response.status_code == 401  # not a 307 redirect to an unchecked route
    assert_nothing_stored(connections)


def test_only_post_triage_is_guarded(api, stub):
    assert api.get("/openapi.json").status_code == 200
    assert api.get("/docs").status_code == 200
    assert api.get("/triage").status_code == 405  # wrong method, not an auth answer


def build_app(*, dependency: bool, middleware: bool) -> tuple[FastAPI, list]:
    """A throwaway app with a real body model, to compare the two auth paths."""
    reached: list[TriageRequest] = []
    throwaway = FastAPI()
    if middleware:
        throwaway.middleware("http")(auth.authenticate_triage_post)

    @throwaway.post("/triage", dependencies=[Depends(require_api_key)] if dependency else [])
    def route(body: TriageRequest):
        reached.append(body)
        return {"ok": True}

    return throwaway, reached


def test_middleware_rejects_a_bad_key_before_the_body_or_route_is_reached():
    throwaway, reached = build_app(dependency=False, middleware=True)
    client = TestClient(throwaway)
    for kwargs, _ in BAD_BODIES.values():
        assert send(client, kwargs, "wrong-key").status_code == 401
    assert reached == []
    good = send(client, dict(json={"enquiry_text": "hello"}), TEST_KEY)
    assert good.status_code == 200 and len(reached) == 1  # a good key passes straight through


def test_dependency_alone_answers_a_malformed_body_before_auth():
    # Characterisation of FastAPI (why the middleware exists). If a future
    # FastAPI changes this, the middleware may be removable: revisit then.
    throwaway, reached = build_app(dependency=True, middleware=False)
    client = TestClient(throwaway)
    assert send(client, BAD_BODIES["malformed-json"][0], "wrong-key").status_code == 422
    assert send(client, BAD_BODIES["invalid-utf8"][0], "wrong-key").status_code == 400
    assert send(client, BAD_BODIES["20000-chars"][0], "wrong-key").status_code == 401
    assert reached == []


def direct_decision(supplied: str | None) -> tuple[int, str | None]:
    try:
        require_api_key(supplied)
    except HTTPException as exc:
        return exc.status_code, exc.detail
    return 200, None


def http_decision(client: TestClient, header: str | bytes | None) -> tuple[int, str | None]:
    headers = {} if header is None else {"X-API-Key": header}
    response = client.post("/triage", headers=headers, json={"enquiry_text": "hello"})
    if response.status_code == 200:
        return 200, None
    return response.status_code, response.json()["detail"]


@pytest.mark.parametrize("configured", [TEST_KEY, ""], ids=["configured", "unconfigured"])
@pytest.mark.parametrize("header", [TEST_KEY, "wrong-key", None, "", "café".encode("utf-8")],
                         ids=["good", "wrong", "missing", "empty", "non-ascii"])
def test_dependency_and_middleware_give_the_same_decision(api, stub, monkeypatch, configured, header):
    monkeypatch.setattr(config, "API_KEY", configured)
    supplied = header.decode("latin-1") if isinstance(header, bytes) else header  # as Starlette reads it
    expected = direct_decision(supplied)
    dependency_only, _ = build_app(dependency=True, middleware=False)
    middleware_only, _ = build_app(dependency=False, middleware=True)
    assert http_decision(TestClient(dependency_only), header) == expected
    assert http_decision(TestClient(middleware_only), header) == expected
    assert http_decision(api, header) == expected
