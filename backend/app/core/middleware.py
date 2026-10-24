from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("buywise.request")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        if not rid.replace("-", "").isalnum() or len(rid) > 64:
            rid = uuid.uuid4().hex[:16]
        request.state.request_id = rid
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
            response = JSONResponse({"error": {"code": "internal_error", "message": "Unexpected server error.",
                                               "request_id": rid}}, status_code=500)
        response.headers["X-Request-ID"] = rid
        log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                 (time.monotonic() - start) * 1000, rid)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-client-IP limit for /api routes (in-memory; per process)."""

    def __init__(self, app, per_minute: int) -> None:  # noqa: ANN001
        super().__init__(app)
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        if self.per_minute > 0 and request.url.path.startswith("/api") and request.url.path != "/api/health":
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests. Please slow down."}},
                                    status_code=429, headers={"Retry-After": str(int(60 - (now - q[0])) + 1)})
            q.append(now)
        return await call_next(request)
