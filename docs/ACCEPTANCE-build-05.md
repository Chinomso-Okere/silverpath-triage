# Acceptance check — Build #5: Demo layer (web form + Slack notification)

Checks every acceptance criterion in `docs/PRD-build-05.md` against evidence.
Evidence is a test name (all in `tests/test_web.py`), a commit hash, or output
captured during the acceptance step (2026-11-06). **Code verified at
`7080519`**, the last commit that changed code, tests or dependencies:
`git diff 7080519 HEAD -- src tests pyproject.toml uv.lock` is empty. `1cb8c85`
changed only the README.

**Result: 11 of 11 PASS.**

## Runs captured during the acceptance step

**Free run, Anthropic key blanked** (`ANTHROPIC_API_KEY= uv run pytest -m "not eval" -v`, Git Bash):
```
test_api.py 152, test_config.py 2, test_entry.py 14, test_main.py 52, test_storage.py 24, test_web.py 85
===================== 329 passed, 9 deselected in 14.19s ======================
```
The 244 tests from builds #1–#4 are all among the 329 and none was edited; the 85
in `test_web.py` are new. 0 failed, 0 errors, 0 skipped.

**Live demo** (run by the director; server started with the documented command,
`uv run uvicorn silverpath_triage.api.app:app --host 127.0.0.1 --port 8000`, Slack
webhook configured in `.env`; fictional samples from `data/samples/` pasted into
`http://127.0.0.1:8000/demo`). Screenshots of both result pages and both Slack
messages were reviewed by the director and the review chat and are kept outside
the repo.

Server console:
```
INFO:     Started server process [10552]
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:59214 - "GET /demo HTTP/1.1" 200 OK
INFO:     127.0.0.1:53473 - "POST /triage HTTP/1.1" 200 OK
INFO:     127.0.0.1:61875 - "POST /demo HTTP/1.1" 200 OK
INFO:     127.0.0.1:63321 - "GET /demo HTTP/1.1" 200 OK
INFO:     127.0.0.1:64172 - "POST /triage HTTP/1.1" 200 OK
INFO:     127.0.0.1:60876 - "POST /demo HTTP/1.1" 200 OK
```
Each `POST /demo` is preceded by its own `POST /triage` from `127.0.0.1`: the form
reached triage through the real endpoint over local HTTP. The console holds only
uvicorn's banner and access lines (client, method, path, status).

Run 1, calm (`eval_01_new_enquiry.txt`). Page: Entry 5, `new_enquiry`, `low`,
`sales`, confidence 0.95, needs review no, escalate no, **no banner**, "Slack
notification sent." Slack (#triage-demo, 12:48):
```
*Entry #5* · intent: new_enquiry · urgency: low · route: sales · confidence: 0.95
Summary: Tom Hughes wants a quote for a full bathroom refit in a newly bought Didsbury house, with a site visit, sometime in spring.
```

Run 2, escalated (`eval_07_vulnerable_new_enquiry.txt`). Page: Entry 6,
`new_enquiry`, `high`, `human_review`, confidence 0.85, needs review no, escalate
yes, **red banner**, "Slack notification sent." Slack (12:48):
```
@here :rotating_light: *ESCALATE*: a person must see this
*Entry #6* · intent: new_enquiry · urgency: high · route: human_review · confidence: 0.85
Summary: Daughter asks for an electrician to inspect a sparking kitchen socket at her elderly father's Harrogate home, check wiring, and quote the cost.
```

Then, through the CLI (a separate process reading the real database):
```
$ uv run python -m silverpath_triage.main list
 ID  Created (UTC)     Intent             Route         Conf  Review  Why       Verified  Source
  6  2026-11-06 12:49  new_enquiry        human_review  0.85  no      routed    no        web-form
  5  2026-11-06 12:48  new_enquiry        sales         0.95  no      -         no        web-form
  4  2026-11-06 11:08  new_enquiry        human_review  0.70  no      routed    no        web-form
  3  2026-10-31 22:59  new_enquiry        human_review  0.85  no      routed    no        acceptance-curl
  1  2026-10-31 00:44  new_enquiry        human_review  0.90  no      routed    yes       data/samples/enquiry_01.txt
```
Entries 5 and 6 are the two acceptance runs, both with source `web-form`. Entry 4
(also `web-form`) is a pre-acceptance preview the director ran after step 3; it is
not evidence. Two paid Claude calls were made for acceptance; the 9-case eval
suite was not run.

**Repository checks:**
```
$ git log --format='%h %s%n  trailers:[%(trailers)]' 8187374..HEAD
1cb8c85 Document the demo page, Slack setup and its limits in the README (step 5)
  trailers:[]
7080519 Add secrets, fixed-address and XSS safety tests for the demo layer (step 4)
  trailers:[]
5e3d911 Add /demo web form that triages over the real POST /triage and notifies Slack (step 3)
  trailers:[]
4675bcb Add Slack notification service with escaping, status mapping and log safety (step 2)
  trailers:[]
171f4e6 Add build #5 dependencies, demo config settings and notification model (step 1)
  trailers:[]
3cf0fea Add build #5 handover docs and evolve CLAUDE.md for the demo layer (step 0)
  trailers:[]
$ git log 8187374..HEAD --format=%B | grep -ciE "co-authored-by|claude-session"
0
$ git diff --name-status 8187374 HEAD -- tests
A	tests/test_web.py
$ git diff 7080519 HEAD -- src tests pyproject.toml uv.lock
(empty)
$ git diff --name-status 7080519 HEAD
M	README.md
$ git check-ignore .env data/triage.db
.env
data/triage.db
```
`8187374` is build #4's last commit, the base for the ranges above.

**Secret scan** (a throwaway `uv run python` script outside the repo; it imports
`silverpath_triage.config`, which loads `.env` as the app does, and prints names
and counts only). For each configured value it counts fixed-string matches in
`git grep -F -c -f - HEAD` (value passed on stdin, never on a command line) and in
the output of `git log -p --all`, i.e. the whole repository history (34 commits),
not just build #5, because the repo is public and the API keys predate this
build. No value was printed, echoed, written to disk or put on a command line.
```
TRIAGE_API_URL (positive control): HEAD=15, history (all commits)=15
ANTHROPIC_API_KEY: HEAD=0, history (all commits)=0
API_KEY: HEAD=0, history (all commits)=0
WEBHOOK_URL: HEAD=0, history (all commits)=0
```
The positive control (a known non-secret string) is found, so the 0s are
meaningful. All three secrets were non-blank.

## Criteria

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | `GET /demo` returns a form (textarea `enquiry_text`, `required`, `maxlength="10000"`, submit button); `POST /demo` shows every result field; banner when `escalate` is true, none when false | PASS | `test_get_demo_shows_the_form`; `test_success_shows_every_field` (all 15 rows incl. key details); `test_escalation_banner_follows_the_api_field` (low-confidence → banner, human-review → banner, calm → none). Live: run 1 no banner, run 2 red banner. Commit `5e3d911` |
| 2 | Blank, whitespace-only or 10,001-character enquiry → friendly error; triage never called, nothing stored, no Slack message; the check is the API's `TriageRequest` | PASS | `test_invalid_input_is_stopped_by_the_api` (empty, whitespace, over-limit): the request is forwarded once, so the API is the validator; 422 page with the fixed message and the text refilled; triage stub not called; nothing stored (connection guard); no webhook POST (`assert_error_page`). Commit `5e3d911` |
| 3 | Front door only: the outgoing request carries `X-API-Key` = configured key and `source: "web-form"`; web code imports none of `services.triage`, `services.storage`, `api.auth`, `api.app` | PASS | `test_outgoing_request_goes_to_the_fixed_api_with_key_and_source`; `test_web_code_imports_only_allowed_modules` (AST, allowlist); `test_importing_web_routes_loads_no_forbidden_module` (subprocess, `sys.modules`); `test_success_stores_the_entry_with_source_web_form`. Live: a `POST /triage` 200 before each `POST /demo`; `list` shows source `web-form`. Commit `5e3d911` |
| 4 | Neither the API key nor the webhook URL appears in any rendered page or captured log; no committed file contains a real secret (`.env.example` blank); **seen to fail first** | PASS | `test_secrets_never_reach_pages_or_logs` (14 scenarios, logs captured at DEBUG: GET form; success with Slack sent; the 422, blank-key 503, API 401, triage-error, storage-error, connect-error, read-timeout, invalid-URL, bad-200-body and unlisted-418 error pages; Slack rejected and unreachable); `test_secret_webhook_url_never_appears_in_logs`; `test_env_example_holds_no_values`; secret scan above (0 and 0 at HEAD and in all history); `check-ignore` above. **Seen to fail:** step 2 (`4675bcb`): the httpx `setLevel(logging.WARNING)` line deleted → 1 failed, httpx's INFO `HTTP Request: POST <sentinel URL>` line was captured. Step 4 (`7080519`), run (a): a hidden key field added to the template → failed on `'KEY-SENTINEL-4d2b8e' not in` the page; run (b): the `setLevel` line deleted again → `[success-sent]` and `[webhook-rejected]` failed on the webhook sentinel in httpx's INFO line. All restored, none committed |
| 5 | One Slack POST with JSON `text` per success; `<!here>` and `:rotating_light:` only when `escalate` is true; `<!channel>`/`<@U123>` in a summary arrive escaped | PASS | `test_one_post_with_a_json_text_and_the_configured_timeout`; `test_escalated_message_is_loud`; `test_calm_message_has_no_markers`; `test_format_follows_the_escalate_field_not_a_recomputation`; `test_model_text_is_escaped_so_only_our_here_can_ping` (`&lt;!channel&gt;`, and no `<` at all in the calm text); `test_message_has_no_key_details_or_reasoning`; `test_message_cannot_carry_enquiry_text`; `test_success_sends_exactly_one_webhook_post`; `test_escalated_submission_sends_the_loud_message`. Live: calm and loud Slack messages above. Commits `4675bcb`, `5e3d911` |
| 6 | Webhook blank, unreachable or non-200 → result still shown with a fixed status; no error text or URL shown | PASS | `test_status_mapping_with_exactly_one_attempt` (8 cases: 200 → sent; 400, 403, 404, 500 → rejected; connect error, read timeout, invalid URL → unreachable; one attempt each); `test_blank_url_is_not_configured_and_sends_nothing`; `test_page_shows_the_fixed_notification_status` (sent, rejected, unreachable, not-configured: result still shown, 200); `test_every_notification_status_has_fixed_page_text`; the secrets scenarios cover the failure pages. Commits `4675bcb`, `5e3d911` |
| 7 | Free run with the key blanked (Git Bash) makes zero Claude, Slack or network calls; the 244 build #4 tests still pass; no existing test file edited | PASS | free run above: 329 passed, the 244 among them; `git diff --name-status 8187374 HEAD -- tests` is only `A tests/test_web.py`; no `conftest.py`. Guards in `test_web.py`: `no_client` (Anthropic constructor fails the test), `connections` real-database guard proved active by `test_real_db_guard_is_active`, temp `DB_PATH`. The triage client runs the app in memory (`httpx.ASGITransport`) and the webhook client is `httpx.MockTransport`, so no socket is opened |
| 8 | Live demo: documented command; one calm and one escalated fictional enquiry through the browser; result pages, both Slack messages (loud one visibly different) and CLI output with `source = web-form` captured; two paid calls | PASS | live demo and `list` above; screenshots reviewed by the director and the review chat (kept outside the repo); entries 5 and 6 with source `web-form`. Two paid calls |
| 9 | No build #5 commit carries a `Co-Authored-By`, `Claude-Session` or other AI attribution trailer | PASS | trailer listing above: `%(trailers)` empty for all six commits before this document; 0 matching lines in their messages. The commit that adds this document is checked when it is made and reported in the step report |
| 10 | Triage API address comes from `config.py`, never from the request or its Host header; a forged Host header still goes to `127.0.0.1:8000` | PASS | `test_forged_host_header_cannot_redirect_the_api_call`; `test_triage_api_url_is_fixed_localhost_8000`; `test_outgoing_request_goes_to_the_fixed_api_with_key_and_source`. **Seen to fail (step 4, `7080519`, run (c)):** URL built from `request.base_url` → the call went to `http://evil.example/triage`, 1 failed. Restored, never committed |
| 11 | Enquiry or model output containing `<script>` or other HTML is shown as text, in the result and in the refilled textarea; **seen to fail first** | PASS | `test_model_output_is_shown_escaped`; `test_refilled_input_is_shown_escaped`; `test_template_has_no_escape_bypass` (no `\|safe`, `Markup`, `autoescape` or `<script`). **Seen to fail (step 4, `7080519`, run (d)):** `\|safe` added to the summary and the textarea → 3 failed: both escaping tests on the raw `<script>alert`, and the template check on `\|safe`. Restored, never committed |

## Known limitations / carried forward

**Deliberate decision in this build (recorded):**
- **`httpx.InvalidURL` is caught alongside `httpx.HTTPError`** in `services/notify.py`
  and `web/routes.py`. It is not an `HTTPError` subclass, so a malformed webhook
  URL or API address would otherwise be an unhandled 500 instead of the fixed
  "unreachable" status or page. A small extension of the Technical PRD, agreed in
  step 2.

**From the Technical PRD:**
- **Direct `POST /triage` calls don't notify.** Only the form posts to Slack.
- **The form is unauthenticated and has no CSRF protection.** It holds the key, so
  anyone who can reach it spends API credits, and another page open in the same
  browser could submit it. Binding to `127.0.0.1` is the only guard; run the server
  only while demoing.
- **A timeout can show "could not reach" for a stored entry.** If triage takes
  longer than the 60-second client timeout, the page shows the fixed message even
  though the API may have saved the entry. Check with `list`.
- **One Slack attempt, no retries.** Slack's limit of about one message per second
  per webhook applies.
- **`TRIAGE_API_URL` must match the run port** (8000). Another port breaks the form.

**Surfaced in this build:**
- **The model-written summary carries personal details to Slack. Observed in the
  live run:** a name in entry 5, and the town and an elderly occupant in entry 6.
  The message never includes the enquiry text or the contact fields, but the
  summary is free text. A real deployment must decide whether summaries go to
  Slack at all.
- **`notify.py` sets the `httpx` logger to WARNING process-wide.** That keeps the
  webhook URL out of logs, but it also hides httpx's INFO line for the triage
  loopback request.
- **`httpcore` DEBUG logs the host only**, not the path or token; the uvicorn
  console shows method, path and status. Neither logs bodies or headers.
- **A browser's `GET /favicon.ico` gets a 404.** Harmless.
- **Entry 4**, the pre-acceptance preview (source `web-form`), is left in the real
  database.
- **Observed, out of build #5 scope:** entry 5's "Location or postcode" was
  "Didsbury" although the enquiry contains `M20 6RT`. This is build #1
  extraction, unchanged here; a candidate eval check for a later build.

**Still open from builds #2–#4** (see `docs/ACCEPTANCE-build-04.md`):
- No raw request-body size limit; the 10,000-character cap is checked after the
  body is read.
- One shared key, no rotation or lockout; a non-ASCII configured key can never
  match over HTTP.
- The CLI does not catch `anthropic.APIError`.
- Secure delete covers the database file only, not SQLite's rollback journal.
- `£` shows as `�` in some Windows shells (display only).
- `escalate` builds on the stored `needs_review` snapshot.
- Not done: network exposure, TLS, rate limiting, and the GDPR work (lawful basis,
  retention policy, privacy notice, encryption at rest). Local-only remains the
  privacy guard.
