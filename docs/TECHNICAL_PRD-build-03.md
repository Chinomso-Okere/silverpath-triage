# Technical PRD — Silverpath Inbound-Enquiry Triage, Build #3: Escalation flag

The *how* for `docs/PRD-build-03.md`. Earlier builds' docs are background and
are not edited. Where this doc and general habit disagree, this doc wins for
this build. Anything not covered here: stop and ask.

## Stack
**Unchanged.** Python 3.12, uv, Pydantic, Anthropic SDK, python-dotenv,
SQLite via `sqlite3`, `argparse`, pytest (dev). **No new dependencies.** Model
(`claude-haiku-5-5`), prompt and threshold (0.6) are unchanged.

## Files touched
```
silverpath-triage/
├── src/silverpath_triage/
│   ├── models/triage.py      # CHANGED: escalate property on TriageRecord (no new fields)
│   ├── services/storage.py   # CHANGED: escalated_only filter in list_entries
│   └── main.py               # CHANGED: --escalated, Why column, Escalate line
├── tests/
│   ├── test_entry.py         # CHANGED: escalate truth table, not serialised, legacy JSON
│   ├── test_storage.py       # CHANGED: tamper, raw record_json, SQL/Python parity
│   ├── test_main.py          # CHANGED: new CLI tests; ONE existing assertion edited
│   └── test_triage_evals.py  # CHANGED: print line only
├── docs/
│   ├── PRD-build-03.md       # NEW
│   ├── TECHNICAL_PRD-build-03.md  # NEW
│   └── ACCEPTANCE-build-03.md     # NEW, final step
├── README.md                 # CHANGED
└── CLAUDE.md                 # CHANGED: evolved for build #3
```
Not touched: `config.py`, `services/triage.py` (`needs_review()` and
`build_record()` stay exactly as they are), `models/entry.py`, the prompt,
`pyproject.toml`, `.gitignore`, and all earlier builds' docs.

## The `escalate` property (`models/triage.py`)
Add a plain Python `@property` to `TriageRecord`. **Not** a field, and **not**
a Pydantic `computed_field`:

```python
class TriageRecord(TriageResult):
    needs_review: bool

    @property
    def escalate(self) -> bool:
        # A person must see this: the model is unsure, or it routed to a person.
        # Computed on every read; never serialised or stored.
        return self.needs_review or self.suggested_route == Route.human_review
```

Why a plain property:
- Pydantic never includes a plain property in `model_dump()` or
  `model_dump_json()`, so `escalate` can't reach `record_json`. Nothing has to
  remember to exclude it.
- It does not change record equality, so build #2's round-trip tests stay
  valid.
- A `computed_field` *is* serialised by default, which would store a stale
  copy.
- Trade-off, recorded for later: if a future build exposes records as JSON
  (e.g. an API), `escalate` won't appear automatically. That build decides
  explicitly, e.g. a `computed_field` excluded at the storage boundary.

Rules:
- Add **no fields** to `TriageRecord` or `TriageResult`. The property goes on
  `TriageRecord` only. `TriageResult` is the schema sent to the model, and it
  must not change.
- Do **not** add a `model_config` (e.g. `extra="allow"`) to either model. With
  Pydantic's default (`extra` ignored), a planted `"escalate"` key in stored
  JSON is dropped on read, which the tamper test relies on.
- Confirm in plan mode, with a quick check, that the installed Pydantic
  version omits plain properties from `model_dump_json()`.

## Storage (`services/storage.py`)
`list_entries` gains `escalated_only: bool = False`:

```python
def list_entries(limit=20, needs_review_only=False, escalated_only=False, db_path=...):
```

- If both `needs_review_only` and `escalated_only` are true, raise
  `ValueError` (a guard behind the command-line check).
- Extend the list query. The `human_review` value is passed as a `?`
  placeholder from `Route.human_review.value`, never typed into the SQL:

```sql
SELECT ... FROM entries
WHERE (? = 0 OR needs_review = 1)
  AND (? = 0 OR needs_review = 1 OR suggested_route = ?)
ORDER BY id DESC
LIMIT ?
```
  Parameters: `(int(needs_review_only), int(escalated_only),
  Route.human_review.value, limit)`.
- **No schema change.** It uses the existing `needs_review` and
  `suggested_route` columns. Nothing is written, migrated or backfilled.
- The rule now exists in two places (the property and this SQL). The parity
  test below is what stops them drifting apart.

## Command line (`main.py`)
- `list`: put `--needs-review` and `--escalated` in an argparse **mutually
  exclusive group**. Using both is an argparse error (exit 2). `--needs-review`
  is otherwise unchanged.
- `list --escalated` with no matches prints `No entries need escalation.`
- A helper `escalation_reason(record) -> str` returns `"low conf"` (needs
  review only), `"routed"` (human_review only), `"both"`, or `"-"`. It must
  agree with `record.escalate`: `"-"` exactly when `escalate` is false.
- **Why column:** add a `Why` column to `LIST_HEADER` and `format_list_line`,
  directly after `Review`, showing `escalation_reason(record)`.
- **Escalate line:** in `format_record`, directly after `Needs review:`, add
  `Escalate:       ` followed by `no`, `YES (low confidence)`,
  `YES (routed to human_review)` or
  `YES (low confidence and routed to human_review)`. Because `triage` and
  `show` both print via `format_record`, both get it.

## Tests (all free unless marked)

| File | Test | Proves |
| --- | --- | --- |
| `test_entry.py` | Truth table: all four combinations of `needs_review` × route (`human_review` / `sales`) | Criterion 1 |
| `test_entry.py` | `"escalate"` not in `json.loads(record.model_dump_json())` or `record.model_dump()` | Not serialised |
| `test_entry.py` | Legacy: a `record_json` string exactly as build #2 wrote Entry 1's shape (no `escalate` key, `needs_review: false`, route `human_review`) validates with `escalate is True` | Criterion 3 (legacy) |
| `test_storage.py` | Raw check: save an entry, read its `record_json` with raw SQL, confirm no `escalate` key | Criterion 3 (nothing stored) |
| `test_storage.py` | **Tamper:** save a record (route `human_review`, confidence 0.9, `needs_review` false), raw-SQL rewrite its `record_json` to include `"escalate": false`, read via `get_entry()` → `escalate is True`. Mirror: route `sales`, `needs_review` false, plant `"escalate": true` → `False` | Criteria 3, 4 |
| `test_storage.py` | Parity: save all four combinations; `list_entries(escalated_only=True)` returns exactly the ids where `record.escalate` is true | Criterion 5 |
| `test_storage.py` | `needs_review_only=True` and `escalated_only=True` together → `ValueError` | Guard |
| `test_main.py` | `list --escalated` output and order; empty message; Why column values for all four combinations; `escalation_reason` agrees with `escalate` | Criteria 5, 6 |
| `test_main.py` | `list --needs-review --escalated` → exit 2, error mentions both flags | Criterion 12 |
| `test_main.py` | `--needs-review` unchanged (existing test passes untouched) | Criterion 6 |
| `test_main.py` | `Escalate:` line text for all four combinations; `show` includes it | Criterion 7 |
| `test_triage_evals.py` | **Paid.** Add `escalate={record.escalate}` to the per-case print. Cases, labels and assertions untouched | Criterion 10 |

**Raw SQL in tests.** Tests may use raw SQL only to inspect or tamper with
stored data, always with `?` placeholders, only against the temporary
`tmp_path` database. These tests go in `test_storage.py`, so the existing
autouse `connections` guard (fails any test that opens the real
`data/triage.db`) applies to them. Application code still keeps all SQL in
`storage.py`.

**The one existing assertion that changes.** In
`test_list_newest_first_and_columns`, the expected columns
`["new_enquiry", "sales", "0.87", "no", "no", "file_2.txt"]` gain the Why value
`"-"` after the Review value. No other existing test is edited. If any other
existing test fails, stop and report; don't edit it.

**Seen to fail (playbook doc 04, Principle 7).** In step 1:
1. Write the tests first.
2. Temporarily implement `escalate` the *wrong* way, as an ordinary stored
   field (`escalate: bool = False`, set in `build_record`).
3. Run the tamper and legacy tests. They must fail. Copy the failing output
   into the step report.
4. Throw the wrong version away (`git restore`), never commit it, implement
   the property, and run again: pass.

## Build sequence (small, reviewable; commit and push after each; stop and report after each)
0. **Handover docs.** Add `docs/PRD-build-03.md`,
   `docs/TECHNICAL_PRD-build-03.md`, and the evolved `CLAUDE.md`. Commit and
   push. Check the commit has no attribution trailer
   (`git log -1 --format='%(trailers)'` is empty).
1. **The property + model/storage proofs.** Write the `test_entry.py` tests
   and the raw, tamper and legacy tests in `test_storage.py`. Do the
   seen-to-fail sequence above. Then add the property. Free run passes.
   *(teaches: derived vs stored data, proving a test can fail)*
2. **Storage filter.** Add `escalated_only` with the guard, plus the parity
   and guard tests. Free run passes. *(teaches: one rule in two places, and
   the test that keeps them in step)*
3. **Command line.** Add `--escalated` (mutually exclusive group), the Why
   column, the `Escalate:` line, the `test_main.py` tests, and the one
   declared assertion edit. Free run passes. *(teaches: argparse groups,
   output as a contract)*
4. **Real-database check + README + eval print.** With the API key blanked in
   the shell, run `list`, `list --escalated` and `list --needs-review` against
   the real database (read-only; no triage). Paste the output. Update the
   README: commands table, and one line each defining `needs_review` and
   `escalate` (wording from the PRD). Add the `escalate=` print to the eval
   file. *(teaches: proving a fix on real stored data at zero cost)*
5. **Acceptance.** Run the free suite with the key blanked. Run the paid evals
   **once, only when asked**. Write `docs/ACCEPTANCE-build-03.md`: every PRD
   criterion with PASS/FAIL and evidence (test name, code commit, or output
   captured in this step), plus "Known limitations / carried forward". Cite
   the last code commit, never the acceptance doc's own hash.

## Secrets
Unchanged: `ANTHROPIC_API_KEY` only, in `.env`, loaded via `config.py`.

## Cost and safety
- API spend: one paid eval run (9 calls) at step 5, only when asked. Steps 1–4
  are free; step 4's real-database check needs no key.
- No stored data is written or modified by this build. Tests never open the
  real database (guarded).