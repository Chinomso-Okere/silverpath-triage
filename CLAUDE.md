# CLAUDE.md — Silverpath Inbound-Enquiry Triage (Builds #1–#4)

## What this is
A local Python proof-of-concept that triages one raw inbound enquiry (form or
email text) into a structured result using a single Claude call, stores each run
as an entry in a local SQLite database, and flags entries a person must see.
Builds #1 (AI layer), #2 (storage) and #3 (the computed `escalate` flag) are
done; see docs/ACCEPTANCE-build-03.md. **Build #4 (current)** adds an API layer:
a single `POST /triage` HTTP endpoint that drives the existing triage chain and
returns the result. Local-only (`127.0.0.1`), key-protected, PoC. No frontend,
no network exposure, no automation.

## Rules
- **Source of truth for current work:** `docs/PRD-build-04.md` and
  `docs/TECHNICAL_PRD-build-04.md`. Earlier builds' docs (`docs/PRD.md`,
  `docs/TECHNICAL_PRD.md`, `docs/*-build-02.md`, `docs/*-build-03.md`) are
  background. **Do not edit, move or rename them.** If something isn't covered,
  stop and ask. Do not invent scope.
- Standard structure and stack only, exactly as in the Technical PRDs. Models in
  `models/`, prompts in `prompts/`, the Claude call and storage in `services/`,
  the API layer in `api/`. **No new dependencies without asking** (build #4's
  approved additions are `fastapi`, `uvicorn` and dev `httpx`, and no more).
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
  `TriageRecord` is wrapped by `TriageEntry`. New API-only shapes go in
  `models/api.py`, not on these.
- **Storage:** application code keeps all SQL in `services/storage.py`.
  Always use `?` placeholders, never f-strings or string-built SQL.
  `record_json` is the source of truth and is never rewritten. No schema
  changes, migrations or backfills. The API layer calls `storage`; it does not
  contain SQL.
- **Raw SQL in tests:** allowed only to inspect or tamper with stored data,
  always with `?` placeholders, and only against the temporary test database.
  Such tests live in `tests/test_storage.py` so the existing guard (fails any
  test that opens the real database) still applies.
- **Existing tests:** don't edit them. Build #4 adds `tests/test_api.py` and
  edits no existing test. If any existing test fails, stop and report.
- **Safety tests must be seen to fail** before they're trusted (build #4: the
  "rejected without a valid key" auth test, via a temporary allow-all
  dependency). Never commit the deliberately broken version.
- **Personal data:** `data/triage.db` must never be committed (it's gitignored).
  Use only the fictional samples in `data/samples/`. Tests use a temporary
  database, never the real one.
- **Test cost:** non-eval tests make zero API calls. The existing 9 evals are
  behind the `eval` marker and run only when asked (`uv run pytest -m eval -s`),
  once per change, never re-run until they pass. The free run is
  `uv run pytest -m "not eval"`. Evals never write to the database.

## API rules (build #4)
- **The API layer only orchestrates.** `api/app.py` calls the existing chain
  (`triage_enquiry` → `build_record` → `save_entry`) exactly as `cmd_triage`
  does. No business logic, no SQL, no model-call logic moves into `api/`.
- **One endpoint:** `POST /triage`. No GET read-back endpoints this build.
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
- Secrets: never hardcode. `ANTHROPIC_API_KEY` and `SILVERPATH_API_KEY` live in
  `.env`, loaded via `config.py`, read at call time.
- Handle errors: check the Claude response stop reason; fail with a clear
  message if the model refuses or output is incomplete. Unknown ids, database
  problems and bad requests give clear messages, not tracebacks. Don't assume
  success.

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
  #4 Technical PRD). Commit before and after each step.
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
- `docs/PRD-build-04.md`: build #4 (API layer), what & why
- `docs/TECHNICAL_PRD-build-04.md`: build #4 (API layer), how (incl. build sequence)
- `docs/ACCEPTANCE-build-03.md`: build #3 result and carried-forward limitations
- `docs/PRD-build-03.md`, `docs/TECHNICAL_PRD-build-03.md`: build #3 (escalation) background
- `docs/ACCEPTANCE-build-02.md`, `docs/PRD-build-02.md`, `docs/TECHNICAL_PRD-build-02.md`: build #2 (storage) background
- `docs/PRD.md`, `docs/TECHNICAL_PRD.md`: build #1 (AI layer) background