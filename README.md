# Silverpath Inbound-Enquiry Triage (Build #1)

Reads one raw inbound enquiry (web form or email text) and returns a structured
triage decision (intent, urgency, route, key details, confidence) using a
single Claude call, flagging low-confidence results for human review.

**Proof of concept, AI layer only.** It suggests a route and a person acts on
it. There is no database, API, frontend or automatic sending.

## Setup
1. Install [uv](https://docs.astral.sh/uv/), then run `uv sync`.
2. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

## Run
- **Triage one enquiry:** `uv run python -m silverpath_triage.main [path/to/enquiry.txt]`
  (defaults to `data/samples/enquiry_01.txt`). Prints the result and saves it
  as JSON in `data/outputs/`.
- **Run the eval set:** `uv run pytest -v`. This makes 9 real API calls, one
  per case.

## Docs
- [docs/PRD.md](docs/PRD.md): what and why
- [docs/TECHNICAL_PRD.md](docs/TECHNICAL_PRD.md): how
