"""AI shopping assistant endpoint. Keys are read server-side only; replies are grounded on BuyWise's own data."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes import demo_on, http_error
from app.assistant import service
from app.database.session import get_db
from app.models import Product

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=40)
    product_id: int | None = Field(None, ge=1)


@router.get("/assistant/status")
def assistant_status(request: Request) -> dict:
    s = request.app.state.settings
    which = service.provider(s)
    return {"configured": which is not None, "provider": which,
            "model": (s.gemini_model if which == "gemini" else s.anthropic_model if which == "anthropic" else None)}


@router.post("/assistant/chat")
async def assistant_chat(body: ChatIn, request: Request, db: Session = Depends(get_db)) -> dict:
    cat = request.app.state.catalog
    context = ""
    if body.product_id:
        p = db.get(Product, body.product_id)
        if p is not None:
            demo = demo_on(request)
            context = service.product_context(cat.product_detail(db, p, demo=demo), cat.history(db, p, "365d", demo=demo))
    try:
        res = await service.ask(cat.settings, [m.model_dump() for m in body.messages], context)
    except service.AssistantError as e:
        raise http_error(e.status, e.code, e.message) from None
    return {**res, "grounded_on_product": bool(context)}
