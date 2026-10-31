# Acceptance check — Build #4: API layer

Checks every acceptance criterion in `docs/PRD-build-04.md` against evidence.
Evidence is a test name, a commit hash, or output captured during the
acceptance step (2026-10-31). **Code verified at `c65bb5b`**, the last commit
that changed code, tests or dependencies: `git diff c65bb5b HEAD -- src tests
pyproject.toml uv.lock` is empty. `34cbea6` changed only the README.

**Result: 23 of 23 PASS.**

## Runs captured during the acceptance step

**Free run, Anthropic key blanked** (`ANTHROPIC_API_KEY= uv run pytest -m "not eval" -v`, Git Bash):
```
test_api.py 152, test_config.py 2, test_entry.py 14, test_main.py 52, test_storage.py 24
====================== 244 passed, 9 deselected in 11.14s =====================
```
The 92 tests from builds #1–#3 are all among the 244 and none was edited; the 152
in `test_api.py` are new. 0 failed, 0 errors, 0 skipped.

**Server started with the documented command** (console captured to a log file):
```
$ uv run uvicorn silverpath_triage.api.app:app --host 127.0.0.1 --port 8000
INFO:     Started server process [8036]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

**Local-only proof, taken while the server was idle:**
```
$ netstat -ano | findstr :8000
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       8036
  TCP    127.0.0.1:60086        127.0.0.1:8000         TIME_WAIT       0

listeners on :8000 whose Local Address is not 127.0.0.1:   (none)
$ tasklist /FI "PID eq 8036"   → python.exe   8036   (the uvicorn process above)
```
The one `LISTENING` row is bound to `127.0.0.1:8000`. There is no `0.0.0.0:8000`
and no `[::]:8000`. (`0.0.0.0:0` in the *Foreign Address* column of a listening
row means "any peer" and is not the binding.) After the run the server was
stopped; `:8000` had no listener.

**Free live checks, no model call** (keys not shown; the real key was passed through
the shell, never on a command line):
```
wrong key, valid body                  → {"detail":"Invalid or missing API key."}  HTTP 401
missing key, valid body                → {"detail":"Invalid or missing API key."}  HTTP 401
wrong key + malformed JSON "{not json" → {"detail":"Invalid or missing API key."}  HTTP 401
wrong key + 20,000-character body      → {"detail":"Invalid or missing API key."}  HTTP 401
GET /openapi.json, no key              → HTTP 200
GET /docs, no key                      → HTTP 200
good key + blank text                  → {"detail":[{"loc":["body","enquiry_text"],"msg":"Value error, enquiry_text must not be empty"}]}  HTTP 422
```
Real database unchanged by these (`list` still showed only Entry 1).

**The one paid call**, made once (`data/samples/enquiry_01.txt`, fictional, sent with
`source` = `acceptance-curl` and the correct key): `HTTP 200` in 4.0 s.
```json
{
  "entry_id": 3,
  "intent": "new_enquiry",
  "urgency": "high",
  "summary": "Priya Shah needs an urgent boiler repair visit this Thursday or Friday and a rough callout price; she has no heating or hot water with a 6-month-old baby at home.",
  "key_details": {
    "customer_name": "Priya Shah",
    "requested_service": "Boiler repair callout (Worcester boiler not heating water)",
    "deadline_or_date": "this Thursday or Friday",
    "location_or_postcode": "LS6 2AB, Leeds",
    "contact_info": {"phone": "07700 900123", "email": "priya.shah@example.com"}
  },
  "suggested_route": "human_review",
  "confidence": 0.85,
  "reasoning": "A first-time boiler enquiry, but no heating or hot water with a baby at home is a vulnerability concern that a person should review before sales follow-up.",
  "needs_review": false,
  "escalate": true
}
```
Then, through the CLI (a separate process reading the real database):
```
$ show 3     (triage result section; the original-enquiry section matches enquiry_01.txt)
=== Entry 3 ===
Source:         acceptance-curl
Model:          claude-haiku-5-5
Threshold:      0.60
Route:          human_review
Confidence:     0.85 (threshold 0.60)
Needs review:   no
Escalate:       YES (routed to human_review)
$ list
 ID  Created (UTC)     Intent             Route         Conf  Review  Why       Verified  Source
  3  2026-10-31 22:59  new_enquiry        human_review  0.85  no      routed    no        acceptance-curl
  1  2026-10-31 00:44  new_enquiry        human_review  0.90  no      routed    yes       data/samples/enquiry_01.txt
$ list --escalated   → the same two entries
```
The id is 3, not 2: ids are never reused (`AUTOINCREMENT`), and Entry 1 was the
only entry listed before the call. Entry 3 was left in the real database.

**Server console after the run, in full, and the log check** (counts only):
```
INFO:     Started server process [8036]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:60086 - "GET /openapi.json HTTP/1.1" 200 OK
INFO:     127.0.0.1:57902 - "POST /triage HTTP/1.1" 401 Unauthorized      (×4)
INFO:     127.0.0.1:57906 - "GET /openapi.json HTTP/1.1" 200 OK
INFO:     127.0.0.1:57907 - "GET /docs HTTP/1.1" 200 OK
INFO:     127.0.0.1:57908 - "POST /triage HTTP/1.1" 422 Unprocessable Entity
INFO:     127.0.0.1:57912 - "POST /triage HTTP/1.1" 200 OK

SILVERPATH_API_KEY (value non-empty) occurrences in log: 0
ANTHROPIC_API_KEY  (value non-empty) occurrences in log: 0
log lines matching any of the 11 non-blank lines of the sample enquiry: 0
"Priya", "Shah", "boiler", "LS6", "07700", "example.com", "acceptance-curl",
"wrong-key", "enquiry_text", "X-API-Key", "Traceback": 0 each
```
The console holds only uvicorn's banner and access lines (client, method, path,
status). No request body, header, enquiry text or key appears.

**Repository checks:**
```
$ git log 85b38ec..HEAD --format="%h %s | trailers=[%(trailers)]"
34cbea6 Document the API in the README; relabel build #3 docs (step 4) | trailers=[]
c65bb5b Authenticate POST /triage before body parsing; criterion 23 tests (step 3, part 2) | trailers=[]
04e3952 Add POST /triage app, error handlers and route tests (step 3, part 1) | trailers=[]
459dccc Add X-API-Key auth dependency with tests (step 2) | trailers=[]
1dd1734 Add API deps, config values and request/response models (step 1) | trailers=[]
79801a3 Add build #4 handover docs and evolve CLAUDE.md for the API layer (step 0) | trailers=[]
$ git log 85b38ec..HEAD --format=%B | grep -ciE "co-authored-by|claude-session"
0
$ git diff --name-status 85b38ec HEAD -- tests
A	tests/test_api.py
$ git diff --stat 85b38ec HEAD -- src/silverpath_triage/services src/silverpath_triage/prompts \
      src/silverpath_triage/models/triage.py src/silverpath_triage/models/entry.py
(empty)
$ git diff --name-status 85b38ec HEAD -- src pyproject.toml .env.example
M	.env.example
M	pyproject.toml
A	src/silverpath_triage/api/__init__.py
A	src/silverpath_triage/api/app.py
A	src/silverpath_triage/api/auth.py
M	src/silverpath_triage/config.py
A	src/silverpath_triage/models/api.py
$ git diff 85b38ec HEAD -- src/silverpath_triage/config.py   (added lines only)
+API_KEY = os.environ.get("SILVERPATH_API_KEY", "").strip()
+MAX_ENQUIRY_CHARS = 10_000
$ git show 1dd1734:.env.example
ANTHROPIC_API_KEY=
SILVERPATH_API_KEY=
$ grep -c "0.0.0.0" README.md        → 0
```
Locked versions (`uv.lock`): `fastapi 0.162.0`, `uvicorn 0.54.0` (plain, no extras),
`httpx 0.28.1` (dev), `starlette 1.10.0` (pulled in by fastapi). `85b38ec` is
build #3's last commit, the base for the ranges above.
`SILVERPATH_API_KEY` did not exist in `.env` before this step; a generated value was
added to the gitignored `.env` for the run (never printed or recorded here).

## Criteria

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | With a non-blank key set, a correct `X-API-Key` and a valid body give 200 (free, stubbed) | PASS | `test_correct_key_is_accepted`; `test_valid_request_returns_the_full_response`; live 200 above. Commits `459dccc`, `04e3952` |
| 2 | Missing or wrong key → 401 before any work (no client, no DB write); free test; **seen to fail first** against an allow-all dependency | PASS | `test_missing_or_wrong_key_is_rejected_with_401` (6 cases: missing, empty, wrong, extra char, short, wrong case); `test_route_rejects_missing_or_wrong_key_with_401` (triage stub not called, no connection opened, no database file); `no_client` guard. **Seen to fail (step 2):** allow-all `require_api_key` gave `18 failed, 21 passed`, e.g. `assert 200 == 401`, `Failed: DID NOT RAISE HTTPException`; restored with `git restore`, never committed. Live 401s above. Commit `459dccc` |
| 3 | Fail-closed: blank or unset key → 503 for every request, even with a plausible key; no model call, no DB write | PASS | `test_blank_configured_key_rejects_everything_with_503` (none, empty, wrong, plausible); `test_blank_key_and_no_header_is_503_not_a_match`; `test_dependency_raises_503_when_not_configured`; `test_route_is_503_when_no_key_is_configured` (no stub call, no connection); `test_unconfigured_key_is_503_whatever_the_body`. **Seen to fail (step 2):** fail-closed branch removed gave `9 failed, 30 passed` (`assert 200 == 503` for a header-less request: the `"" == ""` hole). Commits `459dccc`, `04e3952`, `c65bb5b` |
| 4 | Check uses `secrets.compare_digest`; neither key in any response body, header or captured log line | PASS | `api/auth.py` calls `secrets.compare_digest` on UTF-8 bytes; `test_key_is_compared_with_compare_digest_on_utf8_bytes` (spy: two `bytes` args; not called when unconfigured); `test_keys_never_appear_in_responses_or_logs` (3), `test_neither_key_appears_in_route_responses` (3), `test_validation_errors_do_not_echo_the_key`, `test_no_enquiry_text_key_or_path_is_ever_logged`; live log check: 0 occurrences of either key. Commits `459dccc`, `04e3952` |
| 5 | `.env.example` gains blank `SILVERPATH_API_KEY=`, keeps `ANTHROPIC_API_KEY=` | PASS | `git show 1dd1734:.env.example` above |
| 6 | Missing `enquiry_text` → 422, no model call, no DB write | PASS | `test_missing_enquiry_text_is_rejected`; `test_invalid_body_is_422_with_no_work_and_no_echo[missing-field]` (stub not called, no connection, no database file). Commits `1dd1734`, `04e3952` |
| 7 | Empty or whitespace-only `enquiry_text` → 422, no model call, no DB write | PASS | `test_blank_enquiry_text_is_rejected` (empty, space, whitespace); `test_invalid_body_is_422_with_no_work_and_no_echo[empty]` and `[blank]`; live 422 above |
| 8 | `enquiry_text` over 10,000 characters → 422, no model call, no DB write | PASS | `test_length_cap_boundary` (10,000 accepted, 10,001 rejected); `test_invalid_body_is_422_with_no_work_and_no_echo[over-limit]` (12,600 chars) and `[way-over-limit]` (20,000) |
| 9 | `source` optional: omitted → `"api"` stored; supplied → stored | PASS | `test_source_defaults_to_api`; `test_source_supplied_is_kept`; `test_entry_id_refers_to_a_saved_row` (stored `source == "api"`); `test_source_supplied_is_stored` (`"web-form"` read back via `get_entry`); live: stored as `acceptance-curl` |
| 10 | Valid authenticated request → 200 with the full result, `needs_review`, `escalate` and `entry_id` | PASS | `test_valid_request_returns_the_full_response` (keys equal `TriageResponse.model_fields`; body equals the expected mapping); live 200 above |
| 11 | Response `escalate` equals the code-computed `record.escalate`: true for a `human_review` stub, false for a confident `sales` stub | PASS | `test_response_escalate_matches_the_record` (`human_review` 0.9 → true; `sales` 0.87 → false; `sales` 0.3 → true); `test_response_escalate_equals_record_escalate` (4); `test_escalate_is_in_the_response_but_not_the_record`; live `escalate: true` for a `human_review` route |
| 12 | `entry_id` refers to a saved row; fetching it returns the same triage data | PASS | `test_entry_id_refers_to_a_saved_row` (`get_entry(entry_id)` record equals `build_record(stub result)`; text stored unchanged; model and threshold from config); live `show 3` above |
| 13 | An API entry routed to `human_review` appears in `list_entries(escalated_only=True)` and CLI `list --escalated` | PASS | `test_escalated_entry_appears_in_the_escalated_list` (storage filter and `main.main(["list","--escalated"])`; the confident entry is absent); live `list --escalated` above |
| 14 | `TriageError` → 502 with a clear message, no traceback, no DB write | PASS | `test_triage_error_is_502` (fixed generic detail, no connection, nothing in body or log from the error text or enquiry). Also `test_anthropic_api_error_is_502` (2). Handlers seen to matter: see criterion 15 note. Commit `04e3952` |
| 15 | `StorageError` → 500 with a clear message, no traceback | PASS | `test_storage_error_is_500` (stubbed `save_entry`); `test_real_storage_error_does_not_leak_the_path` (a real `StorageError`, from a database path that is a directory: body and log hold neither the path nor the SQLite text). **Seen to fail (step 3):** `StorageError` handler removed → the exception propagates (3 failed); `str(exc)` returned in the 500 → 2 failed; validation handler removed → 8 failed. All restored, none committed. Commit `04e3952` |
| 16 | Run command binds `127.0.0.1`; at acceptance `netstat` shows it listening on `127.0.0.1` only | PASS | netstat output above: one `LISTENING` row, `127.0.0.1:8000`, PID 8036 = the uvicorn process; no `0.0.0.0:8000` or `[::]:8000`. README documents the exact command; `0.0.0.0` appears 0 times in the README. Commit `34cbea6` |
| 17 | `/docs` and `/openapi.json` enabled; free test confirms `/openapi.json` is served and holds neither the key nor any stored enquiry text | PASS | `test_openapi_and_docs_are_open_and_hold_no_key_or_enquiry` (served without a key; an entry with a sentinel text was stored first; neither it nor the key is in the schema; `/docs` 200); live 200s above. Commit `04e3952` |
| 18 | Enquiry text is never logged; free test asserts no captured log record contains it | PASS | `test_no_enquiry_text_key_or_path_is_ever_logged` (success, 401, 422, 502, 500 under `caplog` at DEBUG: no enquiry text, key, database path or error text); handlers log a fixed note and the exception type only; live console above |
| 19 | `uv run pytest -m "not eval"` passes with zero API calls and zero real-database access; no existing test edited | PASS | free run above: 244 passed with the key blanked; `no_client` guard (autouse) in `test_api.py` and `test_main.py`; real-database guard `connections` with `REAL_DB` captured at import, proved active by `test_real_db_guard_is_active`; `git diff --name-status 85b38ec HEAD -- tests` is only `A tests/test_api.py` |
| 20 | One paid end-to-end proof at acceptance: correct key → 200 with `escalate` and `entry_id`, visible via CLI `show`; missing or wrong key → 401; no log line holds the enquiry or either key | PASS | paid call, `show 3`, `list`, the four 401s and the log check above. One paid request was made; the 9-case eval suite was not run |
| 21 | No commit from this build carries a Claude attribution trailer | PASS | trailer listing above: `%(trailers)` empty for all six commits before this document; 0 `co-authored-by` or `claude-session` lines in their messages. The commit that adds this document is checked when it is made and reported in the step report |
| 22 | README documents the API (run command, request and response shape, `X-API-Key`, local-only note) and the build #3 docs are relabelled | PASS | README "API" section and "What the API is not"; docs list marks build #4 current and build #3 as background; example JSON and links checked in step 4. Commit `34cbea6` |
| 23 | Auth is checked before body validation: bad key plus an invalid body → 401, never 422 | PASS | `test_bad_key_is_401_whatever_the_body` (11 bodies × wrong and missing key = 22), `test_unconfigured_key_is_503_whatever_the_body` (33), `test_control_the_same_bodies_are_rejected_for_a_good_key` (11: the same bodies get 422, or 400 for invalid UTF-8, with a good key), `test_middleware_rejects_a_bad_key_before_the_body_or_route_is_reached`, `test_dependency_and_middleware_give_the_same_decision` (10). **Seen to fail (step 3):** dependency only → `assert 422 == 401`, `assert 400 == 401`, `assert 307 == 401`; middleware removed `11 failed, 141 passed`; auth removed entirely `73 failed, 79 passed` (invalid bodies gave 422/400, a valid body with a bad key gave 200). Live: bad key + malformed JSON and bad key + 20,000 characters → 401. Commit `c65bb5b` |

## Known limitations / carried forward

**Deliberate decisions in this build (recorded):**
- **Auth middleware on `POST /triage`.** FastAPI parses the JSON syntax of a body
  before it resolves dependencies, so with the dependency alone a bad key plus
  malformed JSON got 422 and invalid UTF-8 got 400. The middleware
  (`authenticate_triage_post`) calls the same `require_api_key` first and returns
  its 401 or 503. It guards `POST /triage` only (trailing slash included);
  `/docs` and `/openapi.json` stay open. The Technical PRD did not include it.
- **Fixed generic 502 and 500 messages.** The Technical PRD said
  `{"detail": "<message>"}`. That form would return the local database path and
  SQLite text on a 500, and, for one `TriageError`, pydantic's rendering of the
  model's raw output. The responses say `The triage service could not produce a
  valid result.` and `The entry could not be saved.`; logs carry only the exception
  type.
- **`anthropic.APIError` → 502.** A small extension completing the PRD's "model
  failure → 502" rule: a model that cannot be reached would otherwise be an
  unhandled 500 with a server-side traceback.
- **`/docs` and `/openapi.json` left enabled** (localhost only; they show shapes,
  not keys or data). Revisit when the endpoint is exposed.

**Surfaced in this build:**
- **The auth rule lives in two places**: the route's `Depends(require_api_key)` and
  the middleware. Both call the one function, and
  `test_dependency_and_middleware_give_the_same_decision` keeps them in step.
- **A characterisation test documents FastAPI's ordering**
  (`test_dependency_alone_answers_a_malformed_body_before_auth`). If a future
  FastAPI changes that order, the test fails and the middleware may be removable.
- **A non-ASCII configured key can never match over HTTP.** Starlette decodes
  header bytes as latin-1 while the configured key is encoded as UTF-8. Use an
  ASCII key (the README says so).
- **No raw request-body size limit.** The 10,000-character cap is enforced after
  the body is read, so an oversized body is rejected with 422 but still read into
  memory.
- **The CLI has the same unhandled `APIError` gap.** `main` catches `TriageError`,
  `StorageError`, `ValueError` and `OSError`, not `anthropic.APIError`. Not touched.
- **One shared key.** No per-caller keys, rotation or lockout.
- **Uvicorn's console shows client port, method, path and status** for every
  request (no bodies or headers). Acceptable for local use.
- **The live proof added Entry 3 to the real database** (a fictional sample, source
  `acceptance-curl`), left in place. Entry 2 is absent; ids are not reused.

**Deferred to build #5 (exposure and data protection):** network exposure, TLS,
rate limiting, per-caller keys, revisiting open `/docs`, and the GDPR work (lawful
basis, retention policy, privacy notice, encryption at rest). The endpoint is
local-only; that is the privacy guard for this build.

**Resolved from build #3:** "`escalate` is not serialised; a later build exposing
records as JSON must add it explicitly." `TriageResponse` sets it by hand from
`record.escalate`, and the tests cover true and false.

**Still open from builds #2 and #3:**
- **Secure delete covers the database file only.** SQLite's temporary
  rollback-journal file is removed by the operating system, not overwritten.
  Revisit before handling real enquiries, together with retention and encryption
  at rest.
- **`£` shows as `�` in some Windows shells.** Display only; data is stored as UTF-8.
- **Not built:** duplicate-enquiry detection; `export <id>` to turn a verified
  entry into an eval case.
- **`escalate` builds on the stored `needs_review` snapshot.** If the threshold
  changes later, old entries keep their old `needs_review`.
- **Only two escalation triggers** (low confidence and `human_review` routing).
- **Blanking the API key on Windows.** In PowerShell, `$env:ANTHROPIC_API_KEY = ''`
  removes the variable, so `.env` then supplies the real key. The blank-key run
  here used Git Bash (`ANTHROPIC_API_KEY= …`).
