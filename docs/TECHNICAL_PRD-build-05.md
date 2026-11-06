# Technical PRD — Silverpath Inbound-Enquiry Triage, Build #5: Demo layer

The *how* for `docs/PRD-build-05.md`. Builds on the code verified at the end of
build #4 (last code commit `c65bb5b`; HEAD `8187374`).

## Stack
- **Unchanged:** Python 3.12, uv, FastAPI, uvicorn, Pydantic, python-dotenv,
  anthropic, pytest.
- **Changes (approved by the director):**
  - `httpx` moves from the `dev` group to runtime dependencies
    (`uv remove --dev httpx`, then `uv add httpx`).
  - `uv add jinja2 python-multipart`. FastAPI needs `jinja2` for templates and
    `python-multipart` to read HTML form submissions.
- **Versions:** let `uv` resolve current releases. Report the resolved versions
  from `uv.lock` in the step report. Do not pin numbers from memory.
- **No new test dependencies** (no pytest-asyncio). Tests use FastAPI's
  `TestClient`; the async handler runs inside it.
- No JavaScript, no CSS framework, no CDN, no external fonts.

## Files touched

| File | Change |
|---|---|
| `src/silverpath_triage/web/__init__.py` | **New**, empty |
| `src/silverpath_triage/web/routes.py` | **New**: `APIRouter` with `GET /demo`, `POST /demo`, the two client dependencies, error mapping |
| `src/silverpath_triage/web/templates/demo.html` | **New**: the one page (form, result, errors, notification status) |
| `src/silverpath_triage/services/notify.py` | **New**: build the Slack text, escape it, send one POST |
| `src/silverpath_triage/models/notify.py` | **New**: `NotificationStatus`, `NotificationResult` |
| `src/silverpath_triage/config.py` | **Add** four settings (below). Existing lines unchanged |
| `src/silverpath_triage/api/app.py` | **Add two lines only:** import the demo router, `app.include_router(...)`. Nothing else changes |
| `tests/test_web.py` | **New** |
| `pyproject.toml`, `uv.lock` | The three dependency changes, via `uv` commands only |
| `.env.example` | **Add** `SILVERPATH_WEBHOOK_URL=` (blank) |
| `README.md` | **Add** a "Demo" section; update the Docs list |
| `CLAUDE.md` | Replaced with the build #5 version (evolved, not rewritten) |
| `docs/PRD-build-05.md`, `docs/TECHNICAL_PRD-build-05.md` | **New** (step 0) |
| `docs/ACCEPTANCE-build-05.md` | **New** (final step) |

**Not touched:** `services/triage.py`, `services/storage.py`, `api/auth.py`,
`prompts/`, `models/triage.py`, `models/entry.py`, `models/api.py`, `main.py`,
every existing test file, and every earlier build's docs.

## Config (`config.py`): add

```python
# Fixed address of this app's own API. Never derived from the request, its Host
# header or request.base_url (that would let a forged header redirect the key).
TRIAGE_API_URL = "http://127.0.0.1:8000"
TRIAGE_TIMEOUT_SECONDS = 60.0   # a Claude call can exceed httpx's 5s default

# Read at call time by services/notify.py (config.WEBHOOK_URL, not imported by
# value). Blank means "not configured": the page says so, nothing is sent.
WEBHOOK_URL = os.environ.get("SILVERPATH_WEBHOOK_URL", "").strip()
WEBHOOK_TIMEOUT_SECONDS = 10.0
```

`TRIAGE_API_URL` must match the port in the documented run command (8000).

## Models (`models/notify.py`)

```python
class NotificationStatus(str, Enum):
    sent = "sent"
    not_configured = "not_configured"   # webhook URL blank: nothing sent
    unreachable = "unreachable"         # network error or timeout
    rejected = "rejected"               # Slack answered with a non-200 status


class NotificationResult(BaseModel):
    status: NotificationStatus
    loud: bool  # True when the escalate format was used
```

The fixed text shown for each status is derived when the page is rendered
(one mapping in `web/routes.py`). It is not stored on the model.

## Notification (`services/notify.py`)

- `slack_escape(text: str) -> str`: replace `&` → `&amp;` **first**, then
  `<` → `&lt;` and `>` → `&gt;`. This is the one home for Slack escaping.
- `build_slack_text(response: TriageResponse) -> str`: a pure function. Every
  string that came from the model (summary, labels) goes through
  `slack_escape`. Our own markup is added **after** escaping, so it stays live.
  Shape:

  ```
  [escalate only] <!here> :rotating_light: *ESCALATE*: a person must see this
  *Entry #<entry_id>* · intent: <intent> · urgency: <urgency> · route: <route> · confidence: <0.00>
  Summary: <escaped summary>
  ```

  It takes a `TriageResponse`, which does not contain the enquiry text. That
  keeps the raw enquiry out of Slack by construction. No `key_details` (and so
  no contact details) are included.
- `async def notify_slack(response: TriageResponse, client: httpx.AsyncClient) -> NotificationResult`:
  - read `config.WEBHOOK_URL` at call time; if blank, return `not_configured`
    without making a request;
  - otherwise make exactly one
    `POST <url>, json={"text": ...}, timeout=config.WEBHOOK_TIMEOUT_SECONDS`;
  - Slack answers `200` with body `ok` on success, so `200` → `sent`, and any
    other status → `rejected`;
  - `httpx.HTTPError` (connection errors, timeouts) → `unreachable`;
  - no retries.
- **Logging:**
  - never log the URL, the payload, Slack's response body, or exception text;
    the exception type or status code is allowed;
  - set `logging.getLogger("httpx").setLevel(logging.WARNING)` in this module.
    httpx logs every request's full URL at INFO, and the webhook URL is the
    secret.

## Web layer (`web/routes.py`)

- `router = APIRouter(include_in_schema=False)`;
  `templates = Jinja2Templates(directory=Path(__file__).parent / "templates")`.
- **Two injectable clients**, so tests can swap each one:

  ```python
  async def get_triage_client() -> AsyncIterator[httpx.AsyncClient]:
      async with httpx.AsyncClient() as client:
          yield client

  async def get_webhook_client() -> AsyncIterator[httpx.AsyncClient]:
      async with httpx.AsyncClient() as client:
          yield client
  ```

- `GET /demo` (`async def`): render `demo.html` with an empty form.
- `POST /demo` (`async def`, `enquiry_text: str = Form("")`):
  - The default empty string matters. A *required* form field that is missing
    would trigger FastAPI's own 422, which build #4's JSON error handler would
    answer. The user would see raw JSON instead of the page. With the default,
    the handler always runs and the API does the validating.
  - Make the call:
    `await triage_client.post(f"{config.TRIAGE_API_URL}/triage", json={"enquiry_text": enquiry_text, "source": "web-form"}, headers={"X-API-Key": config.API_KEY}, timeout=config.TRIAGE_TIMEOUT_SECONDS)`.
  - **Do not** pre-check the key, the blank text or the length. `TriageRequest`
    and the auth dependency are the one home for those rules. A blank key gets
    the API's 503 (fail-closed is preserved).
  - Map the outcome to one of these fixed page states:

    | API outcome | Page message (fixed) | Page HTTP status |
    |---|---|---|
    | 200 + valid `TriageResponse` | (result shown) | 200 |
    | 422 | "Please enter an enquiry (not blank, at most 10,000 characters)." | 422 |
    | 401 or 503 | "The demo server is not configured correctly (API key). See the README." | 502 |
    | 502 | "The triage service could not produce a result. Please try again." | 502 |
    | 500 | "The result could not be saved." | 502 |
    | `httpx.HTTPError` (refused, timeout) | "Could not reach the triage API. Is the server running on 127.0.0.1:8000?" | 502 |
    | 200 but invalid JSON or the wrong shape, or any other status | "The triage API returned an unexpected response." | 502 |

  - Parse a 200 body with `TriageResponse.model_validate(response.json())`.
    Catch `ValueError` / `ValidationError` and show the "unexpected response"
    row. Never show the response body or exception text.
  - Only on success, call `notify.notify_slack(result, webhook_client)`. On any
    failure path, send no notification.
  - Render one template with: `enquiry_text` (refilled only on error), `result`
    (`TriageResponse | None`), `error` (fixed string or `None`), `notification`
    (`NotificationResult | None`) plus its fixed status text.
- **Import boundary:**
  - `web/` and `services/notify.py` may import `config`, `models.api`
    (`TriageResponse`, the one home for the response shape), `models.notify` and
    `services.notify`;
  - they must **never** import `services.triage`, `services.storage`,
    `api.auth` or `api.app`.
- **Never log enquiry text**, the key or the webhook URL.

## Template (`web/templates/demo.html`)
- Jinja2 autoescaping (on by default for `.html` via `Jinja2Templates`) is the
  only output path. **Never** `|safe`, `Markup`, `{% autoescape false %}`, an
  inline `<script>`, or an external stylesheet, font or script.
- The form is `method="post" action="/demo"`, with a textarea
  `name="enquiry_text" required maxlength="10000"` (a browser convenience only;
  the API is the authority) and a submit button.
- The result shows every `TriageResponse` field, including the nested
  `key_details` and `contact_info`.
- When `result.escalate` is true, show a prominent banner ("Escalated: a person
  must see this enquiry"). Use the API's field; never recompute it.
- Show a notification status line with the fixed text for its status.
- Include a "Submit another enquiry" link to `/demo` and minimal inline
  `<style>` only.

## App (`api/app.py`): the only change

```python
from silverpath_triage.web.routes import router as demo_router
...
app.include_router(demo_router)
```

The middleware still guards `POST /triage` only. The `/demo` routes are not
covered by it and need no key from the browser.

## Running it
1. **Slack setup (the director does this, not Claude Code):**
   - in a Slack workspace you own (a free demo workspace is fine), create an app
     at api.slack.com/apps ("From scratch");
   - open Incoming Webhooks, switch it on, then "Add New Webhook to Workspace"
     and pick a channel (e.g. `#triage-demo`);
   - copy the URL **straight into `.env`** as `SILVERPATH_WEBHOOK_URL=...`.
   Never paste it into chat, a prompt, a terminal command or a file that gets
   committed.
2. Run `uv run uvicorn silverpath_triage.api.app:app --host 127.0.0.1 --port 8000`
   (unchanged).
3. Open `http://127.0.0.1:8000/demo`.

`.env` needs `ANTHROPIC_API_KEY`, `SILVERPATH_API_KEY` and, for notifications,
`SILVERPATH_WEBHOOK_URL`. If the webhook is blank, the demo still works and the
page says "notification not configured".

## Tests (`tests/test_web.py`, all free)

**Guards (autouse), copied from the `test_api.py` pattern.** They are not moved
into a shared `conftest.py`, because that would change how the existing tests
run.
- The Anthropic client constructor fails the test if called.
- A temp `config.DB_PATH`, plus the real-database guard and its "guard is
  active" test.
- `triage_service.triage_enquiry` is stubbed with a call recorder. Patching it
  in the *test* is fine; the boundary rule applies to `web/` code, not tests.
- `config.API_KEY` is set to a test key.
- `config.WEBHOOK_URL` is set to a fake `https://hooks.slack.test/...` value.
- **Both clients are always overridden** via `app.dependency_overrides`, and
  the overrides are cleared after each test:
  - the triage client is `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`
    with a request event hook that records each outgoing request. Each test
    therefore runs the real middleware, auth, validation, error handlers and
    route, with only triage stubbed;
  - the webhook client is `httpx.AsyncClient(transport=httpx.MockTransport(handler))`,
    recording each request and answering a configurable status (200 `ok` by
    default) or raising `httpx.ConnectError`.
- No test makes a real network call.

**Tests to include (names are suggestions; one or more per bullet):**
- Form page: 200, textarea attributes present, no secret in the body.
  *(criterion 1)*
- Success: every field shown; escalation banner on for an escalated stub result
  (low confidence, or `human_review`) and off for a calm one; the entry is stored
  in the temp DB with `source == "web-form"`. *(1)*
- Invalid input: blank, whitespace-only and 10,001 characters each give the
  fixed message, `stub.calls == []`, nothing stored, zero webhook requests.
  *(2)*
- Outgoing triage request: URL is `config.TRIAGE_API_URL + "/triage"`,
  `X-API-Key` equals the test key, JSON `source == "web-form"`. *(3)*
- Import boundary: parse `web/routes.py` and `services/notify.py` with `ast`;
  assert none of the four forbidden modules is imported. *(3)*
- Error mapping, one test per table row:
  - blank `config.API_KEY` → the 503 row;
  - stub raises `TriageError` → 502;
  - `storage.save_entry` patched to raise `StorageError` → 500;
  - the triage client raises `httpx.ConnectError` and `httpx.ReadTimeout` →
    unreachable;
  - a fake 200 with the wrong shape → unexpected response.
  Zero webhook requests on each. *(6, 2)*
- Notification:
  - exactly one POST per successful submission, with a JSON `text`;
  - loud vs calm format;
  - `<!channel>`, `<@U123>` and `&` in the summary arrive escaped;
  - status mapping: 200 → sent; 400, 403, 404 and 500 → rejected; ConnectError
    → unreachable; blank URL → not_configured with zero requests;
  - the page shows the fixed status text and never the URL or error text. *(5, 6)*
- **Secrets (seen to fail first):**
  - set `config.API_KEY` and `config.WEBHOOK_URL` to distinctive sentinel
    values;
  - drive GET, success and every error path with
    `caplog.set_level(logging.DEBUG)`;
  - assert neither sentinel appears in any response body or in `caplog.text`;
  - broken version: delete the `httpx` logger-level line. httpx then logs the
    webhook URL at INFO, and the test must fail on the URL sentinel. *(4)*
- **Fixed address (seen to fail first):**
  - `POST /demo` with header `Host: evil.example`;
  - assert the recorded outgoing request went to `127.0.0.1:8000`;
  - broken version: build the URL from `request.base_url`; the test must fail.
    *(10)*
- **XSS (seen to fail first):**
  - (a) a stub result whose summary is `<script>alert("xss")</script><b>x</b>`;
  - (b) the textarea refill: submit a 10,001-character input that starts with
    `<script>alert("xss")</script>`; it fails validation, so it is echoed back;
  - assert `&lt;script&gt;` is present and the raw `<script>alert` is absent in
    both;
  - broken version: add `|safe` to the summary output; the test must fail.
    *(11)*

Every "seen to fail" run is reported in the step report: the command, the
failing assertion, then the restored passing run. Never commit a broken version.

## Build sequence
Small, reviewable steps. For each: plan mode first, then build, commit and push,
then **stop and report** (files changed, what each change does in plain
language, test output, any errors, commit hash). Run the free suite
`uv run pytest -m "not eval"` at every step; every existing test must still pass.

0. **Docs (step 0).**
   - The director places `docs/PRD-build-05.md`, `docs/TECHNICAL_PRD-build-05.md`
     and the new `CLAUDE.md`.
   - Claude Code checks only those three files changed (`git status`), commits,
     pushes, and confirms the commit has no trailers.
   - **Then start a fresh Claude Code session** so it reads the new CLAUDE.md.
1. **Dependencies, config, model.**
   - The three `uv` changes, the four `config.py` settings, `.env.example`,
     `models/notify.py`;
   - small tests for the new config values and the model, in `test_web.py`;
   - report the resolved versions.
2. **Notification service.** `services/notify.py` plus its tests against the
   fake transport, including the secrets-in-logs test seen to fail.
3. **Web layer.**
   - `web/routes.py`, `demo.html`, and the two-line `app.py` include;
   - tests for the form, success, invalid input, the outgoing request, the
     import boundary, error mapping and notification wiring.
4. **Safety tests.** The secrets-in-pages, fixed-address and XSS tests, each
   seen to fail first, reported as above.
5. **README.**
   - a "Demo" section: Slack setup, run, open `/demo`, what the page shows;
   - the security posture and known limitations in plain language;
   - add the build #5 docs to the Docs list.
6. **Acceptance.**
   - The free run with `ANTHROPIC_API_KEY=` blanked in **Git Bash** (not
     PowerShell; see playbook doc 05);
   - the live demo per PRD criterion 8 (two paid calls, fictional enquiries
     only);
   - the trailer check across every build #5 commit;
   - then write `docs/ACCEPTANCE-build-05.md` in the build #4 format: each of
     the 11 criteria with PASS/FAIL and evidence (test name, code commit or
     captured output), "Code verified at <last code commit>" plus an empty
     `git diff <that commit> HEAD -- src tests pyproject.toml uv.lock`, and a
     "Known limitations / carried forward" section;
   - mark build #5 done in CLAUDE.md's "What this is" (a proposed change,
     approved first). Never cite the acceptance doc's own commit hash.

**Known limitations to carry into the acceptance doc** (plus anything
surfaced):
- direct `POST /triage` calls don't notify;
- the form route is unauthenticated and has no CSRF protection (localhost only);
- a timeout on the page can still mean the entry was stored, so the page may say
  "couldn't reach" for a triage that succeeded;
- no Slack retries; Slack's ~1 message/second limit applies;
- `TRIAGE_API_URL` must match the run port.

## If loopback proves unworkable
Stop and report the actual error first. Do not switch on your own. Either
fallback needs the director's approval.

- **Fallback A (preferred):** keep the front door but skip the network. The
  production triage client becomes `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`,
  calling the app in memory through the same middleware, auth and validation.
  - The import boundary and criterion 3 still hold.
  - Criterion 10 becomes "the address is fixed in config and not used from the
    request".
  - Cost: a circular import to manage (`app` must be imported lazily inside the
    dependency), and the server console no longer shows the second request line.
- **Fallback B (director-sanctioned):** an in-process call to the triage service
  from the handler, mirroring the `/triage` route's chain (`triage_enquiry` →
  `build_record` → `save_entry`).
  - The import boundary is dropped, so criteria 3 and 10 must be rewritten.
  - The chain then lives in two places (doc 04: one rule, one home), so it needs
    a test proving the form and the API store identical entries for the same
    stubbed result.

## Secrets
- `ANTHROPIC_API_KEY`, `SILVERPATH_API_KEY` and `SILVERPATH_WEBHOOK_URL` live in
  `.env` only, loaded via `config.py` and read at call time.
- `.env.example` lists all three, blank.
- Claude Code **never opens, prints, copies or edits `.env`**. To check a value
  is present, use a check that prints only true/false.
- Nothing secret appears in templates, pages, logs, tests or commits. Tests use
  sentinel values only.

## Cost and safety
- Automated tests: zero paid calls, zero network.
- Acceptance: two paid Claude calls and two Slack messages.
- Provider spending cap on.
- Bind to `127.0.0.1` only. Stop the server when not demoing.