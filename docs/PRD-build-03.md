# PRD — Silverpath Inbound-Enquiry Triage, Build #3: Escalation flag

## Context
Builds #1 (AI layer) and #2 (SQLite storage) are complete. Build #2 closed with
`docs/ACCEPTANCE-build-02.md` (12 of 12 PASS), which carried forward one known
limitation: the escalation gap. Earlier builds' docs stay where they are,
unchanged, as background.

## Problem
`needs_review` is computed only from confidence (`confidence < 0.6`). The model
is told to route sensitive enquiries (vulnerable customers, safety, legal
threats, unclear messages) to `human_review`. It often does this with high
confidence, so `needs_review` stays off and the enquiry never appears in
`list --needs-review`.

Evidence (from `ACCEPTANCE-build-02.md`):
- Entry 1 in the real database, a vulnerable household, was routed to
  `human_review` at confidence 0.90 and stored with `needs_review = no`.
- In the paid eval run, `other_job_application` (0.92) and
  `vulnerable_new_enquiry` (0.85) show the same pattern.

The model is behaving as instructed. The gap is in our code: nothing turns
"routed to a person" into a flag a person will see.

## Decision
Keep `needs_review` exactly as it is, and add a separate flag, `escalate`.

| Flag | Meaning in one line | How it is set |
| --- | --- | --- |
| `needs_review` | The model is unsure | Stored snapshot: `confidence < threshold`, computed by code at triage time. **Unchanged** |
| `escalate` | A person must see this | Computed by code every time it is read: `needs_review OR suggested_route == human_review`. **Never stored** |

Why not change `needs_review` itself: stored entries (including Entry 1) were
computed under the old rule. Changing the meaning would either leave one field
name with two meanings in the database, or require rewriting stored records,
which breaks the build #2 rule that `record_json` is never modified.

Why `escalate` is never stored: a stored copy is a frozen value that goes stale
when the rule changes. That is this build's bug, repeated. Because `escalate`
is computed from facts already in every record (`needs_review` and
`suggested_route`), every entry, old or new, gets the correct value on read,
with no backfill and no database change.

## Type
**Proof of Concept (PoC).** Same system as builds #1–#2: run by hand on one
machine, no users. Only the escalation rule changes.

## The one workflow
`TriageResult` (from the model) → `build_record()` → `TriageRecord` with
`needs_review` (stored, unchanged) and `escalate` (computed on read) → saved as
today → `list --escalated` shows every entry a person must see, with the
reason.

- **Input:** a `TriageResult` from the model (unchanged).
- **Output:** a `TriageRecord` whose `escalate` flag is true for both
  low-confidence and `human_review`-routed enquiries, and a review queue
  (`list --escalated`) that shows them.

## Scope (MoSCoW)

| Priority | Item |
| --- | --- |
| Must | `escalate` on `TriageRecord`, computed by code from `needs_review` and `suggested_route`; never serialised or stored |
| Must | `needs_review` unchanged in meaning, computation and storage |
| Must | `list --escalated`: only entries where `escalate` is true |
| Must | `--escalated` and `--needs-review` cannot be used together (command-line error) |
| Must | A "Why" column in `list`: `low conf` / `routed` / `both` / `-` |
| Must | `triage` and `show` print an `Escalate:` line with its reason |
| Must | Tests proving `escalate` is always recomputed on read, including a tamper test seen to fail first |
| Must | Paid eval output prints `escalate` per case. Cases, labels and assertions unchanged |
| Must | README documents `list --escalated` and defines both flags in one line each |
| Must | No commit from this build carries a Claude attribution trailer |
| Won't | Other escalation triggers (e.g. high urgency) |
| Won't | Any change to the prompt, model, threshold or eval labels |
| Won't | Database schema change, migration or backfill |
| Won't | `£` display fix, journal-file secure delete, `export`, duplicate detection (carried forward from build #2) |
| Won't | API, frontend, automation, Postgres |

## Observable acceptance criteria
The build is done when:
1. `TriageRecord.escalate` is `True` exactly when `needs_review` is true or
   the route is `human_review`. A free test covers all four combinations.
2. `needs_review` is unchanged in meaning and computation. Existing build #2
   tests pass. The only existing assertion edited is the column check in
   `test_list_newest_first_and_columns`, which gains the new "Why" value
   (required by criterion 6).
3. `escalate` is never stored: a saved entry's raw `record_json` has no
   `escalate` key; a record whose stored JSON contains a planted, wrong
   `escalate` value reads back with the correct computed value (both
   directions); and a `record_json` written by build #2 (no `escalate` key)
   loads with the correct value.
4. The tamper test was seen to fail against a deliberately wrong
   stored-field version before it passed. The failing output is captured in
   the step report.
5. `list --escalated` shows exactly the entries where `escalate` is true. A
   free test proves the SQL filter matches the Python property across all four
   combinations.
6. `list` shows a "Why" column (`low conf` / `routed` / `both` / `-`).
   `list --needs-review` behaves exactly as before.
7. `triage` and `show` print an `Escalate:` line with its reason.
8. On the real database, with no re-triage and the API key blanked,
   `list --escalated` shows Entry 1 with reason `routed`, and
   `list --needs-review` still does not show it.
9. `uv run pytest -m "not eval"` passes with zero API calls.
10. One paid eval run (9 calls): all 9 pass with labels unchanged, and the
    output prints `escalate` per case (expected `True` for 06, 07 and 08).
11. No commit from this build carries a Claude attribution trailer.
12. `--escalated` and `--needs-review` are mutually exclusive: using both
    gives a command-line error (exit code 2). A free test proves it.
13. README documents `list --escalated` and defines both flags in one line
    each: `needs_review` = "the model is unsure"; `escalate` = "a person must
    see this".

## Accuracy bar
- **The escalation rule: 100%.** It is deterministic code, so every one of the
  four combinations must be correct, proven by tests.
- **Triage accuracy is unchanged and not re-measured.** The prompt, model and
  threshold do not change. The single paid eval run confirms nothing
  regressed and shows `escalate` on real model output.

## Error handling
- **Escalation design:** the playbook's escalation pattern (doc 03). The
  confident majority is routed automatically; anything the model is unsure
  about, *or* routes to a person, goes to the `--escalated` queue.
- **Command line:** combining `--escalated` with `--needs-review` is rejected
  before anything runs. All other error behaviour is unchanged from build #2.

## Data / privacy
No change. No new data is stored, and no stored record is modified. Only the
fictional samples in `data/samples/` are used. The real `data/triage.db` is
read, never written, during the criterion 8 check.

## Cost
One paid eval run at acceptance (9 calls, pennies), only when asked. Every
other check is free, including criterion 8.

## Out of scope
- New escalation triggers, prompt/model/threshold changes, eval label changes.
- Database schema changes, migrations or rewriting stored records.
- Build #2's other carried-forward items (`£` display, journal secure delete,
  `export`, duplicate detection).
- Editing, moving or renaming earlier builds' docs.