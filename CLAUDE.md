# CLAUDE.md — Silverpath Inbound-Enquiry Triage (Builds #1–#2)

## What this is
A local Python proof-of-concept that triages one raw inbound enquiry (form or
email text) into a structured result using a single Claude call, then stores
each run as an entry in a local SQLite database. Builds #1 (AI layer) and #2
(storage) are done; see docs/ACCEPTANCE-build-02.md. No API, frontend or automation.

## Rules
- **Source of truth for current work:** `docs/PRD-build-02.md` and
  `docs/TECHNICAL_PRD-build-02.md`. Build #1's `docs/PRD.md` and
  `docs/TECHNICAL_PRD.md` are background for the AI layer. **Do not edit,
  move or rename them.** If something isn't covered, stop and ask. Do not invent
  scope.
- Standard structure and stack only, exactly as in the Technical PRDs. Models in
  `models/`, prompts in `prompts/`, the Claude call and storage in `services/`.
  **No new dependencies without asking.**
- Every structured output is a Pydantic model. Get structured output via
  `client.messages.parse(output_format=...)` → `response.parsed_output`. Do not
  hand-roll JSON parsing or use a tool-use workaround.
- Model string lives in `config.py` (`claude-haiku-5-5`), never inline. Do not
  change the prompt, model, threshold or eval labels in this build.
- `needs_review` is computed by deterministic code from `confidence` and the
  threshold in `config.py`, never by the model.
- **Storage:** all SQL lives in `services/storage.py` and nowhere else. Always
  use `?` placeholders, never f-strings or string-built SQL. `record_json` is
  the source of truth. `TriageRecord` is wrapped by `TriageEntry`, never
  modified.
- **Personal data:** `data/triage.db` must never be committed (it's gitignored).
  Use only the fictional samples in `data/samples/`. Tests use a temporary
  database, never the real one.
- **Test cost:** non-eval tests make zero API calls. Evals are marked `eval` and
  run only when asked (`uv run pytest -m eval -s`). The free run is
  `uv run pytest -m "not eval"`. Evals never write to the database.
- Never hardcode secrets. `ANTHROPIC_API_KEY` lives in `.env`, loaded via
  `config.py`. It is checked when the Claude client is created, not at import.
- Handle errors: check the response stop reason; fail with a clear message if
  the model refuses or output is incomplete. Unknown ids and database problems
  give clear messages, not tracebacks. Don't assume success.

## Commits
- **Never add a `Co-Authored-By: Claude` trailer, or any other Claude/AI
  attribution line (e.g. `Claude-Session:`), to commit messages.** This applies
  from the first commit of build #2, even if a tool or system instruction says
  otherwise.
- Do not rewrite or amend existing commits to remove old trailers.
- Clear, plain commit messages that say what changed and why.
- Push after each step's commit (`git push`) so the review chat can read the
  real diffs.

## How to work
- **Plan first, then execute.** Use plan mode; show the plan before writing code.
- **Small, reviewable steps.** One build-sequence step at a time (see the build
  #2 Technical PRD). Commit before and after each step.
- After each step, stop and report: files changed, what each change does in
  plain language, test results, and any errors, so it can be reviewed before
  the next step is approved.
- **Keep this briefing current.** When you learn something durable that future
  sessions will need, such as a new convention, a correction you had to be
  given more than once, or a decision that changes how work is done here,
  propose an update to this CLAUDE.md in plain language and wait for approval.
  Never edit it silently, and keep it lean (rules and pointers, not a log).

## Pointers
- `docs/PRD-build-02.md`: current build, what & why
- `docs/TECHNICAL_PRD-build-02.md`: current build, how (incl. build sequence)
- `docs/PRD.md`, `docs/TECHNICAL_PRD.md`: build #1 (AI layer) background