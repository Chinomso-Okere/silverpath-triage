# Acceptance check — Build #2: Storage

Checks every acceptance criterion in `docs/PRD-build-02.md` against evidence.
Evidence is a test name, a commit hash, or output captured during the
acceptance step (2026-10-31). **Code verified at `2b3865b`** (last code
commit), plus `test_non_ascii_text_round_trips`, added in the acceptance commit.

**Result: 12 of 12 PASS.**

## Runs captured during the acceptance step

**Free run, API key blanked** (`export ANTHROPIC_API_KEY= && uv run pytest -m "not eval" -v`):
```
test_config.py 2, test_entry.py 8, test_main.py 36, test_storage.py 19
====================== 65 passed, 9 deselected in 6.40s =======================
```

**Paid eval run, made once** (`uv run pytest -m eval -s -v`, 9 API calls):
```
new_enquiry            intent=new_enquiry       route=sales         confidence=0.95 needs_review=False PASSED
existing_booking       intent=existing_customer route=support       confidence=0.93 needs_review=False PASSED
complaint              intent=complaint         route=support       confidence=0.90 needs_review=False PASSED
billing_refund         intent=billing           route=billing       confidence=0.95 needs_review=False PASSED
spam_seo               intent=spam              route=ignore        confidence=0.97 needs_review=False PASSED
other_job_application  intent=other             route=human_review  confidence=0.92 needs_review=False PASSED
vulnerable_new_enquiry intent=new_enquiry       route=human_review  confidence=0.85 needs_review=False PASSED
vague_short            intent=other             route=human_review  confidence=0.35 needs_review=True  PASSED
mixed_complaint_bill   intent=complaint         route=support       confidence=0.85 needs_review=False PASSED
====================== 9 passed, 64 deselected in 24.50s ======================
```

**`list` immediately before and after the paid run** (identical, so the evals wrote nothing):
```
 ID  Created (UTC)     Intent             Route         Conf  Review  Verified  Source
  1  2026-10-31 00:44  new_enquiry        human_review  0.90  no      yes       data/samples/enquiry_01.txt
```

**Commands with the API key blanked:**
```
$ list --needs-review                       → No entries need review.   exit=0
$ show 2                                    → No entry with id 2        exit=1
$ show 99                                   → No entry with id 99       exit=1
$ verify 99 --intent spam --route ignore    → No entry with id 99       exit=1
$ delete 99 --yes                           → No entry with id 99       exit=1
$ show 1  (verdict section)
=== Human verdict ===
Correct intent: new_enquiry
Correct route:  human_review
Reviewed:       2026-10-31 00:56:52 UTC
```

**Repository checks:**
```
$ ls data/outputs
20261030-203606_enquiry_01.json             (build #1's file only)
$ git check-ignore -v data/triage.db
.gitignore:4:data/*.db	data/triage.db
$ git log --all --oneline -- 'data/*.db' | wc -l
0
$ git log e8083ca^..HEAD --format="%h %s | trailers=[%(trailers)]"
2b3865b Add verify and delete commands (step 5) | trailers=[]
7d5a315 Wire triage, list and show commands to storage (step 4) | trailers=[]
c4060f2 Add SQLite storage module and tests (step 3) | trailers=[]
bee9a59 Add push-after-each-step rule to CLAUDE.md | trailers=[]
12776f0 Add TriageEntry and HumanVerdict models with tests (step 2) | trailers=[]
76d5f05 Move API key check to client creation and split paid evals (step 1) | trailers=[]
e8083ca Add build #2 (storage) docs and gitignore the database | trailers=[]
$ git log e8083ca^..HEAD --format=%B | grep -ciE "co-authored-by|claude-session"
0
$ git diff --stat e8083ca -- tests/test_triage_evals.py
 tests/test_triage_evals.py | 4 +++-      (eval marker + docstring run line only)
```

## Criteria

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | `triage <file>` prints the result exactly as before, saves an entry, and prints its id. No JSON file is written | PASS | `test_triage_prints_result_then_saves` (stdout is exactly `format_record(...)` + `Saved as entry 1`; saved entry checked field by field); `test_triage_writes_no_json` (no `*.json` under `data/` changes); `ls data/outputs` above holds only build #1's file. Commit `7d5a315` |
| 2 | `show <id>` returns that entry, and its record is identical to what was saved | PASS | `test_round_trip` (saved entry == retrieved entry, incl. datetimes and confidence); `test_non_ascii_text_round_trips`; `test_sql_like_text_round_trips`; `test_show_entry` |
| 3 | Entries survive closing and reopening the program | PASS | `test_persists_across_separate_connections`; `list` above, run in a new process, still returns entry 1 (created 00:44 UTC) with its verdict |
| 4 | `list` shows newest first; `--needs-review` shows only flagged entries | PASS | `test_list_newest_first_by_id` (orders by id even when `created_at` is out of order); `test_list_needs_review_only`; `test_list_newest_first_and_columns`; `test_list_needs_review_and_limit`; `list --needs-review` above |
| 5 | `verify <id> --intent X --route Y` stores a verdict and `show <id>` displays it. A new entry's verdict is empty | PASS | `test_verify_stores_and_show_displays`; `test_reverify_overwrites_and_says_so`; `test_set_verdict`; `test_new_entry_has_empty_verdict`; `test_new_entry_verdict_is_empty`; `show 1` verdict section above. Commit `2b3865b` |
| 6 | `delete <id>` asks for confirmation (or takes `--yes`), removes the entry, and `show <id>` then reports not found | PASS | `test_delete_shows_entry_and_prompts`; `test_delete_declined_keeps` (`n`, empty, `no`, `maybe`); `test_delete_eof_keeps`; `test_delete_confirmed` (then `show` gives not found); `test_delete_yes_flag_skips_prompt`; `test_secure_delete_overwrites_deleted_content`; `show 2` above. Commit `2b3865b` |
| 7 | An unknown id gives a clear "not found" message for `show`, `verify` and `delete`, never a crash | PASS | `test_show_unknown_id`; `test_verify_unknown_id`; `test_delete_unknown_id_no_prompt`; `test_unknown_ids`; `show 99`, `verify 99` and `delete 99` above |
| 8 | `list`, `show`, `verify` and `delete` work with no API key and make no API calls | PASS | `test_commands_never_create_client` (the client constructor fails the test if called); the blank-key commands above |
| 9 | Both config proofs pass as tests | PASS | `test_import_config_without_key_does_not_raise`; `test_triage_without_key_fails_before_client_is_created`. Commit `76d5f05` |
| 10 | `pytest -m "not eval"` passes with zero API calls; `pytest -m eval` runs the 9 evals, which pass with labels unchanged | PASS | free run above: 65 passed with the key blanked, so any API call would have failed; paid run above: 9 passed; the eval file's diff since `e8083ca` is the marker and docstring lines only (cases and labels untouched) |
| 11 | After real use, `git status` never shows the database file | PASS | `check-ignore` above names `.gitignore:4`; no commit has ever touched `data/*.db`; the real database holds entry 1 and `git status` for the acceptance commit lists no `.db` file |
| 12 | No commit from this build carries a Claude attribution trailer | PASS | trailer listing above: empty for every build #2 commit; 0 `co-authored-by` or `claude-session` lines in any message |

## Known limitations / carried forward

- **Route `human_review` but `needs_review = no`.** Entry 1 (a vulnerable
  household) was routed to `human_review` at confidence 0.90, so the
  `needs_review` flag stayed off. The same pattern shows in the paid run
  (`other_job_application` at 0.92, `vulnerable_new_enquiry` at 0.85). This is
  by design: `needs_review` is computed only from confidence. Not changed in
  this build. *Likely fix in a later build:* `needs_review = confidence <
  threshold OR route == human_review`, re-checked against the eval set (eval
  08 asserts `needs_review`).
- **Secure delete covers the database file only.** `PRAGMA secure_delete = ON`
  overwrites deleted content inside `data/triage.db` (proven by
  `test_secure_delete_overwrites_deleted_content`, which was also shown to
  fail without the PRAGMA). SQLite's temporary rollback-journal file is
  removed by the operating system when a write finishes, not overwritten, so
  old page contents may remain in free disk space. Revisit before handling
  real enquiries, together with retention and encryption at rest.
- **`£` shows as `�` in some Windows shells.** This is display only. When
  Python's output is piped on Windows it uses the `cp1252` encoding, so the
  terminal shows a placeholder. Data is stored as UTF-8: the sample file holds
  bytes `C2 A3`, and `test_non_ascii_text_round_trips` proves `£`, `é` and
  curly quotes round-trip unchanged. Possible later fix: force UTF-8 output
  (`PYTHONIOENCODING=utf-8` or `sys.stdout.reconfigure(encoding="utf-8")`).
- **Not built:** flagging a duplicate enquiry (PRD "Nice"); `export <id>` to
  turn a verified entry into an eval case (PRD "Later").
