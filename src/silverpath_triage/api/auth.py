import secrets

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from silverpath_triage import config


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    # Raises (never returns an error) so it resolves before body validation.
    # config.API_KEY is read here, at call time. Neither key is logged or echoed.
    configured = config.API_KEY
    if not configured:  # fail-closed: no key configured means nothing gets in
        raise HTTPException(status_code=503, detail="Endpoint is not configured.")
    supplied = x_api_key or ""
    if not secrets.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


async def authenticate_triage_post(request: Request, call_next):
    # FastAPI parses the JSON syntax of a body before it resolves dependencies, so
    # on its own the dependency lets a malformed body answer 422/400 to a caller
    # with no valid key. This runs first, reads headers only, and calls the same
    # require_api_key, so the two checks cannot disagree.
    if request.method == "POST" and request.url.path.rstrip("/") == "/triage":
        try:
            require_api_key(request.headers.get("x-api-key"))
        except HTTPException as exc:  # middleware sits outside the exception handlers
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)
