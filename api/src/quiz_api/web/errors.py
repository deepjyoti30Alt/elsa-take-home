"""Stable, correlation-aware HTTP error responses."""

from typing import Final

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)

STATUS_CODES: Final[dict[int, str]] = {
    status.HTTP_400_BAD_REQUEST: "invalid_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}
UNEXPECTED_ERROR_MESSAGE: Final[str] = "An unexpected error occurred."
VALIDATION_ERROR_MESSAGE: Final[str] = "The request contains invalid data."


class ErrorDetail(BaseModel):
    """Machine-readable and support-friendly error details."""

    code: str
    correlation_id: str
    message: str


class ErrorResponse(BaseModel):
    """Single envelope used for every API error response."""

    error: ErrorDetail


def register_exception_handlers(app: FastAPI) -> None:
    """Register the API's consistent exception-to-response mappings."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)


async def http_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    """Convert expected HTTP failures to the public error envelope."""
    if not isinstance(exception, StarletteHTTPException):
        return await unexpected_exception_handler(request, exception)
    error_code = STATUS_CODES.get(exception.status_code, "request_failed")
    message = exception.detail if isinstance(exception.detail, str) else "The request failed."
    return error_response(
        correlation_id=get_correlation_id(request),
        error_code=error_code,
        message=message,
        status_code=exception.status_code,
    )


async def validation_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    """Avoid leaking validation internals while signaling an invalid request."""
    if not isinstance(exception, RequestValidationError):
        return await unexpected_exception_handler(request, exception)
    return error_response(
        correlation_id=get_correlation_id(request),
        error_code="validation_error",
        message=VALIDATION_ERROR_MESSAGE,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def unexpected_exception_handler(request: Request, exception: Exception) -> JSONResponse:
    """Log unexpected failures and return a non-sensitive server error."""
    logger.exception("unhandled_exception", exception_type=type(exception).__name__)
    return error_response(
        correlation_id=get_correlation_id(request),
        error_code="internal_error",
        message=UNEXPECTED_ERROR_MESSAGE,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def error_response(
    *,
    correlation_id: str,
    error_code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    """Serialize a public error response with its HTTP status code."""
    payload = ErrorResponse(
        error=ErrorDetail(
            code=error_code,
            correlation_id=correlation_id,
            message=message,
        ),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def get_correlation_id(request: Request) -> str:
    """Get the ID assigned by request middleware without trusting raw headers."""
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else "unknown"
