# Technical PRD — Silverpath Inbound-Enquiry Triage (Build #1)

Built from AI Build Playbook docs 01 (stack) and 02 (structure). Where this
doc and general habit disagree, this doc wins for this build.

## Stack (only what this build needs)
| Concern | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.12 | Set via `.python-version` |
| Env & deps | **uv** | Manages Python version, venv, and packages |
| Structured data | **Pydantic** | Every output shape is a Pydantic model |
| AI layer | **Anthropic Python SDK** (`anthropic`) | The one Claude call |
| Model | **`claude-haiku-5-5`** | Anthropic designates Haiku for classification, extraction, and routing — exactly this task — and it's the cheapest model. The model string lives in `config.py` so it can be swapped in one line. |
| Secrets | **python-dotenv** + `.env` | Loads `ANTHROPIC_API_KEY` at runtime |
| Tests/evals | **pytest** (dev dependency) | Runs the eval set; test-only, installed with `--dev` |

No FastAPI, no database, no Celery, no frontend, no observability tooling —
none is needed for a local PoC script. (Playbook 01: add layers only when the
build needs them.)

## How the structured output works (important — current method)
Use the SDK's native structured-outputs feature, NOT a manual tool-use or
JSON-parsing workaround:

- Call `client.messages.parse(model=..., max_tokens=1024, output_format=TriageResult, messages=[...])`.
- Read the validated result from `response.parsed_output` — it is already a
  `TriageResult` instance. No manual `json.loads`, no retry-on-bad-JSON.

Gotchas to respect (from Anthropic's structured-outputs docs):
- **Keep `reasoning` a short explanation**, phrased as "a one-sentence
  explanation", not "step-by-step reasoning" — asking a schema field for
  detailed chain-of-thought can trigger a refusal. One short sentence is fine.
- **Handle non-ideal responses.** Check the response's stop reason; if it is a
  refusal or hit the token limit, `parsed_output` may be absent. Fail cleanly
  with a clear message rather than assuming success. (This satisfies the
  "handles errors" review criterion.)
- Numeric bounds on `confidence` (0–1) are enforced by Pydantic validation; the
  SDK handles the schema translation. Use `Field(ge=0, le=1, ...)`.

## Data shapes (the Pydantic models — `src/silverpath_triage/models/triage.py`)
The LLM fills `TriageResult`. Note: `needs_review` is NOT in this model — it is
computed in code after the call (see "The deterministic rule").

```python
from enum import Enum
from pydantic import BaseModel, Field

class Intent(str, Enum):
    new_enquiry = "new_enquiry"
    existing_customer = "existing_customer"
    complaint = "complaint"
    billing = "billing"
    spam = "spam"
    other = "other"

class Urgency(str, Enum):
    low = "low"; medium = "medium"; high = "high"

class Route(str, Enum):
    sales = "sales"; support = "support"; billing = "billing"
    human_review = "human_review"; ignore = "ignore"

class ContactInfo(BaseModel):
    phone: str | None = None
    email: str | None = None

class KeyDetails(BaseModel):
    customer_name: str | None = None
    requested_service: str | None = None
    deadline_or_date: str | None = None
    location_or_postcode: str | None = None
    contact_info: ContactInfo = Field(default_factory=ContactInfo)

class TriageResult(BaseModel):
    intent: Intent
    urgency: Urgency
    summary: str
    key_details: KeyDetails
    suggested_route: Route
    confidence: float = Field(ge=0, le=1,
        description="0 to 1 confidence in the intent/route decision")
    reasoning: str = Field(description="one short sentence on why")
```

The final saved/printed record is the `TriageResult` plus the code-computed
`needs_review` boolean. Exact representation (wrapper model vs. augmented dict)
is for Claude Code to propose in plan mode — keep it typed and simple.

## The deterministic rule (the teaching beat)
`config.py` holds `CONFIDENCE_THRESHOLD` (start at 0.6). After the model returns
`TriageResult`, plain Python sets:
`needs_review = result.confidence < CONFIDENCE_THRESHOLD`.
The model judges; code decides escalation. No LLM call for this.

## Folder structure (playbook 02, instantiated)
```
silverpath-triage/
├── src/
│   └── silverpath_triage/
│       ├── __init__.py
│       ├── main.py          # entry point: load enquiry → triage → print + save JSON
│       ├── config.py        # loads .env; holds MODEL, CONFIDENCE_THRESHOLD, paths
│       ├── models/
│       │   ├── __init__.py
│       │   └── triage.py    # the Pydantic models above
│       ├── prompts/
│       │   ├── __init__.py
│       │   └── triage_prompt.py   # the triage instruction prompt, kept out of logic
│       └── services/
│           ├── __init__.py
│           └── triage.py    # the messages.parse() call + needs_review rule
├── data/
│   ├── samples/             # sample raw enquiries (inputs)
│   └── outputs/             # saved JSON results (gitignored)
├── tests/
│   └── test_triage_evals.py # the ~8–10 hand-made eval cases
├── docs/
│   ├── PRD.md
│   └── TECHNICAL_PRD.md
├── .env                     # ANTHROPIC_API_KEY — NEVER committed
├── .env.example             # blank template, safe to commit
├── .gitignore               # must list .env, .venv/, data/outputs/
├── .python-version
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

## Environment setup steps
1. `uv init` the project; set Python 3.12 in `.python-version`.
2. `uv add anthropic pydantic python-dotenv`, then `uv add --dev pytest`
   (pytest is a test-only dev dependency, kept out of runtime deps).
3. Create `.gitignore` FIRST, containing `.env`, `.venv/`, `data/outputs/`.
4. Create `.env` with `ANTHROPIC_API_KEY=...` and `.env.example` with the key
   name blank.
5. `git init` and make the first commit — the clean baseline.

## Secrets
- Only `ANTHROPIC_API_KEY`, in `.env`, loaded via `config.py`. Never hardcoded,
  never printed, never committed. `.gitignore` must contain `.env` before the
  first commit.

## Build sequence (small, reviewable, commit before & after each)
1. **Scaffold + env** — structure, uv, `.env`, `.gitignore`, first commit.
   *(teaches: uv, secrets)*
2. **Models** — write `models/triage.py`. *(teaches: structured shapes)*
3. **Core call** — write the prompt + `services/triage.py` using
   `messages.parse`. Test on ONE sample enquiry before anything else.
   *(teaches: first Claude call + structured outputs)*
4. **Rule + wiring** — add the `needs_review` threshold rule and `main.py`
   (print + save JSON). *(teaches: deterministic vs LLM, file I/O)*
5. **Evals** — write ~8–10 cases in `tests/` and run with pytest.
   *(teaches: first eval)*

## Cost & safety
- Model usage is pennies for the whole build. Still: set a spending cap in the
  Anthropic console before running anything.
- Never point an untested loop at the API — step 3 tests on a single enquiry
  first; the eval loop (step 5) runs only after the single call is proven.