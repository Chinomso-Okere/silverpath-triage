"""Config proofs: a missing key doesn't stop import, but still stops a triage
before any client is created. Zero API calls."""
import os
import subprocess
import sys

import anthropic
import pytest

from silverpath_triage import config
from silverpath_triage.services.triage import TriageError, triage_enquiry


def test_import_config_without_key_does_not_raise():
    # A fresh process, because config is already imported here with the real
    # key. The empty variable is kept by load_dotenv (it doesn't override), so
    # the key in .env is never loaded; the assert proves it really is blank.
    env = {**os.environ, "ANTHROPIC_API_KEY": ""}
    result = subprocess.run(
        [sys.executable, "-c",
         "import silverpath_triage.config as c; assert c.ANTHROPIC_API_KEY == ''"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_triage_without_key_fails_before_client_is_created(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Anthropic client was created despite a blank key")

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(anthropic, "Anthropic", fail_if_called)

    with pytest.raises(TriageError, match="ANTHROPIC_API_KEY"):
        triage_enquiry("some text")
