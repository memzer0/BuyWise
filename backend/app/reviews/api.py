"""Review-module endpoint: AI-written answers for "Ask the reviews" (see app/reviews/answer.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes import http_error
from app.database.session import get_db
from app.models import Product
from app.reviews import answer as svc

router = APIRouter(prefix="/api")


class ExcerptIn(BaseModel):
    review_id: int = Field(..., ge=0)
    text: str = Field(..., min_length=1, max_length=600)


class AskIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=200)
    excerpts: list[ExcerptIn] = Field(default_factory=list, max_length=6)
    aspects: list[str] = Field(default_factory=list, max_length=8)
    use_case: str | None = Field(None, max_length=20)


@router.post("/products/{product_id}/reviews/ask")
async def ask_reviews(product_id: int, body: AskIn, request: Request, db: Session = Depends(get_db)) -> dict:
    p = db.get(Product, product_id)
    if p is None:
        raise http_error(404, "not_found", "Product not found.")
    try:
        return await svc.answer(request.app.state.settings, product_id, p.review_data, body.question.strip(),
                                [e.model_dump() for e in body.excerpts], body.aspects, body.use_case)
    except svc.ReviewAnswerError as e:
        raise http_error(e.status, e.code, e.message) from None
