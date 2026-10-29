# CLAUDE.md — Silverpath Inbound-Enquiry Triage (Build #1)

## What this is
A local Python proof-of-concept that triages one raw inbound enquiry (form or
email text) into a structured result using a single Claude call. Output prints
to the terminal and saves as JSON. AI layer only — no database, API, or frontend.

## Rules
- Follow `docs/PRD.md` and `docs/TECHNICAL_PRD.md` as the source of truth. If
  something isn't covered there, stop and ask — do not invent scope.
- Standard structure and stack only, exactly as in the Technical PRD. Put models
  in `models/`, prompts in `prompts/`, the Claude call in `services/`.
- Every structured output is a Pydantic model. Get structured output via
  `client.messages.parse(output_format=...)` → `response.parsed_output`. Do not
  hand-roll JSON parsing or use a tool-use workaround.
- Model string lives in `config.py` (`claude-haiku-5-5`), never inline.
- `needs_review` is computed by deterministic code from `confidence` and the
  threshold in `config.py` — never by the model.
- Never hardcode secrets. `ANTHROPIC_API_KEY` lives in `.env`, loaded via
  `config.py`. `.gitignore` must contain `.env` before the first commit.
- Handle errors: check the response stop reason; fail with a clear message if
  the model refuses or output is incomplete. Don't assume success.

## How to work
- **Plan first, then execute.** Use plan mode; show the plan before writing code.
- **Small, reviewable steps.** One build-sequence step at a time (see Technical
  PRD). Commit before and after each step.
- After each step, stop and report what changed so it can be reviewed before the
  next step is approved.
- **Keep this briefing current.** When you learn something durable that future
  sessions will need — a new convention, a correction you had to be given more
  than once, or a decision that changes how work is done here — propose an
  update to this CLAUDE.md in plain language and wait for approval. Never edit it
  silently, and keep it lean (rules and pointers, not a log).

## Pointers
- `docs/PRD.md` — what & why (problem, workflow, I/O, acceptance criteria)
- `docs/TECHNICAL_PRD.md` — how (stack, models, structure, build sequence)