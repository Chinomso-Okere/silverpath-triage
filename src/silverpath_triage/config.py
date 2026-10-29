import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"

load_dotenv(PROJECT_ROOT / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is missing or blank. Add it to the .env file in the "
        "project root (see .env.example), then try again."
    )

MODEL = "claude-haiku-5-5"
CONFIDENCE_THRESHOLD = 0.6  # defined now; used from step 4 (needs_review rule)
