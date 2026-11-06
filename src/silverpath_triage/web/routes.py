import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates

from silverpath_triage import config
from silverpath_triage.models.api import TriageResponse
from silverpath_triage.models.notify import NotificationStatus
from silverpath_triage.services import notify

logger = logging.getLogger(__name__)

# Not API endpoints: kept out of /docs and /openapi.json.
router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Fixed page messages: never exception text, response bodies or the enquiry.
INVALID_INPUT = "Please enter an enquiry (not blank, at most 10,000 characters)."
NOT_CONFIGURED = "The demo server is not configured correctly (API key). See the README."
TRIAGE_FAILED = "The triage service could not produce a result. Please try again."
SAVE_FAILED = "The result could not be saved."
UNREACHABLE = "Could not reach the triage API. Is the server running on 127.0.0.1:8000?"
UNEXPECTED = "The triage API returned an unexpected response."

# API status -> (page message, page status). Anything else non-200 is UNEXPECTED.
API_ERRORS = {
    422: (INVALID_INPUT, 422),
    401: (NOT_CONFIGURED, 502),
    503: (NOT_CONFIGURED, 502),
    502: (TRIAGE_FAILED, 502),
    500: (SAVE_FAILED, 502),
}

NOTIFICATION_TEXT = {
    NotificationStatus.sent: "Slack notification sent.",
    NotificationStatus.not_configured: "Slack notification not configured (no webhook URL set).",
    NotificationStatus.unreachable: "Slack notification failed: Slack was unreachable.",
    NotificationStatus.rejected: "Slack notification failed: Slack rejected it.",
}


# Injectable so tests can swap each client.
async def get_triage_client():
    async with httpx.AsyncClient() as client:
        yield client


async def get_webhook_client():
    async with httpx.AsyncClient() as client:
        yield client


def _page(request: Request, status_code: int = 200, **context):
    defaults = dict(
        max_chars=config.MAX_ENQUIRY_CHARS,
        enquiry_text="",  # refilled on error only
        result=None,
        error=None,
        notification=None,
        notification_text=None,
    )
    return templates.TemplateResponse(
        request, "demo.html", {**defaults, **context}, status_code=status_code,
    )


@router.get("/demo")
async def demo_form(request: Request):
    return _page(request)


@router.post("/demo")
async def demo_submit(
    request: Request,
    # Default "" so a missing field still reaches the API, the one validator.
    enquiry_text: str = Form(default=""),
    triage_client: httpx.AsyncClient = Depends(get_triage_client),
    webhook_client: httpx.AsyncClient = Depends(get_webhook_client),
):
    # Front door only: the real POST /triage at the fixed address from config
    # (never from the request), with the key added here. No pre-checks: the
    # API's TriageRequest and auth are the one home for those rules.
    try:
        reply = await triage_client.post(
            f"{config.TRIAGE_API_URL}/triage",
            json={"enquiry_text": enquiry_text, "source": "web-form"},
            headers={"X-API-Key": config.API_KEY},
            timeout=config.TRIAGE_TIMEOUT_SECONDS,
        )
    # InvalidURL is not an HTTPError in httpx; it must still give the fixed page.
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning("triage API unreachable: %s", type(exc).__name__)
        return _page(request, 502, error=UNREACHABLE, enquiry_text=enquiry_text)

    if reply.status_code != 200:
        logger.warning("triage API answered HTTP %d", reply.status_code)
        message, status = API_ERRORS.get(reply.status_code, (UNEXPECTED, 502))
        return _page(request, status, error=message, enquiry_text=enquiry_text)

    try:
        result = TriageResponse.model_validate(reply.json())
    except ValueError as exc:  # bad JSON, or ValidationError (a ValueError) for the wrong shape
        logger.warning("triage API response unusable: %s", type(exc).__name__)
        return _page(request, 502, error=UNEXPECTED, enquiry_text=enquiry_text)

    # Success only: the entry is stored, so a notification failure never hides it.
    notification = await notify.notify_slack(result, webhook_client)
    return _page(
        request,
        result=result,
        notification=notification,
        notification_text=NOTIFICATION_TEXT[notification.status],
    )
