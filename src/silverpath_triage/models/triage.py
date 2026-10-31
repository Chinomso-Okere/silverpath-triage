from enum import Enum
from pydantic import BaseModel, Field

class Intent(str, Enum):
    new_enquiry = "new_enquiry"
    existing_customer = "existing_customer"
    complaint = "complaint"
    billing = "billing"
    spam = "spam"
    other = "other"

class Urgency(str, Enum):
    low = "low"; medium = "medium"; high = "high"

class Route(str, Enum):
    sales = "sales"; support = "support"; billing = "billing"
    human_review = "human_review"; ignore = "ignore"

class ContactInfo(BaseModel):
    phone: str | None = None
    email: str | None = None

class KeyDetails(BaseModel):
    customer_name: str | None = None
    requested_service: str | None = None
    deadline_or_date: str | None = None
    location_or_postcode: str | None = None
    contact_info: ContactInfo = Field(default_factory=ContactInfo)

class TriageResult(BaseModel):
    intent: Intent
    urgency: Urgency
    summary: str
    key_details: KeyDetails
    suggested_route: Route
    confidence: float = Field(ge=0, le=1,
        description="0 to 1 confidence in the intent/route decision")
    reasoning: str = Field(description="one short sentence on why")

class TriageRecord(TriageResult):
    needs_review: bool

    @property
    def escalate(self) -> bool:
        # A person must see this: the model is unsure, or it routed to a person.
        # Computed on every read; never serialised or stored.
        return self.needs_review or self.suggested_route == Route.human_review
