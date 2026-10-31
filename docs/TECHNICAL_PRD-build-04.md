# Technical PRD — Silverpath Inbound-Enquiry Triage, Build #4: API layer

The *how* for `docs/PRD-build-04.md`. Earlier builds' docs are background and
are not edited. Where this doc and general habit disagree, this doc wins for
this build. Anything not covered here: stop and ask.

## Stack
Python 3.12, uv, Pydantic, Anthropic SDK, python-dotenv, SQLite via `sqlite3`,
`argparse`, pytest (dev) — **unchanged**. Model (`claude-haiku-5-5`), prompt and
threshold (0.6) are unchanged.

**New dependencies (approved):**
- `fastapi` — the API framework (runtime)
- `uvicorn` — the ASGI server that runs it (runtime). **Plain `uvicorn`, not
  `uvicorn[standard]`** — a local PoC does not need the extras.
- `httpx` — required by FastAPI's `TestClient` (dev group)

Confirm the current versions of all three at build time (in plan mode) and show
them before `uv add` runs. No dependency beyond these three without asking.

## Files touched
```
silverpath-triage/
├── src/silverpath_triage/
│   ├── config.py            # CHANGED: add API_KEY, MAX_ENQUIRY_CHARS
│   ├── models/api.py        # NEW: TriageRequest, TriageResponse
│   └── api/
│       ├── __init__.py      # NEW
│       ├── auth.py          # NEW: X-API-Key dependency (fail-closed, compare_digest)
│       └── app.py           # NEW: FastAPI app, POST /triage, error handlers
├── tests/
│   └── test_api.py          # NEW: all API tests (free, stubbed, temp DB)
├── docs/
│   ├── PRD-build-04.md            # NEW
│   ├── TECHNICAL_PRD-build-04.md  # NEW
│   └── ACCEPTANCE-build-04.md     # NEW, final step
├── .env.example             # CHANGED: add SILVERPATH_API_KEY=
├── pyproject.toml           # CHANGED: add fastapi, uvicorn (runtime); httpx (dev)
├── README.md                # CHANGED: API section; relabel build #3 "current"
└── CLAUDE.md                # CHANGED: evolved for build #4
```
**Not touched:** `services/triage.py`, `services/storage.py`,
`models/triage.py`, `models/entry.py`, the prompt, every existing test file,
and all earlier builds' docs. The API layer *calls* the services; it does not
change them. All SQL stays in `storage.py`; the model call stays in
`services/triage.py`.

## Config (`config.py`)
Add two values, both read from the environment, alongside the existing ones:
```python
API_KEY = os.environ.get("SILVERPATH_API_KEY", "").strip()
MAX_ENQUIRY_CHARS = 10_000
```
`API_KEY` is read the same way as `ANTHROPIC_API_KEY` (loaded from `.env`,
stripped). `MAX_ENQUIRY_CHARS` lives here so the cap has one home (the request
model references it).

## Models (`models/api.py`)
A new file, so the frozen `TriageResult`/`TriageRecord` are untouched.

**Request:**
```python
from pydantic import BaseModel, Field, field_validator
from silverpath_triage import config

class TriageRequest(BaseModel):
    enquiry_text: str = Field(max_length=config.MAX_ENQUIRY_CHARS)
    source: str = Field(default="api", max_length=200)

    @field_validator("enquiry_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("enquiry_text must not be empty")
        return v
```
- `max_length` gives the 10,000-char rejection as a clean 422 **before** the
  handler runs, so an over-length body never reaches the model.
- The `not_blank` validator mirrors `triage_enquiry`'s own blank check, moving
  it to the boundary so a blank enquiry is a 422 with no model call.
- `source` defaults to `"api"` and is capped so a stored entry always has a
  valid, recognisable source.

**Response:**
```python
from silverpath_triage.models.triage import Intent, KeyDetails, Route, Urgency

class TriageResponse(BaseModel):
    entry_id: int
    intent: Intent
    urgency: Urgency
    summary: str
    key_details: KeyDetails
    suggested_route: Route
    confidence: float
    reasoning: str
    needs_review: bool
    escalate: bool
```
Built by an explicit mapping (this is the build-#3 serialisation trade-off
resolved deliberately — `escalate` is set by hand because it is not serialised):
```python
TriageResponse(entry_id=entry_id, **record.model_dump(), escalate=record.escalate)
```
`record.model_dump()` provides every `TriageResult` field plus `needs_review`;
it does **not** include `escalate` (a plain property), so adding
`escalate=record.escalate` is what puts it in the response.

## Auth (`api/auth.py`)
A FastAPI dependency that **raises** `HTTPException`. Raising during dependency
resolution is what makes it run before body validation (criterion 23).
```python
import secrets
from fastapi import Header, HTTPException
from silverpath_triage import config

def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured = config.API_KEY
    if not configured:
        raise HTTPException(status_code=503, detail="Endpoint is not configured.")
    supplied = x_api_key or ""
    if not secrets.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
```
- **Fail-closed:** a blank/unset `config.API_KEY` → 503 for every request,
  even one with a plausible key. Checked first.
- **Constant-time compare** with `secrets.compare_digest`, on the UTF-8 bytes
  so a non-ASCII header can't raise.
- The detail messages name neither key. The key is never put in a response or a
  log line anywhere.
- Read `config.API_KEY` at call time (as shown), not captured at import, so
  tests can set or blank it.

## The app and route (`api/app.py`)
```python
from fastapi import Depends, FastAPI
# imports: config, the two services, the models, the errors
```
- `POST /triage` with the auth dependency:
  `@app.post("/triage")` and `def triage(body: TriageRequest, _: None = Depends(require_api_key))`.
- The handler mirrors `cmd_triage` exactly, reusing the existing chain:
  ```python
  created_at = datetime.now(timezone.utc)
  result = triage_service.triage_enquiry(body.enquiry_text)
  record = build_record(result)
  entry = TriageEntry(created_at=created_at, source=body.source,
                      enquiry_text=body.enquiry_text, model=config.MODEL,
                      confidence_threshold=config.CONFIDENCE_THRESHOLD, record=record)
  entry_id = storage.save_entry(entry, db_path=config.DB_PATH)
  return TriageResponse(entry_id=entry_id, **record.model_dump(), escalate=record.escalate)
  ```
  Import the triage function via its module (`from silverpath_triage.services import triage as triage_service`) and call `triage_service.triage_enquiry(...)`, so tests patch it in one place.
- **Error handlers**, so failures map to clean HTTP responses with no traceback:
  - `TriageError` → 502, `{"detail": "<message>"}`
  - `StorageError` → 500, `{"detail": "<message>"}`
  - A custom handler for `RequestValidationError` that returns **location +
    message only, not the submitted input** — so a 20,000-char body or an
    enquiry is never echoed back. (FastAPI's default 422 includes the input.)
- **`/docs` and `/openapi.json`: left enabled** (the FastAPI default). Recorded
  decision: the endpoint is localhost-only, the interactive docs help while
  learning, and the schema exposes field shapes only — never the key or stored
  data. Revisit (disable or protect) when the endpoint is exposed in build #5.
- **Host binding is a run-command concern, not code:** the app is started with
  `--host 127.0.0.1`. Never document or script `0.0.0.0`.

## Running it
```
uv run uvicorn silverpath_triage.api.app:app --host 127.0.0.1 --port 8000
```
The server blocks on the model call; FastAPI runs the sync handler in its
threadpool. No async rewrite, no Celery (doc 01 — defer).

## Tests (`tests/test_api.py`, all free unless marked)
Driven with FastAPI's `TestClient`. Autouse fixtures: point `config.DB_PATH` at
a `tmp_path` database; set `config.API_KEY` to a known test value (specific
tests override it to blank for the 503 case); **stub**
`triage_service.triage_enquiry` to return a canned `TriageResult` so no real
client is constructed and no real call is made. Keep an assertion guard that the
Anthropic client is never constructed, and reuse the real-DB guard pattern so
the real `data/triage.db` is never opened.

| Test | Proves |
| --- | --- |
| Valid key + valid body → 200, `TriageResponse` shape | Criterion 1, 10 |
| `escalate` in response = `record.escalate`: `human_review` stub → true; confident `sales` stub → false | Criterion 11 |
| Returned `entry_id` is real: `get_entry(entry_id)` returns the same triage data | Criterion 12 |
| `human_review` stub → entry appears in `list_entries(escalated_only=True)` | Criterion 13 |
| Missing key → 401; wrong key → 401; no client constructed, no row written | Criterion 2 |
| Blank/unset `config.API_KEY` → 503 for every request (incl. with a plausible key) | Criterion 3 |
| Response body, headers and captured logs never contain the configured or submitted key | Criterion 4 |
| Missing `enquiry_text` → 422; empty/whitespace → 422; >10,000 chars → 422; each with no client, no row | Criteria 6, 7, 8 |
| `source` omitted → stored `"api"`; `source` supplied → stored as given | Criterion 9 |
| `triage_enquiry` stubbed to raise `TriageError` → 502, clean detail, no row | Criterion 14 |
| `save_entry` stubbed to raise `StorageError` → 500, clean detail | Criterion 15 |
| `GET /openapi.json` → 200; body contains neither the key nor any enquiry text | Criterion 17 |
| Captured logs after a request contain no enquiry text | Criterion 18 |
| **Bad key + empty body → 401; bad key + 20,000-char body → 401** (never 422) | Criterion 23 |

**Note on the 500 test.** `StorageError` returns a clean 500 *only because* an
exception handler for it is registered on the app (see `api/app.py`). Without
that handler the exception would propagate as an unhandled error. The test
relies on the handler existing, so wire it deliberately alongside the
`TriageError` handler — don't leave the 500 to chance.

**Seen to fail (doc 04, Principle 7), in the auth step:**
1. Write the auth tests first.
2. Temporarily make `require_api_key` allow-all (return without checking).
3. Run the "missing/wrong key → 401" test and the criterion-23 test. They must
   fail (the request is let through). Copy the failing output into the step
   report.
4. `git restore` the broken version — never commit it — implement the real
   check, run again: pass.

## Build sequence (small, reviewable; commit and push after each; stop and report after each)
0. **Handover docs.** Add `docs/PRD-build-04.md`,
   `docs/TECHNICAL_PRD-build-04.md`, and the evolved `CLAUDE.md`. Commit and
   push. Check the commit has no attribution trailer
   (`git log -1 --format='%(trailers)'` is empty).
1. **Deps, config, models.** `uv add fastapi uvicorn` and
   `uv add --dev httpx` (show versions first). Add `API_KEY` and
   `MAX_ENQUIRY_CHARS` to `config.py`; add the `SILVERPATH_API_KEY=` line to
   `.env.example`; add `models/api.py`. Write the model-level free tests (blank
   → error, over-length → error, `source` default, response mapping includes
   `escalate`). Free run passes. *(teaches: request/response models as the API
   contract; validating before spend)*
2. **Auth dependency.** Add `api/__init__.py` and `api/auth.py`. Write the auth
   tests; do the seen-to-fail sequence above. Then implement the real
   fail-closed, `compare_digest` check. Free run passes. *(teaches: the auth
   boundary, fail-closed, proving a safety test can fail)*
3. **App, route, error handlers.** Add `api/app.py`: `POST /triage` wired to
   the existing chain, the auth dependency, the `TriageError`/`StorageError`
   handlers, and the validation handler that doesn't echo input. Write the
   remaining `test_api.py` tests (200 happy path, escalate true/false,
   entry_id real, escalated parity, 502/500 mapping, 401-before-422, no
   enquiry in logs, openapi has no key/enquiry). Free run passes. *(teaches:
   the API layer as an orchestrator; error mapping; dependency ordering)*
4. **README + run docs.** Document the endpoint: run command (host
   `127.0.0.1`), `X-API-Key` header, request/response shape, local-only note.
   Relabel the build #3 docs that still say "current". Free run passes.
   *(teaches: the run/usage contract)*
5. **Acceptance.** Run the free suite. Start the server; capture
   `netstat -ano | findstr :8000` (listening on `127.0.0.1` only). Run the
   **one** paid curl proof (correct key → 200 + `show <id>`; wrong key → 401),
   and confirm no captured log line contains the enquiry or either key. Write
   `docs/ACCEPTANCE-build-04.md`: every PRD criterion (1–23) with PASS/FAIL and
   evidence (test name, code commit, or output captured in this step), plus
   "Known limitations / carried forward". Cite the last code commit, never the
   acceptance doc's own hash.

## Secrets
Two now, both in `.env`, both loaded via `config.py`, never hardcoded:
`ANTHROPIC_API_KEY` (unchanged) and `SILVERPATH_API_KEY` (new). `.env.example`
lists both, blank. Blank-key test runs use **Git Bash** (`NAME= command`); in
PowerShell `$env:NAME = ''` deletes the variable and `.env` then supplies the
real value (doc 05). Confirm a key's state with a check that prints only
true/false, never the value.

## Cost and safety
- API spend: zero in the automated suite (triage is stubbed). One paid call at
  step 5, only when asked. A blank or over-length request costs nothing (422
  before the call).
- First external surface, kept contained: localhost-only binding, required key,
  fail-closed configuration, input capped before spend. No stored data is
  modified; tests never open the real database (guarded).
- Keep the provider spending cap on.