from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.middleware import RateLimitMiddleware, RequestIdMiddleware
from app.database.session import SessionLocal
from app.providers.registry import ProviderRegistry
from app.regret.service import RegretService
from app.services.catalog import CatalogService
from app.workers.scheduler import RefreshScheduler


BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    """Apply Alembic migrations (equivalent to `alembic upgrade head`)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


def create_app(settings: Settings | None = None, registry: ProviderRegistry | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # never log provider query strings (they can contain API keys)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        reg = app.state.registry
        if settings.auto_migrate:
            run_migrations()
        with SessionLocal() as db:
            reg.ensure_rows(db)
            try:
                from app.services.ingest import repair_store_offers
                repair_store_offers(db)
            except Exception:  # noqa: BLE001 – a repair problem must never stop the app
                logging.getLogger(__name__).exception("store-offer repair failed")
                db.rollback()
        app.state.scheduler.start()
        yield
        await app.state.scheduler.stop()
        await reg.aclose()

    app = FastAPI(title="BuyWise API", version="1.0.0", lifespan=lifespan,
                  description="Electronics price comparison for India. Prices come only from configured provider APIs.")
    reg = registry or ProviderRegistry(settings)
    app.state.settings = settings
    app.state.registry = reg
    app.state.catalog = CatalogService(settings, reg)
    app.state.regret = RegretService(app.state.catalog)
    app.state.scheduler = RefreshScheduler(app.state.catalog, app.state.regret)

    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_minute)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-Client-Id", "X-BuyWise-Demo", "Authorization", "X-Request-ID"],
                       expose_headers=["X-Request-ID"])
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse({"error": {**detail, "request_id": getattr(request.state, "request_id", None)}},
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Invalid request parameters.", "details": errs,
                                       "request_id": getattr(request.state, "request_id", None)}}, status_code=422)

    from app.api.routes import router
    app.include_router(router)
    from app.api.purchases import router as purchases_router
    app.include_router(purchases_router)
    from app.api.assistant import router as assistant_router
    app.include_router(assistant_router)
    from app.reviews.api import router as reviews_router
    app.include_router(reviews_router)
    from app.api.compare import router as compare_router
    app.include_router(compare_router)
    mount_frontend(app)
    return app


FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


def mount_frontend(app: FastAPI) -> None:
    """Serve the built website (frontend/dist) from the backend, so no Node.js is needed to use BuyWise.

    API routes keep priority; any other path returns index.html so the React router can handle it.
    """
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):  # noqa: ANN202
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
            return JSONResponse({"error": {"code": "not_found", "message": "Not found."}}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
