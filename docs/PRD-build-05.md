# PRD — Silverpath Inbound-Enquiry Triage, Build #5: Demo layer (web form + Slack notification)

## Context
Builds #1–#4 are done and verified on this repo: the AI layer (one Claude call →
`TriageResult`), SQLite storage, the computed `escalate` flag, and a local,
key-protected `POST /triage` API (see `docs/ACCEPTANCE-build-04.md`). Build #5
adds a **demo layer on top of that API** so the whole chain can be shown live in
a browser. It changes nothing in triage, storage, auth, the prompt, the model or
the `/triage` route.

## Problem
Today the only way to see the system work is a terminal: the CLI, or `curl` with
an API key. That is fine for building and useless for showing a non-technical
audience. A portfolio demo needs three visible things: type an enquiry into a
page, see the triage result on that page, and see something real happen with it.

## Decisions (recorded, agreed with the director)
1. **Form:** one server-rendered HTML page (Jinja2 template) served by the
   existing FastAPI app at `/demo`. No React, no JavaScript framework, no
   client-side script. The browser never holds the API key or the webhook URL.
2. **Handler → real API over local HTTP ("loopback"):** the form handler posts
   the enquiry to the real `POST /triage` at a fixed address from `config.py`
   (`http://127.0.0.1:8000`), adding the `X-API-Key` header server-side. Reason:
   the web code then never imports triage, storage or auth. It can only reach
   them through the authenticated front door, so builds #1–#4 are protected by
   structure, not by promise. Fallbacks if loopback proves unworkable are named
   in the Technical PRD and need director approval.
3. **Notification:** a **Slack** incoming webhook (one only; no Discord, no
   email). One message per successful triage, sent **from the form only**. Loud
   when `escalate` is true.
4. **Dependencies (approved):** `httpx` moves from dev to runtime; `jinja2` and
   `python-multipart` are added. Versions are confirmed at build time.
5. **`source="web-form"`** (hyphen) on every form submission, matching the
   existing tests.

## Type
**Local portfolio demo; closest to a PoC.** No production value by design. Runs
on `127.0.0.1` only. Not a deployment, not a GDPR/legal build. Demo data is the
director's own details or fictional ones only.

## The one workflow
**Input:** enquiry text typed into the form at `http://127.0.0.1:8000/demo`.

1. Browser submits the form (`POST /demo`, field `enquiry_text`).
2. The handler sends `{"enquiry_text": <text>, "source": "web-form"}` to
   `POST http://127.0.0.1:8000/triage` with `X-API-Key` from `config.API_KEY`.
3. The API runs its existing chain (validate → triage → save) unchanged.
4. The handler reads the JSON response as the existing `TriageResponse` model.
5. On success, it posts one Slack message, then renders the result page.

**Output:**
- (a) the result page: every `TriageResponse` field, an escalation banner when
  `escalate` is true, and a notification status line;
- (b) one Slack message (loud when `escalate` is true);
- (c) a stored entry with `source = web-form` (written by the existing API, not
  by the web code).

Structured data stays structured: the triage result is the existing
`TriageResponse`; the notification outcome is a new `NotificationResult`
Pydantic model.

## Scope (MoSCoW)

**Must**
- `GET /demo`: the form. `POST /demo`: the result (or error) on the same page.
- Loopback call with the key added server-side, a fixed API address from
  `config.py`, an explicit ~60s timeout.
- Friendly, fixed error messages for every failure (invalid input, server not
  configured, triage failed, save failed, API unreachable, unexpected response).
- `escalate` shown prominently, taken from the API's field, never recomputed.
- Slack notification on successful triage only, with the loud format when
  `escalate` is true and model-written text escaped so it can't ping anyone.
- Notification fails soft: the result is still shown, with a fixed status.
- No secret in any page, log or committed file. User input shown escaped (XSS).
- Free tests; every existing test unchanged and passing.
- README demo section; CLAUDE.md evolved; `docs/ACCEPTANCE-build-05.md` at close.

**Should**
- After an error, the textarea is refilled with what was typed (escaped), so it
  can be corrected.
- A "Submit another enquiry" link on the result page.
- Minimal inline CSS so the page is presentable for a portfolio (no external
  CSS, fonts or CDN).
- `/demo` routes excluded from the OpenAPI schema, so `/docs` still documents
  only the API.

**Out of scope (won't, this build)**
- Notifications from direct `POST /triage` calls. **Recorded limitation; a
  possible later build.** Adding it would modify build #4's route.
- Email/SMTP, Discord, multiple Slack channels, retries or queued sending.
- Any change to triage, storage, auth, the prompt, the model, the threshold, the
  `/triage` route, existing models, or existing tests.
- Client-side JavaScript, React, any frontend build tooling.
- Authentication on the form itself, CSRF protection, rate limiting (see
  Security posture).
- Deployment, HTTPS, binding to `0.0.0.0`, Docker, GDPR work.
- Pages that list or read back stored entries.
- A redirect from `/` to `/demo`.
- Enquiry text or contact details in the Slack message.

## Observable acceptance criteria
Each is proved by a named test, a commit, or output captured during the
acceptance step (doc 04, Principle 7). "Seen to fail" means the test was run
against a deliberately broken version that failed for the reason the test
exists, and that version was never committed.

1. **Form and result.** `GET /demo` on `127.0.0.1` returns an HTML form with a
   textarea named `enquiry_text` (`required`, `maxlength="10000"`) and a submit
   button. `POST /demo` with a valid enquiry shows `entry_id`, `intent`,
   `urgency`, `summary`, `key_details`, `suggested_route`, `confidence`,
   `reasoning`, `needs_review` and `escalate`. When `escalate` is true a visible
   escalation banner appears; when false it does not.
2. **Invalid input is stopped.** A blank, whitespace-only or 10,001-character
   enquiry shows a friendly error. Triage is never called, nothing is stored, and
   no Slack message is sent. The check is the API's `TriageRequest`; the handler
   does not re-implement it.
3. **Front door only.** The handler reaches triage only via HTTP
   `POST /triage`: a test shows the outgoing request carries `X-API-Key` equal
   to the configured key and a body with `source: "web-form"`. A test shows the
   web code imports none of `services.triage`, `services.storage`, `api.auth`,
   `api.app`.
4. **No secrets exposed.** Neither the API key nor the webhook URL appears in any
   rendered page (GET, success, and every error path) or in captured logs, and no
   committed file contains a real secret (`.env.example` stays blank). The test
   is seen to fail first.
5. **Notification content.** A successful triage sends exactly one Slack POST
   with a JSON `text`. When `escalate` is true the text contains `<!here>` and the
   `:rotating_light:` marker; when false it contains neither. A summary
   containing `<!channel>` or `<@U123>` arrives escaped (`&lt;!channel&gt;`), so
   only our own `<!here>` can ping. Proved against a fake webhook.
6. **Notification fails soft.** With the webhook URL blank, unreachable, or
   answering non-200, the result is still shown with a fixed status ("not
   configured", "unreachable" or "rejected"). No error text and no URL is shown.
7. **Tests are free and nothing regressed.** `uv run pytest -m "not eval"` with
   `ANTHROPIC_API_KEY` blanked (Git Bash) makes zero real Claude, Slack or
   network calls. The 244 tests passing at the end of build #4 all still pass,
   and no existing test file is edited.
8. **Live demo captured during acceptance.** The server is started with the
   documented command. One non-escalated and one escalated fictional enquiry are
   submitted through the browser. Captured: the result pages, the two Slack
   messages (screenshot, loud one visibly different), and CLI output showing both
   entries with `source = web-form`. Two paid Claude calls.
9. **No attribution trailers.** No commit in build #5 carries a
   `Co-Authored-By`, `Claude-Session` or other AI attribution trailer.
10. **Fixed API address.** The triage API address comes from `config.py`
    (`http://127.0.0.1:8000`), never from the incoming request or its Host
    header. A test submits the form with a forged Host header and shows the
    outgoing request still went to `127.0.0.1:8000`.
11. **Input is shown escaped.** An enquiry or model output containing
    `<script>` or other HTML is displayed as text (`&lt;script&gt;`), never as
    live markup, both in the result and in the refilled textarea. The test is
    seen to fail first.

## Accuracy bar
No new model judgement in this build: prompt, model, threshold and eval labels
are unchanged, so the build #1–#3 accuracy bar and eval set carry over as they
are. No eval run is required for build #5.

## Error handling
Inherited escalation design (build #3): `escalate` means a person must see the
enquiry. This build makes it visible: a banner on the page and a loud Slack
message. Every failure path shows a fixed, friendly message. A notification
failure never hides the triage result, because the entry is already stored.

## Security posture (local demo; recorded)
- **The form route is an unauthenticated door that holds the key.** Anyone who
  can reach `/demo` can trigger paid triage calls. The only protection is binding
  to `127.0.0.1`. Never run with `--host 0.0.0.0`.
- **No CSRF protection.** While the server is running, a malicious web page open
  in the same browser could submit to the form. Run the server only while
  demoing, and stop it afterwards.
- **The webhook URL is a secret:** whoever holds it can post into the channel.
  It lives only in `.env`. Never paste it into chat, a prompt, the shell history
  or a commit.

## Data / privacy
- Demo data is the director's own or fictional. No real customer data.
- Form submissions are stored in `data/triage.db` (gitignored) by the existing
  API, as with any API call.
- Slack is a third party: the message carries the entry id, labels, confidence
  and summary only. It carries no raw enquiry text and no contact details.

## Cost
- One Claude call per submission (the existing Haiku-class model): fractions of
  a penny to pennies each. Slack incoming webhooks are free.
- Acceptance makes two paid calls. Automated tests make none.
- Keep the provider spending cap on.