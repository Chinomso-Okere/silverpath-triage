"""API layer tests. Zero API calls (the Anthropic client constructor fails the
test if called). Step 1: model-level checks only, no app and no database."""
import os
import subprocess
import sys

import anthropic
import pytest
from pydantic import ValidationError

from silverpath_triage import config
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
