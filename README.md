# Silverpath Inbound-Enquiry Triage (Builds #1–#4)

Reads one raw inbound enquiry (web form or email text) and returns a structured
triage decision (intent, urgency, route, key details, confidence) using a
single Claude call, flagging low-confidence results for human review. Each run
is saved as an entry in a local SQLite database, so results can be listed,
shown, checked against a human verdict and deleted. An enquiry can be triaged
from the command line, or sent to a small local HTTP endpoint.

**Proof of concept.** It suggests a route and a person acts on it. There is a
local database and a local-only HTTP endpoint, but no frontend, automation or
automatic sending. It is not production-ready (see [What the API is not](#what-the-api-is-not)).

## Setup
1. Install [uv](https://docs.astral.sh/uv/), then run `uv sync`.
2. Copy `.env.example` to `.env` and set two keys:
   - `ANTHROPIC_API_KEY`: needed for `triage`, for every API request that
     reaches the model, and for the paid evals. The other commands and the free
     tests run without it.
   - `SILVERPATH_API_KEY`: needed to run the API. It can be any strong random
     string; one way to make one is
     `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`.
     Keep it ASCII. If it is blank or unset the server answers **503** to every
     request (it fails closed). Restart the server after changing `.env`.

`.env` is gitignored. Never commit a key.

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

## API
One endpoint, `POST /triage`, runs the same triage-and-save chain as the
`triage` command. Start it with:

```
uv run uvicorn silverpath_triage.api.app:app --host 127.0.0.1 --port 8000
```

It listens on `127.0.0.1` only, so it can be reached from this machine and
nothing else. Keep the host as shown.

**Request:** header `X-API-Key: <your SILVERPATH_API_KEY>` and a JSON body:

```json
{"enquiry_text": "Hi, could you quote for a garden clearance?", "source": "web-form"}
```

- `enquiry_text` is required, must not be blank, and can be at most 10,000
  characters.
- `source` is optional (up to 200 characters) and defaults to `"api"`. It is
  stored with the entry.

**Example** (Git Bash). In PowerShell, plain `curl` is an alias for something
else, so use `curl.exe` or Git Bash:

```
curl -X POST http://127.0.0.1:8000/triage \
  -H "X-API-Key: <your SILVERPATH_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"enquiry_text": "Hi, could you quote for a garden clearance?"}'
```

**Response (200):** the triage result plus the two flags and the new entry id.
The values below are made up:

```json
{
  "entry_id": 12,
  "intent": "new_enquiry",
  "urgency": "medium",
  "summary": "Wants a quote for a garden clearance next month.",
  "key_details": {
    "customer_name": "Test Person",
    "requested_service": "garden clearance",
    "deadline_or_date": "next month",
    "location_or_postcode": "AB1 2CD",
    "contact_info": {"phone": "01234 567890", "email": "test@example.com"}
  },
  "suggested_route": "sales",
  "confidence": 0.87,
  "reasoning": "Clear request for a new service.",
  "needs_review": false,
  "escalate": false
}
```

`needs_review` and `escalate` mean what they do in the CLI and are computed by
code, not the model.

**Stored like the CLI.** Each successful request saves an entry in
`data/triage.db`, so it shows up in `list`, `list --escalated`, `show <id>` and
`verify <id>`. Entries sent through the API carry the `source` you gave (default
`api`).

**Errors** (the body is `{"detail": ...}`; no stack traces, and your enquiry and
the keys are never echoed back):

| Status | When | Detail |
| --- | --- | --- |
| 401 | Missing or wrong key. Checked before anything else, including a malformed body | `Invalid or missing API key.` |
| 503 | `SILVERPATH_API_KEY` is blank or unset | `Endpoint is not configured.` |
| 422 | Missing, blank or over-length `enquiry_text`, or another invalid field. No model call and nothing saved | A list of field locations and messages |
| 502 | The model returned nothing usable, or could not be reached. Nothing saved | `The triage service could not produce a valid result.` |
| 500 | The entry could not be saved | `The entry could not be saved.` |

**Cost.** Each successful request makes one paid Claude call (pennies). Requests
rejected with 401, 503 or 422 make none. Keep the provider spending cap on.

**Docs.** While the server runs, `http://127.0.0.1:8000/docs` (interactive) and
`/openapi.json` are available without a key. They show the request and response
shapes only, never a key or stored data.

**Logging.** The app does not log enquiry text or either key.

### What the API is not
This is a local proof of concept, not a service you can put on a network.
- **Local only.** It is not reachable over a network.
- **No TLS**, so no encrypted transport.
- **No rate limiting**, and no server-level request-size limit (the 10,000
  character cap is checked once the body has been read).
- **One shared key.** No per-user keys, no rotation, no lockout.
- **One endpoint.** There is no way to list or read entries over HTTP; use the
  commands above.
- **Data-protection work is not done:** lawful basis, retention policy, privacy
  notice and encryption at rest. These are needed before any real enquiry
  arrives over a network, and belong to a later build.

## Tests
- **Free:** `uv run pytest -m "not eval"`. No API calls; each test uses its own
  temporary database. This includes the API tests, which stub the triage call
  and never touch the real database.
- **Paid evals:** `uv run pytest -m eval -s`. Makes 9 real API calls, one per
  case; `-s` shows each case's confidence. Evals never write to the database.
- The one paid end-to-end check of the API (a real request with a real key) is
  done by hand at acceptance. It is not part of the automated tests.

## Privacy
- `data/triage.db` holds personal data from enquiries (names, phones, emails,
  postcodes). It is gitignored and must never be committed. Enquiries sent to
  the API are stored there too.
- Use only the fictional samples in `data/samples/`. Do not paste a real key or
  a real enquiry into commits, issues or chat.
- For this build, keeping the API local-only is the privacy guard: no enquiry
  crosses a network.
- `delete <id>` erases an entry; deleted content is overwritten in the
  database file, not just unlinked.

## Docs
- [docs/PRD-build-04.md](docs/PRD-build-04.md): API build (current), what and why
- [docs/TECHNICAL_PRD-build-04.md](docs/TECHNICAL_PRD-build-04.md): API build (current), how
- [docs/PRD-build-03.md](docs/PRD-build-03.md): escalation build, what and why
- [docs/TECHNICAL_PRD-build-03.md](docs/TECHNICAL_PRD-build-03.md): escalation build, how
- [docs/ACCEPTANCE-build-03.md](docs/ACCEPTANCE-build-03.md): build #3 acceptance check and known limitations
- [docs/PRD-build-02.md](docs/PRD-build-02.md): storage build, what and why
- [docs/TECHNICAL_PRD-build-02.md](docs/TECHNICAL_PRD-build-02.md): storage build, how
- [docs/ACCEPTANCE-build-02.md](docs/ACCEPTANCE-build-02.md): acceptance check and known limitations
- [docs/PRD.md](docs/PRD.md), [docs/TECHNICAL_PRD.md](docs/TECHNICAL_PRD.md): build #1 (AI layer) background
