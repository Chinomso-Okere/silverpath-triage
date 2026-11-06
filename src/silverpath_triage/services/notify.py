import logging

import httpx

from silverpath_triage import config
from silverpath_triage.models.api import TriageResponse
from silverpath_triage.models.notify import NotificationResult, NotificationStatus

logger = logging.getLogger(__name__)
# httpx logs every request's full URL at INFO, and the webhook URL is the secret.
logging.getLogger("httpx").setLevel(logging.WARNING)


def slack_escape(text: str) -> str:
    # The one home for Slack escaping. "&" goes first so the others aren't doubled.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_slack_text(response: TriageResponse) -> str:
    # Takes the API response, which has no enquiry text; key_details (contact
    # details) are left out. Model-written strings are escaped before our own
    # markup is added, so only our <!here> can ping.
    lines = []
    if response.escalate:
        lines.append("<!here> :rotating_light: *ESCALATE*: a person must see this")
    lines.append(
        f"*Entry #{response.entry_id}*"
        f" · intent: {slack_escape(response.intent.value)}"
        f" · urgency: {slack_escape(response.urgency.value)}"
        f" · route: {slack_escape(response.suggested_route.value)}"
        f" · confidence: {response.confidence:.2f}"
    )
    lines.append(f"Summary: {slack_escape(response.summary)}")
    return "\n".join(lines)


async def notify_slack(response: TriageResponse, client: httpx.AsyncClient) -> NotificationResult:
    # One POST, no retries. Logs carry the exception type or status code only:
    # never the URL, the payload, Slack's reply or exception text.
    loud = response.escalate
    url = config.WEBHOOK_URL  # read at call time
    if not url:
        return NotificationResult(status=NotificationStatus.not_configured, loud=loud)
    try:
        reply = await client.post(
            url,
            json={"text": build_slack_text(response)},
            timeout=config.WEBHOOK_TIMEOUT_SECONDS,
        )
    # InvalidURL is not an HTTPError in httpx; a malformed URL must still fail soft.
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning("slack notification unreachable: %s", type(exc).__name__)
        return NotificationResult(status=NotificationStatus.unreachable, loud=loud)
    if reply.status_code != 200:
        logger.warning("slack notification rejected: HTTP %d", reply.status_code)
        return NotificationResult(status=NotificationStatus.rejected, loud=loud)
    return NotificationResult(status=NotificationStatus.sent, loud=loud)
