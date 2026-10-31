from pydantic import BaseModel, Field, field_validator

from silverpath_triage import config
from silverpath_triage.models.triage import Intent, KeyDetails, Route, Urgency


class TriageRequest(BaseModel):
    enquiry_text: str = Field(max_length=config.MAX_ENQUIRY_CHARS)
    source: str = Field(default="api", max_length=200)

    @field_validator("enquiry_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("enquiry_text must not be empty")
        return v


class TriageResponse(BaseModel):
    entry_id: int
    intent: Intent
    urgency: Urgency
    summary: str
    key_details: KeyDetails
    suggested_route: Route
    confidence: float
    reasoning: str
    needs_review: bool
    escalate: bool  # set by hand from record.escalate; never serialised on the record
