import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"
DB_PATH = PROJECT_ROOT / "data" / "triage.db"

load_dotenv(PROJECT_ROOT / ".env")

# Checked when the Claude client is created (services/triage.py), not here,
# so commands and tests that never call Claude don't need a key.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

# Checked at request time by api/auth.py (fail-closed if blank), not here.
API_KEY = os.environ.get("SILVERPATH_API_KEY", "").strip()
MAX_ENQUIRY_CHARS = 10_000  # one home for the cap; TriageRequest references it

# Fixed address of this app's own API. Never derived from the request, its Host
# header or request.base_url (that would let a forged header redirect the key).
TRIAGE_API_URL = "http://127.0.0.1:8000"
TRIAGE_TIMEOUT_SECONDS = 60.0   # a Claude call can exceed httpx's 5s default

# Read at call time by services/notify.py (config.WEBHOOK_URL, not imported by
# value). Blank means "not configured": the page says so, nothing is sent.
WEBHOOK_URL = os.environ.get("SILVERPATH_WEBHOOK_URL", "").strip()
WEBHOOK_TIMEOUT_SECONDS = 10.0

MODEL = "claude-haiku-5-5"
CONFIDENCE_THRESHOLD = 0.6  # needs_review is True when confidence is below this
