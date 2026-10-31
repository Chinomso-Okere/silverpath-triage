"""API layer tests. Zero API calls (the Anthropic client constructor fails the
test if called). So far: model-level checks and the auth dependency, with no
database. The auth tests mount it on a throwaway app built here, not on /triage."""
import logging
import os
import secrets
import subprocess
import sys

import anthropic
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from silverpath_triage import config
from silverpath_triage.api import auth
from silverpath_triage.api.auth import require_api_key
from silverpath_triage.models.api import TriageRequest, TriageResponse
from silverpath_triage.models.triage import (
    ContactInfo, Intent, KeyDetails, Route, TriageRecord, Urgency,
)


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
