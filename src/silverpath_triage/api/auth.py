import secrets

from fastapi import Header, HTTPException

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
