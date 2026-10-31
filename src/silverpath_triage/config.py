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

MODEL = "claude-haiku-5-5"
CONFIDENCE_THRESHOLD = 0.6  # needs_review is True when confidence is below this
