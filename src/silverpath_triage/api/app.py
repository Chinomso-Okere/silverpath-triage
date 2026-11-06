import logging
from datetime import datetime, timezone

import anthropic
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from silverpath_triage import config
from silverpath_triage.api.auth import authenticate_triage_post, require_api_key
from silverpath_triage.models.api import TriageRequest, TriageResponse
from silverpath_triage.models.entry import TriageEntry
from silverpath_triage.services import storage
from silverpath_triage.services import triage as triage_service
from silverpath_triage.services.storage import StorageError
from silverpath_triage.services.triage import TriageError, build_record
from silverpath_triage.web.routes import router as demo_router

logger = logging.getLogger(__name__)

# /docs and /openapi.json stay enabled (recorded decision: localhost only).
app = FastAPI(title="Silverpath triage")
# Authenticates POST /triage before any body parsing; the route keeps its own check too.
app.middleware("http")(authenticate_triage_post)
app.include_router(demo_router)


@app.post("/triage")
def triage(body: TriageRequest, _: None = Depends(require_api_key)) -> TriageResponse:
    # Orchestration only: the same chain cmd_triage runs.
    created_at = datetime.now(timezone.utc)
    record = build_record(triage_service.triage_enquiry(body.enquiry_text))
    entry = TriageEntry(
        created_at=created_at,
        source=body.source,
        enquiry_text=body.enquiry_text,
        model=config.MODEL,
        confidence_threshold=config.CONFIDENCE_THRESHOLD,
        record=record,
    )
    entry_id = storage.save_entry(entry, db_path=config.DB_PATH)
    # escalate is a plain property, never serialised, so it is set by hand.
    return TriageResponse(entry_id=entry_id, **record.model_dump(), escalate=record.escalate)


# Error handlers. Responses carry fixed messages only: never the exception text
# (a StorageError names the database path; a TriageError can hold model output),
# never the enquiry, never a key. Logs carry the exception type only.

def _model_failure(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("triage failed: %s", type(exc).__name__)
    return JSONResponse(
        status_code=502,
        content={"detail": "The triage service could not produce a valid result."},
    )


app.add_exception_handler(TriageError, _model_failure)
app.add_exception_handler(anthropic.APIError, _model_failure)  # model unreachable


@app.exception_handler(StorageError)
def _storage_failure(request: Request, exc: StorageError) -> JSONResponse:
    logger.warning("save failed: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "The entry could not be saved."})


@app.exception_handler(RequestValidationError)
def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Location and message only: FastAPI's default 422 echoes the submitted input.
    detail = [{"loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})
