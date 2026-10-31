# Silverpath Inbound-Enquiry Triage (Builds #1–#3)

Reads one raw inbound enquiry (web form or email text) and returns a structured
triage decision (intent, urgency, route, key details, confidence) using a
single Claude call, flagging low-confidence results for human review. Each run
is saved as an entry in a local SQLite database, so results can be listed,
shown, checked against a human verdict and deleted.

**Proof of concept.** It suggests a route and a person acts on it. There is a
local database, but no API, frontend, automation or automatic sending.

## Setup
1. Install [uv](https://docs.astral.sh/uv/), then run `uv sync`.
2. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. The key is only
   needed for `triage` and the paid evals; the other commands and the free
   tests run without it.

## Commands
Run each as `uv run python -m silverpath_triage.main <command>`:

| Command | What it does |
| --- | --- |
| `triage <file>` | Triage one enquiry file, print the result, and save it as a new entry |
| `list [--needs-review \| --escalated] [--limit N]` | List entries, newest first (default 20). The two filters can't be combined |
| `show <id>` | Show one entry: run details, triage result, original enquiry, verdict |
| `verify <id> --intent X --route Y` | Record the correct intent and route. Re-running replaces the verdict |
| `delete <id> [--yes]` | Permanently delete an entry. Asks first unless `--yes` is given |

Two flags, both computed by code, never by the model:
- `needs_review` = "the model is unsure": confidence below the threshold. `list --needs-review` shows these.
- `escalate` = "a person must see this": `needs_review`, or routed to `human_review`. `list --escalated` shows these, with the reason in the Why column.

Running with no command prints help.

## Tests
- **Free:** `uv run pytest -m "not eval"`. No API calls; each test uses its own
  temporary database.
- **Paid evals:** `uv run pytest -m eval -s`. Makes 9 real API calls, one per
  case; `-s` shows each case's confidence. Evals never write to the database.

## Privacy
- `data/triage.db` holds personal data from enquiries (names, phones, emails,
  postcodes). It is gitignored and must never be committed.
- Use only the fictional samples in `data/samples/`.
- `delete <id>` erases an entry; deleted content is overwritten in the
  database file, not just unlinked.

## Docs
- [docs/PRD-build-03.md](docs/PRD-build-03.md): escalation build (current), what and why
- [docs/TECHNICAL_PRD-build-03.md](docs/TECHNICAL_PRD-build-03.md): escalation build (current), how
- [docs/PRD-build-02.md](docs/PRD-build-02.md): storage build, what and why
- [docs/TECHNICAL_PRD-build-02.md](docs/TECHNICAL_PRD-build-02.md): storage build, how
- [docs/ACCEPTANCE-build-02.md](docs/ACCEPTANCE-build-02.md): acceptance check and known limitations
- [docs/PRD.md](docs/PRD.md), [docs/TECHNICAL_PRD.md](docs/TECHNICAL_PRD.md): build #1 (AI layer) background
