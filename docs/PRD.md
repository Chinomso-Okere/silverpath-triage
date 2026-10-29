# PRD — Silverpath Inbound-Enquiry Triage (Build #1)

## Problem
Silverpath AI's clients (UK service businesses — trades, clinics, salons, etc.)
receive inbound enquiries by web form and email. Sorting each one by hand —
what is this, how urgent, who should handle it — is slow, repetitive, and easy
to get wrong at volume. This build proves an AI can read a raw enquiry and
produce a correct, structured triage decision a human can act on.

## Type
**Proof of Concept (PoC).** Goal is to prove the approach works and to teach the
core build skills — NOT a deployed product. It makes a decision and shows it;
it does not act on it. (See "Out of scope".)

## The one workflow
A single enquiry in → one structured triage result out.

- **Input:** one raw inbound enquiry as plain text (a form submission or an
  email body, pasted or loaded from a file). Form and email are both just text —
  one input, one code path.
- **Output:** one validated result (a Pydantic model), containing:
  - `intent` — one of: new_enquiry, existing_customer, complaint, billing, spam, other
  - `urgency` — one of: low, medium, high
  - `summary` — one sentence, plain language, what the enquiry wants
  - `key_details`:
    - `customer_name` (optional)
    - `requested_service` (optional)
    - `deadline_or_date` (optional)
    - `location_or_postcode` (optional)
    - `contact_info`: `phone` (optional), `email` (optional)
  - `suggested_route` — one of: sales, support, billing, human_review, ignore
  - `confidence` — the model's own 0–1 confidence in its decision
  - `needs_review` — true when confidence is below the threshold (set by code,
    not by the model — this is the escalation hook)
  - `reasoning` — one short sentence on why this intent/route was chosen

- **Where the output goes:** printed to the terminal AND written as a JSON file
  into `data/outputs/`. A human reads it and acts. Nothing is sent or routed
  automatically.

## Observable acceptance criteria
This build is "done" when:
1. A raw enquiry (string) can be run through the script and returns a fully
   populated result matching the Pydantic model — every time, no parse errors.
2. The result prints to the terminal in a readable form AND is saved as a JSON
   file in `data/outputs/`.
3. `needs_review` is set to true whenever `confidence` is below the configured
   threshold, by deterministic code.
4. A hand-made eval set of ~8–10 example enquiries exists in `tests/`, each with
   its expected intent/route, and the evals run with one command.
5. On that eval set, the obvious cases are classified and routed correctly.
   (No numeric accuracy gate for a PoC — the bar is "it works end-to-end and
   gets the clear cases right.")

## Accuracy bar
A first build is expected to land around ~70–80% and improve with iteration.
Because this PoC only *suggests* a route and takes no real action, error impact
is low. We do not demand a fixed percentage. The bar is criterion 5 above.

## Error handling
**Escalation.** The model returns a confidence score; deterministic code flips
`needs_review` to true when confidence is below the threshold, so uncertain
enquiries are flagged for a human instead of being silently mis-routed.

## Out of scope (deliberately — these are later builds)
- No database / persistence beyond the JSON file (that's Build #2: Storage).
- No API or webhook to receive enquiries automatically (Build #3: Backend/API).
- No automatic sending, routing, email, or CRM action (Build #4: automation).
- No web/frontend interface.
- No multi-client routing rules (which client an enquiry belongs to is known by
  whoever received it; not modelled here).
- No regex-based extraction of phone/email yet — the model populates all fields
  in the PoC; deterministic regex extraction is a hardening step for later.

## Data / privacy note
Enquiries contain personal data (names, phone, email, location). For this local
PoC on sample/dummy enquiries this is fine and requires no action. The moment
this touches real customer enquiries, UK GDPR applies (storage, retention,
access) — to be designed into the later storage/API builds, not here.
