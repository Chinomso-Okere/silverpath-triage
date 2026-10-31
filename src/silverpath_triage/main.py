import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from silverpath_triage import config
from silverpath_triage.config import CONFIDENCE_THRESHOLD
from silverpath_triage.models.entry import TriageEntry
from silverpath_triage.models.triage import Intent, Route, TriageRecord
from silverpath_triage.services import storage
from silverpath_triage.services.storage import StorageError
from silverpath_triage.services.triage import TriageError, build_record, triage_enquiry

# Storage calls pass db_path=config.DB_PATH explicitly so it is read at call
# time (tests point it at a temporary database).


def escalation_reason(record: TriageRecord) -> str:
    # Why a person must see this; "-" exactly when record.escalate is false.
    if not record.escalate:
        return "-"
    routed = record.suggested_route == Route.human_review
    if record.needs_review and routed:
        return "both"
    return "low conf" if record.needs_review else "routed"


ESCALATE_TEXT = {
    "-": "no",
    "low conf": "YES (low confidence)",
    "routed": "YES (routed to human_review)",
    "both": "YES (low confidence and routed to human_review)",
}


def format_record(record: TriageRecord, threshold: float = CONFIDENCE_THRESHOLD) -> str:
    def show(value: str | None) -> str:
        return value if value else "-"

    d = record.key_details
    return "\n".join([
        "=== Triage result ===",
        f"Intent:         {record.intent.value}",
        f"Urgency:        {record.urgency.value}",
        f"Route:          {record.suggested_route.value}",
        f"Confidence:     {record.confidence:.2f} (threshold {threshold:.2f})",
        f"Needs review:   {'YES' if record.needs_review else 'no'}",
        f"Escalate:       {ESCALATE_TEXT[escalation_reason(record)]}",
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


def format_utc(value: datetime, with_seconds: bool = False) -> str:
    pattern = "%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M"
    return value.astimezone(timezone.utc).strftime(pattern)


def format_list_line(entry: TriageEntry) -> str:
    r = entry.record
    verified = entry.verdict.reviewed_at is not None
    return (
        f"{entry.id:>3}  {format_utc(entry.created_at):<16}  {r.intent.value:<17}  "
        f"{r.suggested_route.value:<12}  {r.confidence:.2f}  "
        f"{'YES' if r.needs_review else 'no':<6}  {escalation_reason(r):<8}  "
        f"{'yes' if verified else 'no':<8}  {entry.source}"
    )


LIST_HEADER = (
    f"{'ID':>3}  {'Created (UTC)':<16}  {'Intent':<17}  {'Route':<12}  Conf  "
    f"{'Review':<6}  {'Why':<8}  {'Verified':<8}  Source"
)


def format_entry(entry: TriageEntry) -> str:
    v = entry.verdict
    if v.reviewed_at is None:
        verdict_lines = ["Not yet verified."]
    else:
        verdict_lines = [
            f"Correct intent: {v.correct_intent.value if v.correct_intent else '-'}",
            f"Correct route:  {v.correct_route.value if v.correct_route else '-'}",
            f"Reviewed:       {format_utc(v.reviewed_at, with_seconds=True)} UTC",
        ]
    return "\n".join([
        f"=== Entry {entry.id} ===",
        f"Created:        {format_utc(entry.created_at, with_seconds=True)} UTC",
        f"Source:         {entry.source}",
        f"Model:          {entry.model}",
        f"Threshold:      {entry.confidence_threshold:.2f}",
        f"Schema version: {entry.schema_version}",
        "",
        format_record(entry.record, entry.confidence_threshold),
        "",
        "=== Original enquiry ===",
        entry.enquiry_text.rstrip("\n"),
        "",
        "=== Human verdict ===",
        *verdict_lines,
    ])


def cmd_triage(args: argparse.Namespace) -> None:
    enquiry_text = Path(args.file).read_text(encoding="utf-8")
    created_at = datetime.now(timezone.utc)
    record = build_record(triage_enquiry(enquiry_text))
    print(format_record(record))

    # Saved only after a complete, valid record exists.
    entry = TriageEntry(
        created_at=created_at,
        source=args.file,
        enquiry_text=enquiry_text,
        model=config.MODEL,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        record=record,
    )
    entry_id = storage.save_entry(entry, db_path=config.DB_PATH)
    print(f"\nSaved as entry {entry_id}")


def cmd_list(args: argparse.Namespace) -> None:
    entries = storage.list_entries(
        limit=args.limit,
        needs_review_only=args.needs_review,
        escalated_only=args.escalated,
        db_path=config.DB_PATH,
    )
    if not entries:
        if args.needs_review:
            print("No entries need review.")
        elif args.escalated:
            print("No entries need escalation.")
        else:
            print("No entries.")
        return
    print(LIST_HEADER)
    for entry in entries:
        print(format_list_line(entry))


def cmd_show(args: argparse.Namespace) -> None:
    entry = storage.get_entry(args.id, db_path=config.DB_PATH)
    if entry is None:
        sys.exit(f"No entry with id {args.id}")
    print(format_entry(entry))


def cmd_verify(args: argparse.Namespace) -> None:
    entry = storage.get_entry(args.id, db_path=config.DB_PATH)
    if entry is None:
        sys.exit(f"No entry with id {args.id}")
    previous = entry.verdict

    found = storage.set_verdict(
        args.id, Intent(args.intent), Route(args.route), db_path=config.DB_PATH
    )
    stored = storage.get_entry(args.id, db_path=config.DB_PATH) if found else None
    if stored is None:
        sys.exit(f"No entry with id {args.id}")

    if previous.reviewed_at is not None:
        print(
            f"Replaced previous verdict: intent={previous.correct_intent.value}, "
            f"route={previous.correct_route.value} "
            f"(reviewed {format_utc(previous.reviewed_at, with_seconds=True)} UTC)."
        )
    v = stored.verdict
    print("\n".join([
        f"Verified entry {stored.id} (stored):",
        f"  Correct intent: {v.correct_intent.value}",
        f"  Correct route:  {v.correct_route.value}",
        f"  Reviewed:       {format_utc(v.reviewed_at, with_seconds=True)} UTC",
    ]))


def cmd_delete(args: argparse.Namespace) -> None:
    entry = storage.get_entry(args.id, db_path=config.DB_PATH)
    if entry is None:
        sys.exit(f"No entry with id {args.id}")
    print("\n".join([
        f"Entry {entry.id}",
        f"Created: {format_utc(entry.created_at, with_seconds=True)} UTC",
        f"Source:  {entry.source}",
    ]))

    if not args.yes:
        try:
            answer = input("Delete this entry permanently? [y/N] ")
        except EOFError:
            print()
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print(f"Kept entry {entry.id}. Nothing was deleted.")
            return

    if not storage.delete_entry(args.id, db_path=config.DB_PATH):
        sys.exit(f"No entry with id {args.id}")
    print(f"Deleted entry {entry.id}.")


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got {value!r}")
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="silverpath_triage.main",
        description="Triage inbound enquiries and keep each run as a stored entry.",
    )
    commands = parser.add_subparsers(dest="command", metavar="command")

    triage = commands.add_parser("triage", help="triage one enquiry file and save it")
    triage.add_argument("file", help="path to the enquiry text file")
    triage.set_defaults(handler=cmd_triage)

    listing = commands.add_parser("list", help="list stored entries, newest first")
    filters = listing.add_mutually_exclusive_group()
    filters.add_argument("--needs-review", action="store_true",
                         help="only entries where the model is unsure "
                              "(confidence below the threshold)")
    filters.add_argument("--escalated", action="store_true",
                         help="only entries a person must see "
                              "(model unsure, or routed to human_review)")
    listing.add_argument("--limit", type=positive_int, default=20,
                         help="maximum entries to show (default 20)")
    listing.set_defaults(handler=cmd_list)

    show = commands.add_parser("show", help="show one entry in full")
    show.add_argument("id", type=int, help="entry id (from list)")
    show.set_defaults(handler=cmd_show)

    verify = commands.add_parser("verify", help="record the correct intent and route for an entry")
    verify.add_argument("id", type=int, help="entry id (from list)")
    verify.add_argument("--intent", required=True, choices=[i.value for i in Intent])
    verify.add_argument("--route", required=True, choices=[r.value for r in Route])
    verify.set_defaults(handler=cmd_verify)

    delete = commands.add_parser("delete", help="permanently delete an entry")
    delete.add_argument("id", type=int, help="entry id (from list)")
    delete.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    delete.set_defaults(handler=cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    try:
        args.handler(args)
    except (TriageError, StorageError, ValueError, OSError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
