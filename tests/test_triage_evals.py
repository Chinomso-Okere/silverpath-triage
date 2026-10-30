"""Eval set: one real Claude call per case (9 in total). Run: uv run pytest -v"""
import pytest

from silverpath_triage.config import SAMPLES_DIR
from silverpath_triage.models.triage import Intent, Route
from silverpath_triage.services.triage import build_record, triage_enquiry

# (sample file, expected intent, expected route, expected needs_review)
# None means "not asserted for this case".
CASES = [
    pytest.param("eval_01_new_enquiry.txt", Intent.new_enquiry, Route.sales, None, id="new_enquiry"),
    pytest.param("eval_02_existing_booking.txt", Intent.existing_customer, Route.support, None, id="existing_booking"),
    pytest.param("eval_03_complaint.txt", Intent.complaint, Route.support, None, id="complaint"),
    pytest.param("eval_04_billing_refund.txt", Intent.billing, Route.billing, None, id="billing_refund"),
    pytest.param("eval_05_spam_seo.txt", Intent.spam, Route.ignore, None, id="spam_seo"),
    pytest.param("eval_06_other_job_application.txt", Intent.other, Route.human_review, None, id="other_job_application"),
    pytest.param("eval_07_vulnerable_new_enquiry.txt", Intent.new_enquiry, Route.human_review, None, id="vulnerable_new_enquiry"),
    pytest.param("eval_08_vague_short.txt", None, Route.human_review, True, id="vague_short"),
    pytest.param("eval_09_mixed_complaint_bill.txt", Intent.complaint, Route.support, None, id="mixed_complaint_bill"),
]


@pytest.mark.parametrize(("filename", "intent", "route", "review"), CASES)
def test_triage_eval(filename, intent, route, review):
    text = (SAMPLES_DIR / filename).read_text(encoding="utf-8")
    record = build_record(triage_enquiry(text))

    mismatches = []
    if intent is not None and record.intent != intent:
        mismatches.append(f"intent: expected {intent.value}, got {record.intent.value}")
    if route is not None and record.suggested_route != route:
        mismatches.append(f"route: expected {route.value}, got {record.suggested_route.value}")
    if review is not None and record.needs_review != review:
        mismatches.append(f"needs_review: expected {review}, got {record.needs_review}")

    assert not mismatches, (
        f"{filename}: " + "; ".join(mismatches)
        + f" (confidence={record.confidence:.2f}; reasoning: {record.reasoning})"
    )
