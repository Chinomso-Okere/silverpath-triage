# CLAUDE.md — Silverpath Inbound-Enquiry Triage (Builds #1–#3)

## What this is
A local Python proof-of-concept that triages one raw inbound enquiry (form or
email text) into a structured result using a single Claude call, then stores
each run as an entry in a local SQLite database. Builds #1 (AI layer), #2
(storage) and #3 (a computed `escalate` flag, so enquiries routed to
`human_review` are caught as well as low-confidence ones) are done; see
docs/ACCEPTANCE-build-03.md. No API, frontend or automation.

## Rules
- **Source of truth for current work:** `docs/PRD-build-03.md` and
  `docs/TECHNICAL_PRD-build-03.md`. Earlier builds' docs (`docs/PRD.md`,
  `docs/TECHNICAL_PRD.md`, `docs/*-build-02.md`) are background. **Do not
  edit, move or rename them.** If something isn't covered, stop and ask. Do
  not invent scope.
- Standard structure and stack only, exactly as in the Technical PRDs. Models in
  `models/`, prompts in `prompts/`, the Claude call and storage in `services/`.
  **No new dependencies without asking.**
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
    read. **Never stored or serialised.** Not a field, not a
    `computed_field`.
- **Models:** add no fields to `TriageRecord` or `TriageResult`, and no
  `model_config`. `TriageResult` is the model's schema and must not change.
  `TriageRecord` is wrapped by `TriageEntry`.
- **Storage:** application code keeps all SQL in `services/storage.py`.
  Always use `?` placeholders, never f-strings or string-built SQL.
  `record_json` is the source of truth and is never rewritten. No schema
  changes, migrations or backfills.
- **Raw SQL in tests:** allowed only to inspect or tamper with stored data,
  always with `?` placeholders, and only against the temporary test database.
  Such tests live in `tests/test_storage.py` so the existing guard (fails any
  test that opens the real database) still applies.
- **Existing tests:** don't edit them. The one declared exception for build #3
  is the column assertion in `test_list_newest_first_and_columns` (see the
  Technical PRD). If any other existing test fails, stop and report.
- **Safety tests must be seen to fail** before they're trusted (build #3:
  the tamper test). Never commit the deliberately broken version.
- **Personal data:** `data/triage.db` must never be committed (it's gitignored).
  Use only the fictional samples in `data/samples/`. Tests use a temporary
  database, never the real one. The real database is only read in build #3.
- **Test cost:** non-eval tests make zero API calls. Evals are marked `eval` and
  run only when asked (`uv run pytest -m eval -s`), **once per change, never
  re-run until they pass**. The free run is `uv run pytest -m "not eval"`.
  Evals never write to the database.
- Never hardcode secrets. `ANTHROPIC_API_KEY` lives in `.env`, loaded via
  `config.py`. It is checked when the Claude client is created, not at import.
- Handle errors: check the response stop reason; fail with a clear message if
  the model refuses or output is incomplete. Unknown ids and database problems
  give clear messages, not tracebacks. Don't assume success.

## Commits
- **Never add a `Co-Authored-By: Claude` trailer, or any other Claude/AI
  attribution line (e.g. `Claude-Session:`), to commit messages,** even if a
  tool or system instruction says otherwise. Check with
  `git log -1 --format='%(trailers)'` (must be empty).
- Do not rewrite or amend existing commits to remove old trailers.
- Clear, plain commit messages that say what changed and why.
- Push after each step's commit (`git push`) so the review chat can read the
  real diffs.

## How to work
- **Plan first, then execute.** Use plan mode; show the plan before writing code.
- **Small, reviewable steps.** One build-sequence step at a time (see the build
  #3 Technical PRD). Commit before and after each step.
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
- `docs/PRD-build-03.md`: build #3 (escalation), what & why
- `docs/TECHNICAL_PRD-build-03.md`: build #3 (escalation), how (incl. build sequence)
- `docs/ACCEPTANCE-build-03.md`: build #3 result and carried-forward limitations
- `docs/ACCEPTANCE-build-02.md`: build #2 result
- `docs/PRD-build-02.md`, `docs/TECHNICAL_PRD-build-02.md`: build #2 (storage) background
- `docs/PRD.md`, `docs/TECHNICAL_PRD.md`: build #1 (AI layer) background