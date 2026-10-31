# Acceptance check — Build #3: Escalation flag

Checks every acceptance criterion in `docs/PRD-build-03.md` against evidence.
Evidence is a test name, a commit hash, or output captured during the
acceptance step (2026-10-31). **Code verified at `538159d`**, the last commit
before this document. Application code last changed in `e6d552e`; `538159d`
changed only the README and the eval print line.

**Result: 13 of 13 PASS.**

## Runs captured during the acceptance step

**Free run, API key blanked** (`ANTHROPIC_API_KEY= uv run pytest -m "not eval" -v`, Git Bash):
```
test_config.py 2, test_entry.py 14, test_main.py 52, test_storage.py 24
====================== 92 passed, 9 deselected in 7.72s =======================
```
All 65 build #2 tests are among the 92 and pass; the only one edited is the
declared column assertion (see criterion 2).

**Paid eval run, made once** (`uv run pytest -m eval -s -v`, 9 API calls):
```
new_enquiry            intent=new_enquiry       route=sales         confidence=0.95 needs_review=False escalate=False PASSED
existing_booking       intent=existing_customer route=support       confidence=0.92 needs_review=False escalate=False PASSED
complaint              intent=complaint         route=support       confidence=0.92 needs_review=False escalate=False PASSED
billing_refund         intent=billing           route=billing       confidence=0.93 needs_review=False escalate=False PASSED
spam_seo               intent=spam              route=ignore        confidence=0.97 needs_review=False escalate=False PASSED
other_job_application  intent=other             route=human_review  confidence=0.85 needs_review=False escalate=True  PASSED
vulnerable_new_enquiry intent=new_enquiry       route=human_review  confidence=0.85 needs_review=False escalate=True  PASSED
vague_short            intent=other             route=human_review  confidence=0.30 needs_review=True  escalate=True  PASSED
mixed_complaint_bill   intent=complaint         route=support       confidence=0.85 needs_review=False escalate=False PASSED
====================== 9 passed, 92 deselected in 24.96s ======================
```

**Real database, read-only, API key blanked.** No `triage`, `verify` or
`delete`; the SHA-256 was taken before the commands below and again after
the paid run, so it covers both:
```
SHA-256 before: 7f5c8653b5c896ae07472b363a06ff946287ae406edd7f7e1af35f07ef608fa2
SHA-256 after:  7f5c8653b5c896ae07472b363a06ff946287ae406edd7f7e1af35f07ef608fa2

$ list
 ID  Created (UTC)     Intent             Route         Conf  Review  Why       Verified  Source
  1  2026-10-31 00:44  new_enquiry        human_review  0.90  no      routed    yes       data/samples/enquiry_01.txt
$ list --escalated
 ID  Created (UTC)     Intent             Route         Conf  Review  Why       Verified  Source
  1  2026-10-31 00:44  new_enquiry        human_review  0.90  no      routed    yes       data/samples/enquiry_01.txt
$ list --needs-review
No entries need review.
$ show 1  (triage result section)
Confidence:     0.90 (threshold 0.60)
Needs review:   no
Escalate:       YES (routed to human_review)

$ ls -la data/          → triage.db 12288 bytes, modified 00:58 (unchanged); no -journal file
$ git status --short    → (empty)
```

**Repository checks:**
```
$ git log 875effc..HEAD --format="%h %s | trailers=[%(trailers)]"
538159d Document escalate in README and print it in evals (step 4) | trailers=[]
e6d552e Add list --escalated, Why column and Escalate line (step 3) | trailers=[]
c061509 Add escalated_only filter to list_entries (step 2) | trailers=[]
6e71b13 Add computed escalate property to TriageRecord (step 1) | trailers=[]
9dfaac1 Add build #3 handover docs and update CLAUDE.md (step 0) | trailers=[]
$ git log 875effc..HEAD --format=%B | grep -ciE "co-authored-by|claude-session"
0
$ git diff 875effc -- src/silverpath_triage/services/triage.py src/silverpath_triage/config.py \
      src/silverpath_triage/models/entry.py src/silverpath_triage/prompts/
(empty)
$ git diff 875effc -- src/silverpath_triage/models/triage.py      (additions only, 0 removed lines)
 class TriageRecord(TriageResult):
     needs_review: bool
+
+    @property
+    def escalate(self) -> bool:
+        # A person must see this: the model is unsure, or it routed to a person.
+        # Computed on every read; never serialised or stored.
+        return self.needs_review or self.suggested_route == Route.human_review
$ git diff 875effc -- tests/test_triage_evals.py                 (print line only)
-        f"confidence={record.confidence:.2f} needs_review={record.needs_review}"
+        f"confidence={record.confidence:.2f} needs_review={record.needs_review} escalate={record.escalate}"
$ git diff 875effc -- tests/ | grep -E '^-[^-]'                  (every removed test line)
-    assert first[3:] == ["new_enquiry", "sales", "0.87", "no", "no", "file_2.txt"]
-    ContactInfo, Intent, KeyDetails, Route, TriageRecord, Urgency,
-        f"confidence={record.confidence:.2f} needs_review={record.needs_review}"
```
The three removed test lines are: the one declared assertion (replaced by the
same list with the Why value `"-"` after Review), the `test_storage.py`
models-import line (replaced to add `TriageResult`; not a test), and the eval
print line.

## Criteria

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | `TriageRecord.escalate` is `True` exactly when `needs_review` is true or the route is `human_review`; a free test covers all four combinations | PASS | `test_escalate_truth_table` (4 cases); `test_escalation_reason_agrees_with_escalate` (4 cases). Commit `6e71b13` |
| 2 | `needs_review` unchanged in meaning and computation; build #2 tests pass; the only edited assertion is the column check in `test_list_newest_first_and_columns` | PASS | `services/triage.py` (`needs_review()`, `build_record()`), `config.py` (threshold 0.6), `models/entry.py` and the prompt are unchanged since `875effc` (empty diff above); `models/triage.py` diff is additions only (the `escalate` property, no fields); all 65 build #2 tests pass in the free run; removed-test-lines listing above |
| 3 | `escalate` is never stored: no key in raw `record_json`; a planted wrong value reads back correct (both directions); a build #2 `record_json` loads correctly | PASS | `test_record_json_has_no_escalate_key` (raw SQL read; also reads back escalated via `get_entry()`); `test_planted_escalate_is_ignored_on_read[human_review-False-True]` and `[sales-True-False]`; `test_legacy_build_2_record_json_escalates`; `test_escalate_is_not_serialised`. Commit `6e71b13` |
| 4 | The tamper test was seen to fail against a deliberately wrong stored-field version first; failing output captured in the step report | PASS | This is the one criterion about an earlier step, so its evidence is step 1's run, not this step's. Against `escalate: bool = False` set in `build_record` (never committed): `8 failed, 28 passed`, including both `test_planted_escalate_is_ignored_on_read` cases (planted value won), `test_legacy_build_2_record_json_escalates` and `test_record_json_has_no_escalate_key`. Full output is in the step 1 report; recorded in the `6e71b13` commit message |
| 5 | `list --escalated` shows exactly the entries where `escalate` is true; a free test proves SQL filter = Python property across all four combinations | PASS | `test_escalated_only_matches_property` (seen to fail in step 2 without the route clause: `[4, 2] == [4, 3, 2]`); `test_list_escalated_contents_and_order`; `list --escalated` above. Commits `c061509`, `e6d552e` |
| 6 | `list` shows a Why column (`low conf` / `routed` / `both` / `-`); `list --needs-review` behaves exactly as before | PASS | `test_list_why_column` (all four values, read by column position); `test_list_newest_first_and_columns` (declared edit); unedited `test_list_needs_review_and_limit`, `test_list_empty`, `test_list_needs_review_only`; `test_list_needs_review_ignores_routing`; `list` and `list --needs-review` above |
| 7 | `triage` and `show` print an `Escalate:` line with its reason | PASS | `test_format_record_escalate_line` (4 cases); `test_show_includes_escalate_line`; `test_triage_includes_escalate_line`; `show 1` above. Commit `e6d552e` |
| 8 | Real database, no re-triage, key blanked: `list --escalated` shows Entry 1 with `routed`; `list --needs-review` does not show it | PASS | real-database outputs above, with identical SHA-256 before and after |
| 9 | `uv run pytest -m "not eval"` passes with zero API calls | PASS | free run above: 92 passed with the key blanked (any client creation would fail; `test_commands_never_create_client` also guards the CLI) |
| 10 | One paid eval run: all 9 pass with labels unchanged; output prints `escalate` per case (`True` for 06, 07, 08) | PASS | paid run above: 9 passed; `escalate=True` for `other_job_application`, `vulnerable_new_enquiry`, `vague_short` and `False` for the rest; eval-file diff since `875effc` is the print line only |
| 11 | No commit from this build carries a Claude attribution trailer | PASS | trailer listing above: empty for every build #3 commit; 0 `co-authored-by` or `claude-session` lines in any message |
| 12 | `--escalated` and `--needs-review` are mutually exclusive: both gives a command-line error (exit 2); a free test proves it | PASS | `test_list_needs_review_and_escalated_together_is_rejected` (exit 2, error names both flags, no database opened; seen to fail in step 3 with the flags as ordinary options); `test_needs_review_and_escalated_together_is_rejected` (storage guard behind it). Commits `c061509`, `e6d552e` |
| 13 | README documents `list --escalated` and defines both flags in one line each | PASS | README commands row `list [--needs-review \| --escalated] [--limit N]`; `needs_review` = "the model is unsure"; `escalate` = "a person must see this"; `test_list_help_defines_both_flags` (same definitions in `list --help`). Commit `538159d` |

## Known limitations / carried forward

**Resolved from build #2:** the escalation gap. Entry 1 (`human_review` at
0.90, `needs_review = no`) now appears in `list --escalated` with no change
to stored data.

**Still open from build #2:**
- **Secure delete covers the database file only.** SQLite's temporary
  rollback-journal file is removed by the operating system, not overwritten.
  Revisit before handling real enquiries, together with retention and
  encryption at rest.
- **`£` shows as `�` in some Windows shells.** Display only; data is stored as
  UTF-8 (`test_non_ascii_text_round_trips`).
- **Not built:** duplicate-enquiry detection; `export <id>` to turn a verified
  entry into an eval case.

**Surfaced in this build:**
- **The rule lives in two places**: the `escalate` property and the
  `list --escalated` SQL. `test_escalated_only_matches_property` keeps them in
  step, but any rule change must update both.
- **`escalate` builds on the stored `needs_review` snapshot.** If the
  threshold changes later, old entries keep their old `needs_review`, and
  `escalate` is recomputed from that, not from the new threshold. Each entry
  records its `confidence_threshold`, so this can be revisited.
- **`escalate` is not serialised.** A later build that exposes records as JSON
  (e.g. an API) must add it explicitly (see the Technical PRD trade-off).
- **Only two triggers.** Low confidence and `human_review` routing. High
  urgency, for example, does not escalate (deliberate, PRD "Won't").
- **Blanking the API key on Windows.** In PowerShell,
  `$env:ANTHROPIC_API_KEY = ''` removes the variable, so `.env` then supplies
  the real key. All blank-key runs here used Git Bash
  (`ANTHROPIC_API_KEY= …`), where the empty value is kept and `load_dotenv`
  does not overwrite it.
- **Observed confidence drift.** Against build #2's paid run, the same cases
  moved slightly: `other_job_application` 0.92 → 0.85, `vague_short`
  0.35 → 0.30, `complaint` 0.90 → 0.92, `existing_booking` 0.93 → 0.92,
  `billing_refund` 0.95 → 0.93. All labels and the `needs_review` assertion
  still pass; the prompt, model and threshold are unchanged. This is
  run-to-run model variation, recorded as observed.
