"""Demo layer tests. Zero API calls (the Anthropic client constructor fails the
test if called; triage is stubbed), zero network calls (the triage client is
routed into the real app in memory with httpx.ASGITransport, the webhook client
to httpx.MockTransport) and no real database (a temp file, with the real-database
guard). Config settings, the notification model, the Slack notification service,
then the /demo routes."""
import ast
import asyncio
import inspect
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from silverpath_triage import config
from silverpath_triage.api.app import app
from silverpath_triage.models.api import TriageResponse
from silverpath_triage.models.notify import NotificationResult, NotificationStatus
from silverpath_triage.models.triage import (
    ContactInfo, Intent, KeyDetails, Route, TriageResult, Urgency,
)
from silverpath_triage.services import notify, storage
from silverpath_triage.services import triage as triage_service
from silverpath_triage.services.storage import StorageError
from silverpath_triage.services.triage import TriageError
from silverpath_triage.web import routes

FAKE_WEBHOOK_URL = "https://hooks.slack.test/services/T000/B000/fake"


TEST_KEY = "test-key-web-123"  # fake test value
REAL_DB = config.DB_PATH.resolve()  # captured at import, before temp_db patches it


@pytest.fixture(autouse=True)
def fake_webhook_url(monkeypatch):
    # No test in this file ever sees the real .env value; tests may override it.
    monkeypatch.setattr(config, "WEBHOOK_URL", FAKE_WEBHOOK_URL)


# Guards, as in test_api.py: no Claude client, a test key, a temp database and
# a failure if anything opens the real one.

@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Anthropic client was created")

    monkeypatch.setattr(anthropic, "Anthropic", fail_if_called)


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", TEST_KEY)


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


# --- the /demo web layer --------------------------------------------------
# Real app, driven by TestClient. The form handler's triage client is routed
# into the same app in memory (ASGITransport), so each test runs the real
# middleware, auth, validation, error handlers and /triage route with only
# triage stubbed. The webhook client is a FakeWebhook. No network.

ENQUIRY = "Hi, could you quote for a garden clearance next month? WEB-ENQUIRY-MARK"
BANNER = "Escalated: a person must see this enquiry"


def make_result(route: Route = Route.sales, confidence: float = 0.87) -> TriageResult:
    return TriageResult(
        intent=Intent.new_enquiry,
        urgency=Urgency.medium,
        summary="Wants a quote for a garden clearance next month.",
        key_details=KeyDetails(
            customer_name="Ada Example",
            requested_service="garden clearance",
            deadline_or_date="next month",
            location_or_postcode="AB1 2CD",
            contact_info=ContactInfo(phone="01234 567890", email="ada@example.test"),
        ),
        suggested_route=route,
        confidence=confidence,
        reasoning="Clear request for a new service.",
    )


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


class Demo:
    """The test client plus what the form handler's two clients saw."""

    def __init__(self):
        self.client = TestClient(app)
        self.webhook = FakeWebhook()
        self.triage_requests: list[httpx.Request] = []
        self.triage_transport: httpx.AsyncBaseTransport | None = None  # None: the real app


@pytest.fixture
def demo(stub):
    state = Demo()

    async def record(request: httpx.Request) -> None:
        state.triage_requests.append(request)

    async def triage_client():
        transport = state.triage_transport or httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, event_hooks={"request": [record]}) as client:
            yield client

    async def webhook_client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(state.webhook)) as client:
            yield client

    app.dependency_overrides[routes.get_triage_client] = triage_client
    app.dependency_overrides[routes.get_webhook_client] = webhook_client
    yield state
    app.dependency_overrides.pop(routes.get_triage_client, None)
    app.dependency_overrides.pop(routes.get_webhook_client, None)


def submit(demo: Demo, text: str = ENQUIRY) -> httpx.Response:
    return demo.client.post("/demo", data={"enquiry_text": text})


def row(label: str, value) -> str:
    return f"<tr><th>{label}</th><td>{value}</td></tr>"


def assert_nothing_stored(connections) -> None:
    """Storage was never even opened: no connection, no database file."""
    assert connections == []
    assert not config.DB_PATH.exists()


def stored_entries() -> list:
    return storage.list_entries(limit=100, db_path=config.DB_PATH)


def assert_error_page(response, demo: Demo, message: str, status: int, text: str = ENQUIRY) -> None:
    assert response.status_code == status
    assert message in response.text
    assert f">{text}</textarea>" in response.text  # refilled so it can be corrected
    assert BANNER not in response.text
    assert demo.webhook.requests == []  # no notification on any failure


def mock_triage(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# form and result

def test_get_demo_shows_the_form(demo):
    response = demo.client.get("/demo")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert '<form method="post" action="/demo">' in page
    assert '<textarea id="enquiry_text" name="enquiry_text" required maxlength="10000"' in page
    assert '<button type="submit">' in page
    assert BANNER not in page
    assert "<table>" not in page


def test_success_shows_every_field(demo, stub):
    response = submit(demo)
    assert response.status_code == 200
    entry_id = stored_entries()[0].id
    for expected in (
        row("Entry ID", entry_id),
        row("Intent", "new_enquiry"),
        row("Urgency", "medium"),
        row("Summary", "Wants a quote for a garden clearance next month."),
        row("Suggested route", "sales"),
        row("Confidence", "0.87"),
        row("Reasoning", "Clear request for a new service."),
        row("Needs review", "no"),
        row("Escalate", "no"),
        row("Customer name", "Ada Example"),
        row("Requested service", "garden clearance"),
        row("Deadline or date", "next month"),
        row("Location or postcode", "AB1 2CD"),
        row("Phone", "01234 567890"),
        row("Email", "ada@example.test"),
    ):
        assert expected in response.text


@pytest.mark.parametrize("route, confidence, escalated", [
    (Route.sales, 0.3, True),          # model unsure (needs_review)
    (Route.human_review, 0.9, True),   # routed to a person
    (Route.sales, 0.87, False),        # confident, routed to a team
], ids=["low-confidence", "human-review", "calm"])
def test_escalation_banner_follows_the_api_field(demo, stub, route, confidence, escalated):
    stub.result = make_result(route, confidence)
    response = submit(demo)
    assert response.status_code == 200
    assert (BANNER in response.text) is escalated
    assert row("Escalate", "yes" if escalated else "no") in response.text


def test_success_stores_the_entry_with_source_web_form(demo, stub):
    response = submit(demo)
    entries = stored_entries()
    assert len(entries) == 1
    assert entries[0].source == "web-form"
    assert entries[0].enquiry_text == ENQUIRY
    assert stub.calls == [ENQUIRY]
    assert row("Entry ID", entries[0].id) in response.text


def test_success_page_does_not_refill_and_links_back(demo, stub):
    response = submit(demo)
    assert "WEB-ENQUIRY-MARK" not in response.text
    assert "<textarea" not in response.text
    assert '<a href="/demo">Submit another enquiry</a>' in response.text


# invalid input: the API's TriageRequest is the one validator

@pytest.mark.parametrize("text", ["", "   \n\t ", "x" * 10_001],
                         ids=["empty", "whitespace", "over-limit"])
def test_invalid_input_is_stopped_by_the_api(demo, stub, connections, text):
    response = submit(demo, text)
    assert_error_page(response, demo, routes.INVALID_INPUT, 422, text)
    assert len(demo.triage_requests) == 1  # forwarded; the API rejected it
    assert stub.calls == []
    assert_nothing_stored(connections)


# the front door

def test_outgoing_request_goes_to_the_fixed_api_with_key_and_source(demo, stub):
    submit(demo)
    assert len(demo.triage_requests) == 1
    request = demo.triage_requests[0]
    assert request.method == "POST"
    assert str(request.url) == config.TRIAGE_API_URL + "/triage"
    assert request.headers["X-API-Key"] == TEST_KEY
    assert json.loads(request.content) == {"enquiry_text": ENQUIRY, "source": "web-form"}
    assert request.extensions["timeout"]["read"] == config.TRIAGE_TIMEOUT_SECONDS


PACKAGE_DIR = Path(routes.__file__).resolve().parents[1]
FORBIDDEN_IMPORTS = {
    "silverpath_triage.services.triage", "silverpath_triage.services.storage",
    "silverpath_triage.api.auth", "silverpath_triage.api.app",
}
ALLOWED_IMPORTS = {
    "silverpath_triage.config", "silverpath_triage.models.api",
    "silverpath_triage.models.notify", "silverpath_triage.services.notify",
}


def project_imports(path: Path) -> list[set[str]]:
    """For each project import in the file, the names it could refer to."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [{alias.name} for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import in {path.name}"
            found += [{node.module, f"{node.module}.{alias.name}"} for alias in node.names]
    return [names for names in found if any(n.startswith("silverpath_triage") for n in names)]


def test_web_code_imports_only_allowed_modules():
    files = sorted((PACKAGE_DIR / "web").glob("*.py")) + [PACKAGE_DIR / "services" / "notify.py"]
    assert {f.name for f in files} >= {"__init__.py", "routes.py", "notify.py"}
    for path in files:
        for names in project_imports(path):
            assert not names & FORBIDDEN_IMPORTS, f"{path.name} imports {names & FORBIDDEN_IMPORTS}"
            assert names & ALLOWED_IMPORTS, f"{path.name} imports {sorted(names)}"


def test_importing_web_routes_loads_no_forbidden_module():
    # A fresh process, so modules this test file imported don't count.
    code = (
        "import sys, silverpath_triage.web.routes; "
        f"loaded = [m for m in {sorted(FORBIDDEN_IMPORTS)!r} if m in sys.modules]; "
        "assert not loaded, loaded"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# error mapping: one fixed message per API outcome, never a notification

def test_blank_api_key_shows_the_not_configured_message(demo, stub, connections, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")  # the API answers 503 (fail-closed)
    response = submit(demo)
    assert_error_page(response, demo, routes.NOT_CONFIGURED, 502)
    assert stub.calls == []
    assert_nothing_stored(connections)


def test_api_401_shows_the_not_configured_message(demo, stub):
    demo.triage_transport = mock_triage(lambda r: httpx.Response(401, json={"detail": "BODY-SENTINEL"}))
    response = submit(demo)
    assert_error_page(response, demo, routes.NOT_CONFIGURED, 502)
    assert "BODY-SENTINEL" not in response.text


def test_triage_error_shows_the_triage_failed_message(demo, stub, connections):
    stub.error = TriageError("MODEL-OUTPUT-SENTINEL")
    response = submit(demo)
    assert_error_page(response, demo, routes.TRIAGE_FAILED, 502)
    assert "MODEL-OUTPUT-SENTINEL" not in response.text
    assert_nothing_stored(connections)


def test_storage_error_shows_the_save_failed_message(demo, stub, monkeypatch):
    def fail(*args, **kwargs):
        raise StorageError("Database problem at /secret/PATH-SENTINEL/triage.db: boom")

    monkeypatch.setattr(storage, "save_entry", fail)
    response = submit(demo)
    assert_error_page(response, demo, routes.SAVE_FAILED, 502)
    assert "PATH-SENTINEL" not in response.text
    assert stub.calls == [ENQUIRY]  # triage ran; nothing was saved


def _raise(make_error):
    def handler(request):
        raise make_error(request)
    return handler


@pytest.mark.parametrize("make_error", [
    lambda r: httpx.ConnectError("EXC-SENTINEL refused", request=r),
    lambda r: httpx.ReadTimeout("EXC-SENTINEL timed out", request=r),
    lambda r: httpx.InvalidURL("EXC-SENTINEL bad url"),
], ids=["connect-error", "read-timeout", "invalid-url"])
def test_unreachable_api_shows_the_could_not_reach_message(demo, stub, make_error):
    demo.triage_transport = mock_triage(_raise(make_error))
    response = submit(demo)
    assert_error_page(response, demo, routes.UNREACHABLE, 502)
    assert "EXC-SENTINEL" not in response.text
    assert stub.calls == []


@pytest.mark.parametrize("reply", [
    lambda r: httpx.Response(200, json={"BODY-SENTINEL": 1}),
    lambda r: httpx.Response(200, text="BODY-SENTINEL not json"),
], ids=["wrong-shape", "not-json"])
def test_bad_200_body_shows_the_unexpected_message(demo, stub, reply):
    demo.triage_transport = mock_triage(reply)
    response = submit(demo)
    assert_error_page(response, demo, routes.UNEXPECTED, 502)
    assert "BODY-SENTINEL" not in response.text


@pytest.mark.parametrize("status", [404, 418])
def test_unlisted_status_shows_the_unexpected_message(demo, stub, status):
    demo.triage_transport = mock_triage(lambda r: httpx.Response(status, text="BODY-SENTINEL"))
    response = submit(demo)
    assert_error_page(response, demo, routes.UNEXPECTED, 502)
    assert "BODY-SENTINEL" not in response.text


# notification wiring

def test_success_sends_exactly_one_webhook_post(demo, stub):
    submit(demo)
    assert len(demo.webhook.requests) == 1
    request = demo.webhook.requests[0]
    assert str(request.url) == FAKE_WEBHOOK_URL
    assert f"*Entry #{stored_entries()[0].id}*" in json_body(request)["text"]


def test_escalated_submission_sends_the_loud_message(demo, stub):
    stub.result = make_result(Route.human_review, 0.9)
    submit(demo)
    assert sent_text(demo.webhook).startswith("<!here> :rotating_light:")


@pytest.mark.parametrize("webhook, url, expected", [
    (lambda: FakeWebhook(status=200), FAKE_WEBHOOK_URL, NotificationStatus.sent),
    (lambda: FakeWebhook(status=500), FAKE_WEBHOOK_URL, NotificationStatus.rejected),
    (lambda: FakeWebhook(error=lambda r: httpx.ConnectError("refused", request=r)),
     FAKE_WEBHOOK_URL, NotificationStatus.unreachable),
    (lambda: FakeWebhook(), "", NotificationStatus.not_configured),
], ids=["sent", "rejected", "unreachable", "not-configured"])
def test_page_shows_the_fixed_notification_status(demo, stub, monkeypatch, webhook, url, expected):
    monkeypatch.setattr(config, "WEBHOOK_URL", url)
    demo.webhook = webhook()
    response = submit(demo)
    assert response.status_code == 200  # the result is shown whatever Slack did
    assert row("Summary", "Wants a quote for a garden clearance next month.") in response.text
    assert routes.NOTIFICATION_TEXT[expected] in response.text
    assert len(demo.webhook.requests) == (0 if expected is NotificationStatus.not_configured else 1)


def test_every_notification_status_has_fixed_page_text():
    assert set(routes.NOTIFICATION_TEXT) == set(NotificationStatus)


def test_demo_routes_are_not_in_the_openapi_schema():
    paths = app.openapi()["paths"]
    assert "/demo" not in paths
    assert "/triage" in paths


# --- safety: secrets, fixed address, escaping ------------------------------
# Each of these was seen to fail against a deliberately broken version first.

SECRET_KEY = "KEY-SENTINEL-4d2b8e"
SECRET_WEBHOOK_TOKEN = "WEBHOOK-SENTINEL-91c7e0"
SECRET_WEBHOOK_URL = f"https://hooks.slack.test/services/{SECRET_WEBHOOK_TOKEN}"
BOTH_SECRETS = f"{SECRET_KEY} {SECRET_WEBHOOK_URL}"  # planted in errors and bodies

# id -> (drive(demo, stub, monkeypatch) -> response, page status, fixed page text).
# The status and text prove each case reached the path it is named after.
SECRET_SCENARIOS = {}


def secret_scenario(case_id: str, status: int, marker: str):
    def register(drive):
        SECRET_SCENARIOS[case_id] = (drive, status, marker)
        return drive
    return register


@secret_scenario("get-form", 200, 'name="enquiry_text"')
def _get_form(demo, stub, monkeypatch):
    return demo.client.get("/demo")


@secret_scenario("success-sent", 200, routes.NOTIFICATION_TEXT[NotificationStatus.sent])
def _success_sent(demo, stub, monkeypatch):
    return submit(demo)


@secret_scenario("invalid-422", 422, routes.INVALID_INPUT)
def _invalid(demo, stub, monkeypatch):
    return submit(demo, "   ")


@secret_scenario("blank-key-503", 502, routes.NOT_CONFIGURED)
def _blank_key(demo, stub, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    return submit(demo)


@secret_scenario("api-401", 502, routes.NOT_CONFIGURED)
def _api_401(demo, stub, monkeypatch):
    demo.triage_transport = mock_triage(lambda r: httpx.Response(401, json={"detail": BOTH_SECRETS}))
    return submit(demo)


@secret_scenario("triage-error", 502, routes.TRIAGE_FAILED)
def _triage_error(demo, stub, monkeypatch):
    stub.error = TriageError(BOTH_SECRETS)
    return submit(demo)


@secret_scenario("storage-error", 502, routes.SAVE_FAILED)
def _storage_error(demo, stub, monkeypatch):
    def fail(*args, **kwargs):
        raise StorageError(BOTH_SECRETS)

    monkeypatch.setattr(storage, "save_entry", fail)
    return submit(demo)


@secret_scenario("connect-error", 502, routes.UNREACHABLE)
def _connect_error(demo, stub, monkeypatch):
    demo.triage_transport = mock_triage(_raise(lambda r: httpx.ConnectError(BOTH_SECRETS, request=r)))
    return submit(demo)


@secret_scenario("read-timeout", 502, routes.UNREACHABLE)
def _read_timeout(demo, stub, monkeypatch):
    demo.triage_transport = mock_triage(_raise(lambda r: httpx.ReadTimeout(BOTH_SECRETS, request=r)))
    return submit(demo)


@secret_scenario("invalid-url", 502, routes.UNREACHABLE)
def _invalid_url_api(demo, stub, monkeypatch):
    demo.triage_transport = mock_triage(_raise(lambda r: httpx.InvalidURL(BOTH_SECRETS)))
    return submit(demo)


@secret_scenario("bad-200-body", 502, routes.UNEXPECTED)
def _bad_200(demo, stub, monkeypatch):
    demo.triage_transport = mock_triage(lambda r: httpx.Response(200, json={"leak": BOTH_SECRETS}))
    return submit(demo)


@secret_scenario("unlisted-418", 502, routes.UNEXPECTED)
def _unlisted(demo, stub, monkeypatch):
    demo.triage_transport = mock_triage(lambda r: httpx.Response(418, text=BOTH_SECRETS))
    return submit(demo)


@secret_scenario("webhook-rejected", 200, routes.NOTIFICATION_TEXT[NotificationStatus.rejected])
def _webhook_rejected(demo, stub, monkeypatch):
    demo.webhook = FakeWebhook(status=500)
    return submit(demo)


@secret_scenario("webhook-unreachable", 200, routes.NOTIFICATION_TEXT[NotificationStatus.unreachable])
def _webhook_unreachable(demo, stub, monkeypatch):
    demo.webhook = FakeWebhook(error=lambda r: httpx.ConnectError(BOTH_SECRETS, request=r))
    return submit(demo)


@pytest.mark.parametrize("case_id", SECRET_SCENARIOS)
def test_secrets_never_reach_pages_or_logs(demo, stub, monkeypatch, caplog, case_id):
    # Root logger only: setting a level on "httpx" here would override the
    # protection under test.
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(config, "API_KEY", SECRET_KEY)
    monkeypatch.setattr(config, "WEBHOOK_URL", SECRET_WEBHOOK_URL)
    drive, status, marker = SECRET_SCENARIOS[case_id]
    response = drive(demo, stub, monkeypatch)
    assert response.status_code == status
    assert marker in response.text
    headers = str(dict(response.headers))
    for secret in (SECRET_KEY, SECRET_WEBHOOK_TOKEN):
        assert secret not in response.text
        assert secret not in headers
        assert secret not in caplog.text


def test_env_example_holds_no_values():
    lines = (config.PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    settings = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    assert all(line.endswith("=") for line in settings), settings
    assert {line[:-1] for line in settings} == {
        "ANTHROPIC_API_KEY", "SILVERPATH_API_KEY", "SILVERPATH_WEBHOOK_URL",
    }


def test_forged_host_header_cannot_redirect_the_api_call(demo, stub):
    response = demo.client.post(
        "/demo", data={"enquiry_text": ENQUIRY}, headers={"Host": "evil.example"},
    )
    assert len(demo.triage_requests) == 1
    url = demo.triage_requests[0].url
    assert str(url) == config.TRIAGE_API_URL + "/triage"
    assert (url.host, url.port) == ("127.0.0.1", 8000)
    assert response.status_code == 200


XSS = '<script>alert("xss")</script><b>x</b>'


def test_model_output_is_shown_escaped(demo, stub):
    result = make_result()
    stub.result = result.model_copy(update={
        "summary": XSS,
        "reasoning": XSS,
        "key_details": result.key_details.model_copy(update={"customer_name": XSS}),
    })
    page = submit(demo).text
    assert "<script>alert" not in page
    assert "<b>x</b>" not in page
    assert "&lt;script&gt;" in page
    assert page.count("&lt;script&gt;") == 3  # summary, reasoning, customer name


def test_refilled_input_is_shown_escaped(demo, stub):
    prefix = '</textarea><script>alert("xss")</script>'
    text = prefix + "x" * (10_001 - len(prefix))  # over the cap, so it is echoed back
    response = submit(demo, text)
    assert response.status_code == 422
    assert routes.INVALID_INPUT in response.text
    page = response.text
    assert "<script>alert" not in page
    assert "</textarea><script>" not in page
    assert "<b>x</b>" not in page
    assert "&lt;/textarea&gt;&lt;script&gt;" in page


def test_template_has_no_escape_bypass():
    template = (PACKAGE_DIR / "web" / "templates" / "demo.html").read_text(encoding="utf-8")
    assert not re.search(r"\|\s*safe\b", template)
    for banned in ("Markup", "autoescape", "<script"):
        assert banned not in template
