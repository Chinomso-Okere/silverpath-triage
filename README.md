# Silverpath Inbound-Enquiry Triage (Build #1)

A local Python proof-of-concept that triages one raw inbound enquiry (form or
email text) into a structured result using a single Claude call. Output prints
to the terminal and is saved as JSON in `data/outputs/`.

AI layer only — no database, API, or frontend. See [docs/PRD.md](docs/PRD.md)
(what and why) and [docs/TECHNICAL_PRD.md](docs/TECHNICAL_PRD.md) (how).

## Setup
1. Install [uv](https://docs.astral.sh/uv/).
2. `uv sync`
3. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

## Status
Build-sequence step 1 (scaffold + env) only. No triage logic yet.
