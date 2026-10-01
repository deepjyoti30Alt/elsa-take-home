"""Request correlation middleware for structured logs."""

from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from quiz_api.observability import REQUEST_COUNT, REQUEST_DURATION, tracer

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a safe correlation ID to request logs and responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Log request completion without exposing query strings or secrets."""
        request_id = get_request_id(request.headers.get("X-Request-ID"))
        started_at = perf_counter()
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        logger.info("request_started", method=request.method, path=request.url.path)

        try:
            with tracer.start_as_current_span("http.request") as span:
                span.set_attribute("http.request.method", request.method)
                span.set_attribute("url.path", request.url.path)
                response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(method=request.method, path=request.url.path, status="500").inc()
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
            )
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            duration_seconds = perf_counter() - started_at
            REQUEST_COUNT.labels(
                method=request.method,
                path=request.url.path,
                status=str(response.status_code),
            ).inc()
            REQUEST_DURATION.labels(
                method=request.method,
                path=request.url.path,
            ).observe(duration_seconds)
            logger.info(
                "request_completed",
                duration_ms=round(duration_seconds * 1000, 2),
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()


def get_request_id(request_id: str | None) -> str:
    """Return a client correlation ID only when it is safe to log and echo."""
    if request_id is not None and 1 <= len(request_id) <= 128 and request_id.isprintable():
        return request_id
    return str(uuid4())
