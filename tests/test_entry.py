"""TriageEntry / HumanVerdict checks: built from a hand-made TriageRecord.
Zero API calls, no database."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from silverpath_triage import config
from silverpath_triage.models.entry import HumanVerdict, TriageEntry
from silverpath_triage.models.triage import (
    ContactInfo, Intent, KeyDetails, Route, TriageRecord, Urgency,
)


def make_record() -> TriageRecord:
    return TriageRecord(
        intent=Intent.new_enquiry,
        urgency=Urgency.medium,
        summary="Wants a quote for a garden clearance next month.",
        key_details=KeyDetails(
            customer_name="Test Person",
            requested_service="garden clearance",
            deadline_or_date="next month",
            location_or_postcode="AB1 2CD",
            contact_info=ContactInfo(phone="01234 567890", email="test@example.com"),
        ),
        suggested_route=Route.sales,
        confidence=0.87,
        reasoning="Clear request for a new service.",
        needs_review=False,
    )


def make_entry(record: TriageRecord | None = None) -> TriageEntry:
    return TriageEntry(
        created_at=datetime.now(timezone.utc),
        source="data/samples/enquiry_01.txt",
        enquiry_text="Hi, could you quote for a garden clearance?",
        model=config.MODEL,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        record=record or make_record(),
    )


def assert_utc_aware(value: datetime) -> None:
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_new_entry_defaults():
    entry = make_entry()
    assert entry.id is None
    assert entry.schema_version == 1
    assert entry.model == config.MODEL
    assert entry.confidence_threshold == config.CONFIDENCE_THRESHOLD


def test_new_entry_verdict_is_empty():
    verdict = make_entry().verdict
    assert verdict == HumanVerdict()
    assert verdict.correct_intent is None
    assert verdict.correct_route is None
    assert verdict.reviewed_at is None


def test_entries_do_not_share_a_verdict():
    first, second = make_entry(), make_entry()
    assert first.verdict is not second.verdict
    first.verdict.correct_intent = Intent.complaint
    assert second.verdict.correct_intent is None


def test_record_is_wrapped_unchanged():
    record = make_record()
    assert make_entry(record).record == record


def test_json_round_trip():
    entry = make_entry()
    restored = TriageEntry.model_validate_json(entry.model_dump_json())
    assert restored == entry
    assert restored.record == entry.record
    assert restored.record.confidence == entry.record.confidence
    assert restored.created_at == entry.created_at
    assert_utc_aware(restored.created_at)


def test_json_round_trip_with_verdict():
    entry = make_entry()
    entry.verdict = HumanVerdict(
        correct_intent=Intent.complaint,
        correct_route=Route.support,
        reviewed_at=datetime.now(timezone.utc),
    )
    restored = TriageEntry.model_validate_json(entry.model_dump_json())
    assert restored == entry
    assert restored.verdict == entry.verdict
    assert_utc_aware(restored.verdict.reviewed_at)


def test_invalid_verdict_value_is_rejected():
    with pytest.raises(ValidationError):
        HumanVerdict(correct_intent="nonsense")
    with pytest.raises(ValidationError):
        HumanVerdict(correct_route="nonsense")


def test_naive_datetimes_are_rejected():
    naive = datetime(2026, 10, 31, 12, 0)
    with pytest.raises(ValidationError):
        TriageEntry(
            created_at=naive,
            source="x.txt",
            enquiry_text="text",
            model=config.MODEL,
            confidence_threshold=config.CONFIDENCE_THRESHOLD,
            record=make_record(),
        )
    with pytest.raises(ValidationError):
        HumanVerdict(reviewed_at=naive)
