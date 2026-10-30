import sys
from datetime import datetime
from pathlib import Path

from silverpath_triage.config import CONFIDENCE_THRESHOLD, OUTPUTS_DIR, SAMPLES_DIR
from silverpath_triage.models.triage import TriageRecord
from silverpath_triage.services.triage import TriageError, build_record, triage_enquiry

DEFAULT_ENQUIRY = SAMPLES_DIR / "enquiry_01.txt"


def format_record(record: TriageRecord) -> str:
    def show(value: str | None) -> str:
        return value if value else "-"

    d = record.key_details
    return "\n".join([
        "=== Triage result ===",
        f"Intent:         {record.intent.value}",
        f"Urgency:        {record.urgency.value}",
        f"Route:          {record.suggested_route.value}",
        f"Confidence:     {record.confidence:.2f} (threshold {CONFIDENCE_THRESHOLD:.2f})",
        f"Needs review:   {'YES' if record.needs_review else 'no'}",
        f"Summary:        {record.summary}",
        f"Reasoning:      {record.reasoning}",
        "Key details:",
        f"  Name:         {show(d.customer_name)}",
        f"  Service:      {show(d.requested_service)}",
        f"  Date:         {show(d.deadline_or_date)}",
        f"  Location:     {show(d.location_or_postcode)}",
        f"  Phone:        {show(d.contact_info.phone)}",
        f"  Email:        {show(d.contact_info.email)}",
    ])


def save_record(record: TriageRecord, source: Path) -> Path:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)  # gitignored, so absent on a fresh clone
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = OUTPUTS_DIR / f"{stamp}_{source.stem}.json"
    out_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ENQUIRY
    try:
        enquiry_text = source.read_text(encoding="utf-8")
        record = build_record(triage_enquiry(enquiry_text))
    except (OSError, ValueError, TriageError) as e:
        sys.exit(f"Error: {e}")

    print(format_record(record))
    print(f"\nSaved: {save_record(record, source)}")


if __name__ == "__main__":
    main()
