from enum import Enum
from pydantic import BaseModel


class NotificationStatus(str, Enum):
    sent = "sent"
    not_configured = "not_configured"   # webhook URL blank: nothing sent
    unreachable = "unreachable"         # network error or timeout
    rejected = "rejected"               # Slack answered with a non-200 status


class NotificationResult(BaseModel):
    status: NotificationStatus
    loud: bool  # True when the escalate format was used
