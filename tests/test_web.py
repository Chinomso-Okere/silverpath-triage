"""Demo layer tests. Zero API calls and zero network calls. This step covers the
new config settings and the notification model only; the guards, the Slack
service and the /demo routes are added in later steps."""
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from silverpath_triage import config
from silverpath_triage.models.notify import NotificationResult, NotificationStatus


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
