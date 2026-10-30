# PRD — Silverpath Inbound-Enquiry Triage, Build #2: Storage

## Context
Build #1 is complete and committed. It is the AI layer: `triage_enquiry()` calls
Claude and returns a validated `TriageResult`; `build_record()` adds the
code-computed `needs_review` flag and returns a `TriageRecord`. Build #1's own
docs (`docs/PRD.md`, `docs/TECHNICAL_PRD.md`) stay exactly where they are,
unchanged, as the reference for the AI layer.

Build #2 adds a **storage layer on top**. It saves what build #1 produces. It
does not replace or change the AI layer's behaviour.

## Problem
Today each triage result is printed and written as a loose JSON file. Those
files:
- don't accumulate into anything you can list, filter or search;
- don't contain the original enquiry text, so a result can never be re-run or
  checked later;
- can't become eval cases, because an eval case needs the input *and* the
  correct answer.

This build makes every triage run a complete, retrievable **entry** in a local
database: the original enquiry, the run details, the triage record, and empty
slots for a human verdict. Captured enquiries can then grow the eval set in a
later build.

## Type
**Proof of Concept (PoC).** AI layer + storage, run by hand on one machine, no
users. The storage code is still held to a tested standard (see acceptance
criteria). "PoC" describes the system, not permission to skip tests.

## The one workflow
Enquiry file → `triage_enquiry()` → `build_record()` → wrap as a `TriageEntry`
→ save to SQLite → retrieve by command.

- **Input:** an existing `TriageRecord` (build #1's output) plus the context
  of the run it came from: the enquiry text, the source file, the model, the
  confidence threshold and the time.
- **Output:** that record, persisted unchanged inside a `TriageEntry` in a
  local SQLite database, and retrievable.

### What a `TriageEntry` holds
- `id`: assigned by the database
- `created_at`: when the triage ran (UTC)
- `source`: the enquiry file path as given on the command line
- `enquiry_text`: the full original enquiry
- `model`: the model string used (from `config.py`)
- `confidence_threshold`: the threshold used (from `config.py`)
- `schema_version`: starts at 1
- `record`: the `TriageRecord`, **unchanged**
- `verdict`: human-verdict fields (`correct_intent`, `correct_route`,
  `reviewed_at`), **empty when the entry is created**

## Scope (MoSCoW)

| Priority | Item |
| --- | --- |
| Must | `TriageEntry` and `HumanVerdict` Pydantic models |
| Must | One storage module holding all database code (SQLite) |
| Must | Commands: `triage <file>`, `list` (with `--needs-review`), `show <id>`, `verify <id>`, `delete <id>` |
| Must | `triage` keeps the terminal print, saves to the database, and no longer writes JSON files |
| Must | `delete <id>`: simple removal of one entry by id. A baseline requirement because entries hold personal data |
| Must | Config improvement: a missing API key no longer stops the program at import. It fails cleanly only when a Claude call is attempted (detail below) |
| Must | Storage and config tests that make zero API calls; evals split out behind an `eval` marker |
| Must | The database file is gitignored before it is ever created |
| Must | README updated for the new commands and test commands |
| Must | No commit from this build carries a `Co-Authored-By: Claude` trailer or any other Claude attribution line |
| Nice | Flag when the same enquiry text has been stored before |
| Later | `export <id>`: turn a verified entry into an eval case (building the eval set from verdicts is a later piece) |
| Won't | Importing the old JSON files in `data/outputs/` (they lack the enquiry text, so they have no eval value) |
| Won't | Postgres/Supabase, API, frontend, automation |
| Won't | Any change to the prompt, model, threshold or eval labels |

### The config improvement (surfaced by this build)
Today `config.py` raises an error at import if `ANTHROPIC_API_KEY` is missing.
Any command that imports config therefore demands a key, even commands that
never call Claude (`list`, `show`, `verify`, `delete`) and tests that make no API
call. The key check moves to the point where the Claude client is created. Two
things must both be proven:
1. Importing config with no key set does **not** raise.
2. Attempting a triage with no key set still **fails cleanly** with a clear
   message naming `ANTHROPIC_API_KEY`, before any network call is made.

## Observable acceptance criteria
The build is done when:
1. `triage <file>` prints the result exactly as before, saves an entry, and
   prints the new entry's id. No JSON file is written.
2. `show <id>` returns that entry, and its record is identical to what was
   saved (proven by a test: saved entry == retrieved entry).
3. Entries survive closing and reopening the program (proven by a test using
   separate connections).
4. `list` shows entries newest first. `list --needs-review` shows only entries
   where `needs_review` is true.
5. `verify <id> --intent X --route Y` stores a verdict, and `show <id>`
   displays it. A new entry's verdict fields are empty.
6. `delete <id>` asks for confirmation (or takes `--yes`), removes the entry,
   and `show <id>` then reports it not found.
7. An unknown id gives a clear "not found" message for `show`, `verify` and
   `delete`, never a crash.
8. `list`, `show`, `verify` and `delete` work with no API key set and make no
   API calls.
9. Both config proofs above pass as tests.
10. `uv run pytest -m "not eval"` passes with **zero API calls**. `uv run
    pytest -m eval` runs the 9 existing evals, which still pass with their
    labels unchanged.
11. After real use, `git status` never shows the database file.
12. No commit from this build carries a Claude attribution trailer.

## Accuracy bar
- **Storage layer only: 100% round-trip fidelity.** Every entry saved is
  returned identical. This is achievable because storage is deterministic code,
  and it is proven by tests.
- **This is not a claim about triage accuracy.** The triage tool remains
  non-deterministic, with the same accuracy expectations as build #1. This build
  does not change or re-measure it beyond confirming the existing evals still
  pass.

## Error handling
- **Triage decisions:** escalation via `needs_review`, unchanged from build #1.
- **Storage:** an entry is saved only after a complete, valid `TriageRecord`
  exists. A failed triage saves nothing, so there are no partial entries.
  Unknown ids and database problems produce clear messages and a non-zero exit,
  not crashes.
- **Delete:** irreversible, so it needs confirmation unless `--yes` is given.

## Data / privacy
Entries contain personal data (names, phones, emails, postcodes).
- The database lives at `data/triage.db` and is gitignored before it is ever
  created.
- Only the fictional sample enquiries are used during this build. No real
  customer data.
- `delete <id>` is the baseline erasure path. Deleted content is overwritten in
  the file, not just unlinked (see Technical PRD).
- Retention rules, access control and wider UK GDPR design belong to the build
  that first handles real enquiries.

## Out of scope
- Building eval cases from verdicts (`export`): later.
- Importing old JSON outputs.
- Postgres/Supabase, any API or webhook, frontend, automation or sending.
- Any change to triage behaviour (prompt, model, threshold, eval labels).
- Reorganising or editing build #1's docs.