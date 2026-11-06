"""Demo layer tests. Zero API calls and zero network calls (the webhook client
uses httpx.MockTransport). Config settings, the notification model and the
Slack notification service; the guards and the /demo routes come later."""
import asyncio
import inspect
import json
import logging
import os
import subprocess
import sys

import httpx
import pytest
from pydantic import ValidationError

from silverpath_triage import config
from silverpath_triage.models.api import TriageResponse
from silverpath_triage.models.notify import NotificationResult, NotificationStatus
from silverpath_triage.models.triage import ContactInfo, Intent, KeyDetails, Route, Urgency
from silverpath_triage.services import notify

FAKE_WEBHOOK_URL = "https://hooks.slack.test/services/T000/B000/fake"


@pytest.fixture(autouse=True)
def fake_webhook_url(monkeypatch):
    # No test in this file ever sees the real .env value; tests may override it.
    monkeypatch.setattr(config, "WEBHOOK_URL", FAKE_WEBHOOK_URL)


# --- config ---------------------------------------------------------------

def test_triage_api_url_is_fixed_localhost_8000():
    assert config.TRIAGE_API_URL == "http://127.0.0.1:8000"


def test_triage_timeout_is_60_seconds():
    assert config.TRIAGE_TIMEOUT_SECONDS == 60.0


def test_webhook_timeout_is_10_seconds():
    assert config.WEBHOOK_TIMEOUT_SECONDS == 10.0


@pytest.mark.parametrize("value, expected", [
    ("", ""),
    ("  https://hooks.slack.test/x  ", "https://hooks.slack.test/x"),
])
def test_webhook_url_is_read_from_env_and_stripped(value, expected):
    # A fresh process, because config is already imported here. The variable is
    # set explicitly (load_dotenv doesn't override it), so .env is never used.
    env = {**os.environ, "SILVERPATH_WEBHOOK_URL": value}
    result = subprocess.run(
        [sys.executable, "-c",
         f"import silverpath_triage.config as c; assert c.WEBHOOK_URL == {expected!r}"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


# --- NotificationResult ---------------------------------------------------

def test_notification_status_values():
    assert {s.name: s.value for s in NotificationStatus} == {
        "sent": "sent",
        "not_configured": "not_configured",
        "unreachable": "unreachable",
        "rejected": "rejected",
    }


def test_notification_result_holds_status_and_loud():
    result = NotificationResult(status="sent", loud=True)
    assert result.status is NotificationStatus.sent
    assert result.loud is True


def test_notification_result_rejects_unknown_status():
    with pytest.raises(ValidationError):
        NotificationResult(status="delivered", loud=False)


@pytest.mark.parametrize("fields", [{"status": "sent"}, {"loud": False}])
def test_notification_result_requires_both_fields(fields):
    with pytest.raises(ValidationError):
        NotificationResult(**fields)


# --- Slack notification ---------------------------------------------------

def make_response(**overrides) -> TriageResponse:
    fields = dict(
        entry_id=42,
        intent=Intent.new_enquiry,
        urgency=Urgency.medium,
        summary="Wants a quote for a garden clearance next month.",
        key_details=KeyDetails(
            customer_name="Zelda Quickfoot",
            requested_service="Distinctive service",
            deadline_or_date="Distinctive date",
            location_or_postcode="ZZ9 9ZZ",
            contact_info=ContactInfo(phone="07000 111222", email="zelda@example.test"),
        ),
        suggested_route=Route.sales,
        confidence=0.87,
        reasoning="Distinctive reasoning phrase.",
        needs_review=False,
        escalate=False,
    )
    return TriageResponse(**{**fields, **overrides})


class FakeWebhook:
    """MockTransport handler: records each request, then answers `status` or
    raises `error(request)`."""

    def __init__(self, status: int = 200, error=None):
        self.status = status
        self.error = error
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error(request)
        return httpx.Response(self.status, text="ok")


def send(response: TriageResponse, webhook: FakeWebhook) -> NotificationResult:
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(webhook)) as client:
            return await notify.notify_slack(response, client)

    return asyncio.run(run())


def json_body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def sent_text(webhook: FakeWebhook) -> str:
    return json_body(webhook.requests[0])["text"]


def test_slack_escape_escapes_angle_brackets_and_ampersand():
    assert notify.slack_escape("<a> & <b>") == "&lt;a&gt; &amp; &lt;b&gt;"


def test_slack_escape_does_ampersand_first():
    assert notify.slack_escape("&lt;") == "&amp;lt;"


def test_one_post_with_a_json_text_and_the_configured_timeout():
    webhook = FakeWebhook()
    send(make_response(), webhook)
    assert len(webhook.requests) == 1
    request = webhook.requests[0]
    assert request.method == "POST"
    assert str(request.url) == config.WEBHOOK_URL
    body = json_body(request)
    assert list(body) == ["text"]
    assert isinstance(body["text"], str)
    assert request.extensions["timeout"]["read"] == config.WEBHOOK_TIMEOUT_SECONDS


def test_escalated_message_is_loud():
    webhook = FakeWebhook()
    result = send(make_response(escalate=True), webhook)
    assert sent_text(webhook).startswith("<!here> :rotating_light: *ESCALATE*")
    assert result.loud is True


def test_calm_message_has_no_markers():
    webhook = FakeWebhook()
    result = send(make_response(escalate=False), webhook)
    text = sent_text(webhook)
    assert "<!here>" not in text
    assert ":rotating_light:" not in text
    assert result.loud is False


@pytest.mark.parametrize("overrides, loud", [
    ({"suggested_route": Route.human_review, "escalate": False}, False),
    ({"suggested_route": Route.sales, "confidence": 0.95, "escalate": True}, True),
])
def test_format_follows_the_escalate_field_not_a_recomputation(overrides, loud):
    text = notify.build_slack_text(make_response(**overrides))
    assert ("<!here>" in text) is loud


def test_model_text_is_escaped_so_only_our_here_can_ping():
    summary = "Call <!channel> and <@U123> & co"
    loud = notify.build_slack_text(make_response(summary=summary, escalate=True))
    calm = notify.build_slack_text(make_response(summary=summary, escalate=False))
    for text in (loud, calm):
        assert "&lt;!channel&gt;" in text
        assert "&lt;@U123&gt;" in text
        assert "&amp; co" in text
    assert loud.count("<") == 1 and loud.startswith("<!here>")
    assert "<" not in calm


def test_message_carries_the_labels_and_summary():
    text = notify.build_slack_text(make_response())
    for part in ("*Entry #42*", "intent: new_enquiry", "urgency: medium",
                 "route: sales", "confidence: 0.87",
                 "Summary: Wants a quote for a garden clearance next month."):
        assert part in text


@pytest.mark.parametrize("confidence, shown", [(0.8, "0.80"), (0.876, "0.88")])
def test_confidence_is_shown_to_two_decimals(confidence, shown):
    assert f"confidence: {shown}" in notify.build_slack_text(make_response(confidence=confidence))


def test_message_has_no_key_details_or_reasoning():
    text = notify.build_slack_text(make_response())
    for value in ("Zelda Quickfoot", "Distinctive service", "Distinctive date", "ZZ9 9ZZ",
                  "07000 111222", "zelda@example.test", "Distinctive reasoning phrase"):
        assert value not in text


def test_message_cannot_carry_enquiry_text():
    # By construction: the only input is a TriageResponse, which has no enquiry text.
    assert "enquiry_text" not in TriageResponse.model_fields
    assert list(inspect.signature(notify.build_slack_text).parameters) == ["response"]


def _invalid_url(request):
    return httpx.InvalidURL("bad webhook url")


@pytest.mark.parametrize("webhook, expected", [
    (FakeWebhook(status=200), NotificationStatus.sent),
    (FakeWebhook(status=400), NotificationStatus.rejected),
    (FakeWebhook(status=403), NotificationStatus.rejected),
    (FakeWebhook(status=404), NotificationStatus.rejected),
    (FakeWebhook(status=500), NotificationStatus.rejected),
    (FakeWebhook(error=lambda r: httpx.ConnectError("refused", request=r)),
     NotificationStatus.unreachable),
    (FakeWebhook(error=lambda r: httpx.ReadTimeout("timed out", request=r)),
     NotificationStatus.unreachable),
    (FakeWebhook(error=_invalid_url), NotificationStatus.unreachable),
], ids=["200", "400", "403", "404", "500", "connect-error", "read-timeout", "invalid-url"])
def test_status_mapping_with_exactly_one_attempt(webhook, expected):
    result = send(make_response(), webhook)
    assert result.status is expected
    assert len(webhook.requests) == 1  # no retries


def test_blank_url_is_not_configured_and_sends_nothing(monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_URL", "")
    webhook = FakeWebhook()
    result = send(make_response(escalate=True), webhook)
    assert result.status is NotificationStatus.not_configured
    assert webhook.requests == []


SENTINEL_TOKEN = "SENTINEL-WEBHOOK-7f3c9a"
SENTINEL_URL = f"https://hooks.slack.test/services/{SENTINEL_TOKEN}"


def test_secret_webhook_url_never_appears_in_logs(monkeypatch, caplog):
    # Root logger only: setting a level on "httpx" here would override the
    # protection under test.
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(config, "WEBHOOK_URL", SENTINEL_URL)
    cases = [
        FakeWebhook(status=200),
        FakeWebhook(status=500),
        FakeWebhook(error=lambda r: httpx.ConnectError(f"cannot reach {SENTINEL_URL}", request=r)),
        FakeWebhook(error=lambda r: httpx.InvalidURL(f"bad url {SENTINEL_URL}")),
    ]
    for webhook in cases:
        send(make_response(), webhook)
        assert len(webhook.requests) == 1
    assert SENTINEL_TOKEN not in caplog.text
