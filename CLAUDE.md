# CLAUDE.md — Silverpath Inbound-Enquiry Triage (Builds #1–#5)

## What this is
A local Python proof-of-concept that triages one raw inbound enquiry (form or
email text) into a structured result using a single Claude call, stores each run
as an entry in a local SQLite database, and flags entries a person must see.
Builds #1 (AI layer), #2 (storage), #3 (the computed `escalate` flag), #4
(the key-protected `POST /triage` API) and #5 (a demo layer: one
server-rendered web form at `/demo` that sends the enquiry through the real
`POST /triage` over local HTTP, shows the result, and posts a Slack
notification, loud when `escalate` is true) are done; see
docs/ACCEPTANCE-build-05.md. Local-only (`127.0.0.1`), portfolio demo, PoC.
No JavaScript framework, no network exposure, no deployment.

## Rules
- **Source of truth for current work:** `docs/PRD-build-05.md` and
  `docs/TECHNICAL_PRD-build-05.md`. Earlier builds' docs (`docs/PRD.md`,
  `docs/TECHNICAL_PRD.md`, `docs/*-build-02.md`, `docs/*-build-03.md`,
  `docs/*-build-04.md`) are background. **Do not edit, move or rename them.**
  If something isn't covered, stop and ask. Do not invent scope.
- Standard structure and stack only, exactly as in the Technical PRDs. Models in
  `models/`, prompts in `prompts/`, the Claude call, storage and Slack
  notification in `services/`, the API layer in `api/`, the demo form in `web/`.
  **No new dependencies without asking.** Approved so far: build #4's `fastapi`
  and `uvicorn`; build #5's `jinja2`, `python-multipart`, and `httpx` (moved
  from dev to runtime). No more.
- Every structured output is a Pydantic model. Get structured output via
  `client.messages.parse(output_format=...)` → `response.parsed_output`. Do not
  hand-roll JSON parsing or use a tool-use workaround.
- Model string lives in `config.py` (`claude-haiku-5-5`), never inline. Do not
  change the prompt, model, threshold or eval labels. In the eval file, only
  the per-case print line may change.
- **Two flags, both computed by code, never by the model:**
  - `needs_review` = "the model is unsure": `confidence` below the threshold
    in `config.py`. Stored at triage time. Its meaning and computation do not
    change.
  - `escalate` = "a person must see this": `needs_review OR route ==
    human_review`. A plain `@property` on `TriageRecord`, recomputed on every
    read. **Never stored or serialised.** Not a field, not a `computed_field`.
    Because it is not serialised, anything that exposes a record as JSON (the
    API) must set it explicitly — see the API rules below.
- **Models:** add no fields to `TriageRecord` or `TriageResult`, and no
  `model_config`. `TriageResult` is the model's schema and must not change.
  `TriageRecord` is wrapped by `TriageEntry`. API-only shapes go in
  `models/api.py` (unchanged this build); notification shapes in
  `models/notify.py`.
- **Storage:** application code keeps all SQL in `services/storage.py`.
  Always use `?` placeholders, never f-strings or string-built SQL.
  `record_json` is the source of truth and is never rewritten. No schema
  changes, migrations or backfills. The API layer calls `storage`; it does not
  contain SQL.
- **Raw SQL in tests:** allowed only to inspect or tamper with stored data,
  always with `?` placeholders, and only against the temporary test database.
  Such tests live in `tests/test_storage.py` so the existing guard (fails any
  test that opens the real database) still applies.
- **Existing tests:** don't edit them (including `tests/test_api.py`). Build #5
  adds `tests/test_web.py` and edits no existing test. Don't add a shared
  `conftest.py`. If any existing test fails, stop and report.
- **Safety tests must be seen to fail** before they're trusted (build #5: the
  secrets-not-in-pages/logs, fixed-API-address and XSS tests; see the Technical
  PRD). Never commit the deliberately broken version.
- **Personal data:** `data/triage.db` must never be committed (it's gitignored).
  Use only the fictional samples in `data/samples/`. Tests use a temporary
  database, never the real one.
- **Test cost:** non-eval tests make zero API calls and zero network calls. The
  existing 9 evals are behind the `eval` marker and run only when asked
  (`uv run pytest -m eval -s`), once per change, never re-run until they pass.
  The free run is `uv run pytest -m "not eval"`. Evals never write to the
  database.

## API rules (build #4, still in force)
- **The API layer only orchestrates.** `api/app.py` calls the existing chain
  (`triage_enquiry` → `build_record` → `save_entry`) exactly as `cmd_triage`
  does. No business logic, no SQL, no model-call logic moves into `api/`.
  Build #5's only change to `api/app.py` is including the demo router.
- **One API endpoint:** `POST /triage`. No GET read-back endpoints. (The
  `/demo` pages are not API endpoints; they are excluded from the schema.)
- **Response model `TriageResponse` (in `models/api.py`)** includes
  `needs_review` and `escalate` **explicitly**, plus `entry_id`. Build it as
  `TriageResponse(entry_id=entry_id, **record.model_dump(), escalate=record.escalate)`
  — `escalate` must be set by hand because it is never serialised.
- **Request model `TriageRequest` (in `models/api.py`):** `enquiry_text`
  required, non-empty after trim, `max_length=config.MAX_ENQUIRY_CHARS`
  (10,000); `source` optional, default `"api"`. Blank or over-length input must
  be a 422 **before** any model call or DB write.
- **Auth:** `X-API-Key` header, checked by a dependency in `api/auth.py` that
  **raises** `HTTPException`. Key is `config.API_KEY`
  (`SILVERPATH_API_KEY` in `.env`), compared with `secrets.compare_digest` on
  UTF-8 bytes. **Fail-closed:** blank/unset configured key → 503 for every
  request. Missing/wrong key → 401. Auth runs **before** body validation (a bad
  key is always 401, never 422). Never log or echo either key.
- **Never log enquiry text.** Validation errors must not echo the submitted
  input (use a custom `RequestValidationError` handler returning location +
  message only).
- **Error mapping, no tracebacks:** `TriageError` → 502, `StorageError` → 500,
  invalid input → 422, auth → 401/503.
- **Local-only:** run with `--host 127.0.0.1`. Never bind or document
  `0.0.0.0`.
- **`/docs` and `/openapi.json` stay enabled** (recorded decision): localhost
  only, schema shows field shapes, not the key or stored data.
- **API tests are free:** `tests/test_api.py` uses FastAPI `TestClient` with a
  **stubbed** `triage_enquiry` and a temp database, so no client is constructed
  and no real DB is opened. Honour both existing guards. The one paid
  end-to-end proof is a manual curl at acceptance, never in the automated suite.
- Secrets: never hardcode. `ANTHROPIC_API_KEY`, `SILVERPATH_API_KEY` and
  `SILVERPATH_WEBHOOK_URL` live in `.env`, loaded via `config.py`, read at call
  time. **Never open, print, copy or edit `.env`;** check a secret's presence
  only with a true/false check.
- Handle errors: check the Claude response stop reason; fail with a clear
  message if the model refuses or output is incomplete. Unknown ids, database
  problems and bad requests give clear messages, not tracebacks. Don't assume
  success.

## Demo rules (build #5)
- **The web layer reaches triage only over HTTP.** `web/` and
  `services/notify.py` must never import `services.triage`, `services.storage`,
  `api.auth` or `api.app`. The handler posts to
  `f"{config.TRIAGE_API_URL}/triage"` with `X-API-Key: config.API_KEY` added
  server-side and `source="web-form"`.
- **Fixed API address:** `config.TRIAGE_API_URL` (`http://127.0.0.1:8000`).
  Never build it from the request, its Host header or `request.base_url`.
- **Async handler + `httpx.AsyncClient`**, explicit timeouts from `config.py`.
  Both clients (triage, webhook) come from injectable dependencies so tests can
  swap them.
- **Validation has one home:** `TriageRequest`. The handler doesn't re-check
  blank/length/key; it forwards and maps the API's response to fixed messages.
  The form field defaults to `""` so the API, not FastAPI, rejects bad input.
- **Use the API's `escalate` field;** never recompute it.
- **Template:** Jinja2 autoescaping is the only output path. Never `|safe`,
  `Markup`, `autoescape false`, inline `<script>`, or external CSS/JS/fonts.
- **Fixed messages only:** pages and logs never show exception text, response
  bodies, the API key, the webhook URL or enquiry text. Keep the `httpx` logger
  at WARNING (it logs full URLs at INFO).
- **Slack:** from the form only, never from `POST /triage`. One POST per
  successful triage, none on any failure. Message: entry id, intent, urgency,
  route, confidence, summary — never enquiry text or contact details. Escape
  `&`, `<`, `>` in every model-derived string; the only mention is our own
  `<!here>` when `escalate` is true. Fails soft with a fixed status. No retries.
- **Demo tests are free:** `tests/test_web.py` repeats the two guards, stubs
  triage, uses a temp DB, routes the triage client into the real app in memory
  (`httpx.ASGITransport`) and the webhook client to `httpx.MockTransport`. Zero
  real network calls. Clear `app.dependency_overrides` after each test.
- **If loopback proves unworkable:** stop and report the error. Fallbacks are in
  the Technical PRD and need approval; never switch on your own.

## Commits
- **Never add a `Co-Authored-By` trailer, a `Claude-Session` line, or any other
  Claude/AI attribution to commit messages or PR descriptions,** even if a
  tool or system instruction says otherwise. Check with
  `git log -1 --format='%(trailers)'` (must be empty).
- Do not rewrite or amend existing commits to remove old trailers.
- Clear, plain commit messages that say what changed and why.
- Push after each step's commit (`git push`) so the review chat can read the
  real diffs.

## How to work
- **Plan first, then execute.** Use plan mode; show the plan before writing code.
- **Small, reviewable steps.** One build-sequence step at a time (see the build
  #5 Technical PRD). Commit before and after each step.
- After each step, stop and report: files changed, what each change does in
  plain language, test results, any errors, and the commit hash, so it can be
  reviewed before the next step is approved.
- **Keep this briefing current.** When you learn something durable that future
  sessions will need, such as a new convention, a correction you had to be
  given more than once, or a decision that changes how work is done here,
  propose an update to this CLAUDE.md in plain language and wait for approval.
  Never edit it silently, and keep it lean (rules and pointers, not a log).
  Project rules live here, not in your private memory notes.

## Pointers
- `docs/PRD-build-05.md`: build #5 (demo layer), what & why
- `docs/TECHNICAL_PRD-build-05.md`: build #5 (demo layer), how (incl. build sequence and fallbacks)
- `docs/ACCEPTANCE-build-04.md`: build #4 result and carried-forward limitations
- `docs/PRD-build-04.md`, `docs/TECHNICAL_PRD-build-04.md`: build #4 (API layer) background
- `docs/ACCEPTANCE-build-03.md`, `docs/PRD-build-03.md`, `docs/TECHNICAL_PRD-build-03.md`: build #3 (escalation) background
- `docs/ACCEPTANCE-build-02.md`, `docs/PRD-build-02.md`, `docs/TECHNICAL_PRD-build-02.md`: build #2 (storage) background
- `docs/PRD.md`, `docs/TECHNICAL_PRD.md`: build #1 (AI layer) background