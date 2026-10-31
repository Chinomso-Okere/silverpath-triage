# Technical PRD — Silverpath Inbound-Enquiry Triage, Build #2: Storage

The *how* for `docs/PRD-build-02.md`. Build #1's `docs/TECHNICAL_PRD.md` remains
the reference for the AI layer and is not edited. Where this doc and general
habit disagree, this doc wins for this build. Anything not covered here: stop
and ask.

## Stack additions (only what this build needs)
| Concern | Choice | Notes |
| --- | --- | --- |
| Database | **SQLite** via Python's built-in **`sqlite3`** | One local file, no server, no account, no cost, **no new dependency**. Right-sized for one user running by hand |
| Command line | Python's built-in **`argparse`** | Subcommands for `main.py`. No new dependency |
| Everything else | Unchanged from build #1 | Python 3.12, uv, Pydantic, Anthropic SDK, python-dotenv, pytest (dev) |

**No new packages.** If the plan seems to need one, stop and ask first.

**Why not Postgres/Supabase now:** one user, one process, local only, no
concurrent writers. Postgres adds an account, credentials and an online attack
surface for no benefit yet. The upgrade path is cheap by design: **all database
code lives in `services/storage.py`**, so moving to Postgres later means
rewriting that one file. Nothing else in the codebase may touch SQL.

## Folder structure (changes only)
```
silverpath-triage/
├── src/silverpath_triage/
│   ├── config.py            # CHANGED: no import-time key check; adds DB_PATH
│   ├── main.py              # CHANGED: argparse subcommands; JSON write removed
│   ├── models/
│   │   ├── triage.py        # UNCHANGED
│   │   └── entry.py         # NEW: HumanVerdict, TriageEntry
│   └── services/
│       ├── triage.py        # CHANGED: key check moves here (client creation)
│       └── storage.py       # NEW: all SQLite code, nothing else
├── data/
│   └── triage.db            # created at runtime; gitignored, NEVER committed
├── tests/
│   ├── test_triage_evals.py # CHANGED: marked `eval` only; cases untouched
│   ├── test_config.py       # NEW: the two config proofs, zero API calls
│   ├── test_entry.py        # NEW: model checks, zero API calls
│   ├── test_main.py         # NEW: CLI checks, temp DB, zero API calls
│   └── test_storage.py      # NEW: storage tests, temp DB, zero API calls
├── docs/
│   ├── PRD.md               # build #1, UNTOUCHED
│   ├── TECHNICAL_PRD.md     # build #1, UNTOUCHED
│   ├── PRD-build-02.md      # NEW
│   └── TECHNICAL_PRD-build-02.md  # NEW
├── .gitignore               # CHANGED: database files added
├── pyproject.toml           # CHANGED: register the `eval` pytest marker only
├── README.md                # CHANGED: new commands + test commands
└── CLAUDE.md                # CHANGED: evolved for build #2
```
Leave the existing `data/outputs/` folder and its files on disk alone. Don't
delete them, and keep `data/outputs/` in `.gitignore`.

## The config improvement
- `config.py` still loads `.env` and exposes `ANTHROPIC_API_KEY`, but it **no
  longer raises at import** when the key is missing or blank.
- `config.py` gains `DB_PATH = PROJECT_ROOT / "data" / "triage.db"`.
- The key check moves into `services/triage.py`, immediately before the
  Anthropic client is created. If the key is missing or blank, it raises
  `TriageError` with the same clear message as today (it names
  `ANTHROPIC_API_KEY` and points to `.env.example`). `main.py` already catches
  `TriageError`, so the user sees a clean error and no traceback.
- `services/triage.py` must read the key **at call time** (e.g. `config.ANTHROPIC_API_KEY`),
  not copy it at import with `from config import ANTHROPIC_API_KEY`. Otherwise
  tests can't control it.
- `OUTPUTS_DIR` is no longer used. Remove it from `config.py`.

**Two required proofs (`tests/test_config.py`):**
1. Importing config with no key does not raise. Gotcha: `config.py` loads the
   real `.env` by absolute path, so the test must make sure the key is genuinely
   absent. Suggested approach: run `import silverpath_triage.config` in a
   subprocess with `ANTHROPIC_API_KEY` set to an empty string in its
   environment. python-dotenv does not override an existing variable by
   default, so the real key won't load. Confirm in plan mode.
2. `triage_enquiry("some text")` with the key blanked raises `TriageError`
   mentioning `ANTHROPIC_API_KEY`, and **no client is created**. Prove it by
   replacing the Anthropic client constructor with a stand-in that fails the
   test if called.

## Data shapes (`models/entry.py`)
`TriageRecord` in `models/triage.py` is **not modified**. The new models wrap it:

```python
from pydantic import AwareDatetime, BaseModel, Field
from silverpath_triage.models.triage import Intent, Route, TriageRecord

class HumanVerdict(BaseModel):
    correct_intent: Intent | None = None
    correct_route: Route | None = None
    reviewed_at: AwareDatetime | None = None   # UTC, timezone-aware

class TriageEntry(BaseModel):
    id: int | None = None                 # None until saved; set by the database
    created_at: AwareDatetime             # UTC, timezone-aware
    source: str                           # enquiry file path as given
    enquiry_text: str                     # the full original enquiry
    model: str                            # config.MODEL at run time
    confidence_threshold: float           # config.CONFIDENCE_THRESHOLD at run time
    schema_version: int = 1
    record: TriageRecord                  # unchanged build #1 output
    verdict: HumanVerdict = Field(default_factory=HumanVerdict)  # empty on creation
```

## Database design
One table, `entries`. It is a **hybrid**: the full record is stored as JSON (the
source of truth), and a few fields are copied into their own columns purely so
they can be filtered.

```sql
CREATE TABLE IF NOT EXISTS entries (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at           TEXT    NOT NULL,  -- ISO 8601, UTC, with offset
    source               TEXT    NOT NULL,
    enquiry_text         TEXT    NOT NULL,
    model                TEXT    NOT NULL,
    confidence_threshold REAL    NOT NULL,
    schema_version       INTEGER NOT NULL,
    record_json          TEXT    NOT NULL,  -- full TriageRecord: SOURCE OF TRUTH
    intent               TEXT    NOT NULL,  -- copied from record, for filtering
    suggested_route      TEXT    NOT NULL,  -- copied
    urgency              TEXT    NOT NULL,  -- copied
    confidence           REAL    NOT NULL,  -- copied
    needs_review         INTEGER NOT NULL,  -- copied; 0/1
    verdict_intent       TEXT,              -- NULL until verified
    verdict_route        TEXT,              -- NULL until verified
    verdict_reviewed_at  TEXT               -- NULL until verified
);
```

Rules:
- **`record_json` is the source of truth.** On read, rebuild the record with
  `TriageRecord.model_validate_json(record_json)`. The copied columns are
  written from the same record in the same insert and are never edited
  separately.
- **Datetimes are stored as ISO 8601 text with the UTC offset** and parsed back
  into timezone-aware datetimes. Don't rely on `sqlite3`'s built-in datetime
  adapters (deprecated since Python 3.12).
- **Every query uses `?` placeholders. Never build SQL with f-strings or string
  joining.** Enquiry text is untrusted public input. Placeholders are what stop
  it from being run as SQL (the "SQL injection" attack).
- **`PRAGMA secure_delete = ON`** on every connection, so deleted entries are
  overwritten in the file rather than merely unlinked.
- The table is created on first use (`CREATE TABLE IF NOT EXISTS`), and the
  `data/` folder is created if missing. No migration tooling in this build.

## Storage module (`services/storage.py`)
All SQL lives here and nowhere else. Every function takes
`db_path: Path = config.DB_PATH`, so tests can pass a temporary database.
Connections are opened per call and always closed.

| Function | Does | Returns |
| --- | --- | --- |
| `init_db(db_path)` | Create folder and table if missing | `None` |
| `save_entry(entry, db_path)` | Insert a new entry (its `id` must be `None`) | the new `id` |
| `get_entry(entry_id, db_path)` | Fetch one | `TriageEntry` or `None` |
| `list_entries(limit=20, needs_review_only=False, db_path)` | Newest first | `list[TriageEntry]` |
| `set_verdict(entry_id, intent, route, db_path)` | Store verdict, `reviewed_at` = now (UTC) | `True` if found, else `False` |
| `delete_entry(entry_id, db_path)` | Remove one entry | `True` if found, else `False` |

Storage functions do no printing. `main.py` handles all user-facing output.

## Commands (`main.py`, via `argparse`)
| Command | Behaviour |
| --- | --- |
| `triage <file>` | Read the file, triage, **print exactly as today** (`format_record` kept), build a `TriageEntry` (model and threshold from `config`, `created_at` = now UTC), save it, print `Saved as entry <id>`. Save only after a successful triage. **No JSON file.** |
| `list [--needs-review] [--limit N]` | One line per entry: id, date, intent, route, confidence, review flag, verified yes/no, source |
| `show <id>` | Entry details, the printed triage result, the original enquiry text, and the verdict (or "not yet verified") |
| `verify <id> --intent X --route Y` | Values restricted to the `Intent` / `Route` enum choices; store the verdict and confirm |
| `delete <id> [--yes]` | Show the entry's id, date and source; ask `y/N` unless `--yes`; delete; confirm |

- Running with no command prints help.
- The old form `main <file>` is retired in favour of `main triage <file>`.
  Update the README.
- Unknown id: a clear "No entry with id N" and a non-zero exit, no traceback.
- `list`, `show`, `verify` and `delete` must never create an Anthropic client.

## Tests and cost control
| File | What | API calls |
| --- | --- | --- |
| `tests/test_config.py` | The two config proofs | **0** |
| `tests/test_entry.py` | Models, built from a hand-made `TriageRecord`: new entry defaults (`id` None, `schema_version` 1); verdict starts empty and isn't shared between entries; record wrapped unchanged; JSON round-trip returns an equal entry with a UTC-aware `created_at` (and with a filled verdict); invalid verdict values and naive datetimes rejected | **0**, no database |
| `tests/test_storage.py` | Round-trip (saved entry == retrieved entry, including datetimes and confidence); persistence across separate connections; newest-first ordering; `needs_review_only` filter; new entry has empty verdict; `set_verdict` stores and returns correctly; `delete_entry` removes; unknown ids return `None`/`False` | **0**, using a hand-built `TriageRecord` and pytest's `tmp_path` database |
| `tests/test_main.py` | CLI driven in-process: `triage` prints the result exactly then `Saved as entry <id>`, saves the right entry and writes no JSON; a failed triage or missing file saves nothing; `list` order, columns, `--needs-review`, `--limit` (must be 1 or more); `show` details, enquiry text and verdict; unknown or non-integer id; `verify` stores the verdict (choices limited to the enums, re-verify says it replaced one) and `show` displays it; `delete` prompts and only `y`/`yes` deletes (`n`, empty and end-of-input keep it; `--yes` skips the prompt; unknown id shows no prompt); `list`/`show`/`verify`/`delete` never create a client; database problems give a clean error | **0**: the client constructor fails the test if called, triage is stubbed with a hand-made result, `config.DB_PATH` points at a `tmp_path` database |
| `tests/test_triage_evals.py` | Existing 9 evals, now marked `eval` (module-level `pytestmark`). Cases, labels and assertions untouched. Evals never write to the database | **9** |

- Register the `eval` marker in `pyproject.toml` so pytest doesn't warn.
- **Free run:** `uv run pytest -m "not eval"`. **Paid run:** `uv run pytest -m eval -s`.
- Storage tests must never touch the real `data/triage.db`.

## Environment and git setup
1. `.gitignore` gains `data/*.db`, `data/*.db-journal`, `data/*.db-wal` and
   `data/*.db-shm`. **This lands in the first commit of this build, before any
   database file can exist.**
2. No new dependencies, no new secrets. `.env.example` is unchanged.

## Secrets
Unchanged: `ANTHROPIC_API_KEY` only, in `.env`, loaded via `config.py`. Never
hardcoded, printed or committed.

## Build sequence (small, reviewable, commit before and after each; stop and report after each)
0. **Handover docs + guardrails.** Add `docs/PRD-build-02.md`,
   `docs/TECHNICAL_PRD-build-02.md`, the updated `CLAUDE.md`, and the
   `.gitignore` additions. Commit. *(First commit of build #2: check it has no
   attribution trailer.)*
1. **Config improvement + test split.** Move the key check, add `DB_PATH`, add
   `tests/test_config.py`, mark evals as `eval`, register the marker. Prove:
   `pytest -m "not eval"` passes with zero API calls. *(teaches: import-time vs
   call-time behaviour, test cost control)*
2. **Models.** Write `models/entry.py`. *(teaches: wrapping a model without
   changing it)*
3. **Storage module + tests.** Write `services/storage.py` and
   `tests/test_storage.py`. Prove round-trip fidelity. *(teaches: SQL basics,
   placeholders, source-of-truth design)*
4. **Wire `triage`, `list`, `show`.** Convert `main.py` to subcommands and
   remove the JSON write. Then run **one** real triage on
   `data/samples/enquiry_01.txt` (one API call, pennies), then `list` and
   `show`. *(teaches: CLI structure, end-to-end flow)*
5. **Add `verify` and `delete`.** Test both by hand on the entry from step 4.
   *(teaches: updates, irreversible actions, confirmation)*
6. **README + acceptance check.** Update the README. Walk through every PRD
   acceptance criterion and report pass/fail for each. Run the paid evals once,
   only when asked.

## Cost and safety
- New API spend: only the triage runs you choose to do (step 4's single run,
  plus the one paid eval run in step 6, which is 9 calls). All other tests are
  free.
- Security: database gitignored first; parameterised SQL only; secure delete
  on; confirmation before delete; fictional sample data only.