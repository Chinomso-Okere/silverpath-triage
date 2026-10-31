from pydantic import AwareDatetime, BaseModel, Field

from silverpath_triage.models.triage import Intent, Route, TriageRecord

class HumanVerdict(BaseModel):
    correct_intent: Intent | None = None
    correct_route: Route | None = None
    reviewed_at: AwareDatetime | None = None   # UTC, timezone-aware

class TriageEntry(BaseModel):
    id: int | None = None                 # None until saved; set by the database
    created_at: AwareDatetime             # UTC, timezone-aware
    source: str                           # enquiry file path as given
    enquiry_text: str                     # the full original enquiry
    model: str                            # config.MODEL at run time
    confidence_threshold: float           # config.CONFIDENCE_THRESHOLD at run time
    schema_version: int = 1
    record: TriageRecord                  # unchanged build #1 output
    verdict: HumanVerdict = Field(default_factory=HumanVerdict)  # empty on creation
