"""Product comparison endpoint – reads stored data only, so comparing never spends provider (SerpApi) searches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.routes import catalog, demo_on, http_error
from app.database.session import get_db
from app.services import compare as svc

router = APIRouter(prefix="/api")


@router.get("/compare")
def compare_products(request: Request, ids: str = Query(..., max_length=100), db: Session = Depends(get_db)) -> dict:
    try:
        parsed = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise http_error(422, "invalid_ids", "ids must be a comma-separated list of product ids.") from None
    if not parsed:
        raise http_error(422, "invalid_ids", "Choose at least one product to compare.")
    return svc.compare(catalog(request), db, parsed, demo=demo_on(request))
