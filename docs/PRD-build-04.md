# PRD — Silverpath Inbound-Enquiry Triage, Build #4: API layer

## Context
Builds #1 (AI layer), #2 (SQLite storage) and #3 (the `escalate` flag) are
complete and verified — `docs/ACCEPTANCE-build-03.md`, 13 of 13 PASS, code at
`538159d`. Until now the triage chain has only ever been run by hand
(`uv run python -m silverpath_triage.main triage <file>`). Earlier builds' docs
stay where they are, unchanged, as background.

## Problem
There is no way for anything other than a person at the command line to get an
enquiry triaged. The agency's real goal is for an enquiry to arrive from an
outside source — a web form, an inbox, another service — and come back triaged
without someone running a command. This build adds the first piece of that: an
HTTP endpoint that exposes the existing triage chain.

This is also the first time the system is exposed to anything outside the local
command line, so it is the first build where *security* is in scope rather than
deferred.

## Decision
Add an **API layer** (FastAPI) with a single endpoint, `POST /triage`, that
drives the **existing** chain — `triage_enquiry()` → `build_record()` →
`save_entry()` — and returns the triage result over HTTP. The AI, storage and
escalation logic are reused unchanged; the API layer only orchestrates and maps
to HTTP.

Two design facts that shape the whole build:

- **`escalate` must be put into the response explicitly.** It is a plain
  `@property` on `TriageRecord`, deliberately not serialised (build #3
  trade-off, `TECHNICAL_PRD-build-03.md`). An HTTP response built from
  `model_dump()` would silently drop it. A new response model sets it by hand.
- **This is the first external surface, so it is guarded from the start:** a
  required API key, bound to the local machine only, with blank and oversized
  input rejected before the paid model is ever called.

## Type
**Proof of Concept (PoC).** Local-only (`127.0.0.1`), run by hand on one
machine, no real external caller yet and no users. It proves the triage chain
can be driven by an HTTP request and returns a correct, guarded response.
Wiring a real external caller — and the full exposure concerns that come with
it (TLS, rate limiting, GDPR lawful basis, encryption at rest) — is build #5.

## The one workflow
A caller sends an enquiry as an HTTP request; the system triages it, stores it,
and returns the result.

- **Input:** `POST /triage` with header `X-API-Key: <key>` and JSON body
  `{ "enquiry_text": "<the enquiry>", "source": "<optional label>" }`.
  `source` is optional and defaults to `"api"`.
- **Output:** HTTP 200 with a JSON body (`TriageResponse`) carrying the full
  triage result **plus `needs_review` and `escalate` as explicit fields plus
  the new `entry_id`**. The entry is saved to the existing SQLite database by
  the same chain the CLI uses, so API entries appear in `list`, `show`,
  `verify` and `list --escalated`.

## Scope (MoSCoW)

| Priority | Item |
| --- | --- |
| Must | `POST /triage` endpoint driving the existing `triage_enquiry → build_record → save_entry` chain |
| Must | A `TriageResponse` model that includes `needs_review` and `escalate` explicitly, plus `entry_id`; `escalate` mapped from `record.escalate` by hand |
| Must | A `TriageRequest` model: required non-empty `enquiry_text` (max 10,000 chars), optional `source` defaulting to `"api"` |
| Must | Blank/whitespace-only or over-length `enquiry_text` rejected with 422 **before any model call or DB write** |
| Must | API-key auth via `X-API-Key` header; key in `.env` as `SILVERPATH_API_KEY`, compared with `secrets.compare_digest`; never logged or echoed |
| Must | Fail-closed: a blank/unset key configuration rejects every request (503) |
| Must | Auth checked **before** body validation: bad key always 401, never 422 |
| Must | Server bound to `127.0.0.1` only; `0.0.0.0` out of scope |
| Must | Enquiry text never logged |
| Must | Clean HTTP error mapping (`TriageError` → 502, `StorageError` → 500); no tracebacks leaked |
| Must | New deps limited to `fastapi`, `uvicorn` (runtime) and `httpx` (dev) |
| Must | New API tests are free (stubbed triage, temp DB) and honour the existing no-real-client and no-real-DB guards; no existing test edited |
| Must | The auth "rejected without a valid key" test seen to fail first (doc 04 P7) |
| Must | README documents the endpoint; build #3 docs relabelled from "current" |
| Must | No commit from this build carries a Claude attribution trailer |
| Should | `/docs` and `/openapi.json` left enabled for local convenience (recorded decision) |
| Won't | Network exposure, binding beyond localhost, TLS |
| Won't | Rate limiting, raw request-body-size limit at the server |
| Won't | GDPR lawful basis, retention policy, privacy notice, encryption at rest |
| Won't | GET read-back endpoints (list/show over HTTP) |
| Won't | Any change to the prompt, model, threshold, eval labels, or the frozen `TriageResult`/`TriageRecord` fields |
| Won't | Database schema change, migration or backfill; frontend; Postgres; background workers |

## Observable acceptance criteria
The build is done when:

**Auth & secrets**
1. With `SILVERPATH_API_KEY` set to a non-blank value, a `POST /triage`
   carrying the correct key in `X-API-Key` and a valid body returns **200**.
   (free, stubbed triage)
2. A request with a missing or wrong key is rejected with **401** before any
   work — no Anthropic client constructed, no DB write. A free test proves it,
   and this test was **seen to fail first** against a deliberately allow-all
   auth dependency (failing output captured in the step report, doc 04 P7);
   the broken version is never committed.
3. **Fail-closed:** if `SILVERPATH_API_KEY` is unset or blank, every request is
   rejected with **503** — even one sent with a plausible key — with no model
   call and no DB write. A free test proves it.
4. The key check uses `secrets.compare_digest`. Neither the configured key nor
   the submitted key appears in any response body, any response header, or any
   captured log line. Free tests assert this.
5. `.env.example` gains a blank `SILVERPATH_API_KEY=` line and keeps the
   existing `ANTHROPIC_API_KEY=` line.

**Request validation (reject before spending)**
6. Missing `enquiry_text` → **422**, no model call, no DB write.
7. Empty or whitespace-only `enquiry_text` → **422**, no model call, no DB
   write.
8. `enquiry_text` longer than **10,000 characters** → **422**, no model call,
   no DB write.
9. `source` is optional: omitted → the stored entry's `source` is `"api"`;
   supplied → that value is stored. Free tests prove both.

**Success path & response contract**
10. A valid, authenticated request returns **200** with a JSON body containing
    the full triage result **and** `needs_review` **and** `escalate` as
    explicit fields **and** the new `entry_id`. (free, stubbed)
11. The response's `escalate` equals the code-computed `record.escalate`:
    **true** for a stub routed to `human_review`, **false** for a confident
    stub routed to `sales`. A free test covers both.
12. The `entry_id` refers to a row actually saved: fetching that id
    (`get_entry`, or CLI `show <id>`) returns the same triage data. (free,
    stubbed)
13. An API-submitted entry whose stubbed triage routes to `human_review`
    appears in `list_entries(escalated_only=True)` and in CLI
    `list --escalated`. (free)

**Error mapping (clean messages, no tracebacks)**
14. When triage raises `TriageError`, the endpoint returns **502** with a clear
    message, no traceback, and no DB write. (free, stubbed to raise)
15. When storage raises `StorageError`, the endpoint returns **500** with a
    clear message and no traceback. (free, stubbed to raise)

**Local-only & surface**
16. The documented run command binds to `127.0.0.1`; `0.0.0.0` is out of scope.
    At acceptance, with the server running,
    `netstat -ano | findstr :8000` shows it listening on `127.0.0.1` only;
    output captured.
17. `/docs` and `/openapi.json` are enabled (recorded decision). A free test
    confirms `/openapi.json` is served and that neither the API key nor any
    stored enquiry text appears in it.
18. Enquiry text is **never logged**: a free test drives a request and asserts
    no captured log record contains the enquiry body.

**Cost, suite integrity & hygiene**
19. `uv run pytest -m "not eval"` passes with **zero API calls** (Anthropic
    client never constructed) and **zero real-database access** — the new API
    tests honour both existing guards. **No existing build #1–#3 test is
    edited**; if any existing test needs changing, stop and report.
20. **One paid end-to-end proof**, run once at acceptance (not in the automated
    suite): with real `ANTHROPIC_API_KEY` and `SILVERPATH_API_KEY`, start the
    server and `curl` one sample enquiry with the correct key → **200** with a
    well-formed response including `escalate` and `entry_id`, then visible via
    CLI `show <id>`. The same curl with a missing/wrong key → **401** (free, no
    model call). During this proof, confirm no captured log line contains the
    enquiry text or either key. Captured in the acceptance doc.
21. No commit from this build carries a Claude attribution trailer
    (`%(trailers)` empty for every build-04 commit; zero
    `co-authored-by`/`claude-session` lines).
22. README documents the API — run command, request/response shape,
    `X-API-Key` header, local-only note — and the build #3 docs that still say
    "current" are relabelled.
23. **Auth is checked before body validation.** A request with both a
    missing/wrong key **and** an invalid body (missing or over-length
    `enquiry_text`) returns **401**, never 422 — an unauthenticated caller
    cannot probe the validation rules. A free test proves it (bad key + empty
    body → 401; bad key + 20,000-char body → 401).

## Accuracy bar
- **The API layer: 100%, deterministic, test-proven.** Correct status codes,
  auth enforced and checked first, `escalate` present and correct, `entry_id`
  returned and real, blank/over-length rejected with no model call. Every one
  is covered by a free test.
- **Triage accuracy is unchanged and not re-measured.** The prompt, model and
  threshold do not change. The single paid end-to-end proof confirms the whole
  chain works over HTTP; it is not an accuracy measurement.

## Error handling
- **Escalation design unchanged** (doc 03): the confident majority is routed
  automatically; low-confidence or `human_review`-routed enquiries carry
  `escalate = true` in the response and show in the CLI `--escalated` queue.
- **At the HTTP boundary:** auth failures → 401 (misconfiguration → 503);
  invalid input → 422 before any spend; model failure → 502; storage failure
  → 500. All with clear messages, never a traceback, and never echoing the
  submitted enquiry or the key.

## Data / privacy
- API-submitted enquiries are stored in the existing `data/triage.db`, which
  already holds personal data and is gitignored and never committed. Tests use
  only a temporary database and the fictional `data/samples/`.
- **Local-only is the privacy guard for this build.** The endpoint is reachable
  only from the machine it runs on, so no enquiry crosses a network. The full
  data-protection work (lawful basis, retention, privacy notice, encryption at
  rest, secure transport) is required before any real, network-delivered
  enquiry is accepted — carried forward to build #5.
- Enquiry text is never logged; validation errors never echo the submitted
  input back.

## Cost
- Each successful request makes one paid Haiku call (pennies). Blank and
  over-length input are rejected with no call, so a malformed request costs
  nothing. Local-only + required key keep the endpoint from being driven by
  anything but you.
- The automated suite is free (stubbed). One paid call at acceptance, only when
  asked. Keep the provider spending cap on (doc 05).

## Out of scope
- Network exposure, binding beyond `127.0.0.1`, TLS, rate limiting, a
  server-level body-size limit.
- GDPR lawful basis, retention, privacy notice, encryption at rest.
- GET read-back endpoints; frontend; Postgres; background workers.
- Any change to the prompt, model, threshold, eval labels, or the frozen
  `TriageResult`/`TriageRecord` fields.
- Build #2/#3 carried-forward items (`£` display, journal-file secure delete,
  `export`, duplicate detection).
- Editing, moving or renaming earlier builds' docs.