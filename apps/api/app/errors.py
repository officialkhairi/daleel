"""Every error leaves the API as an ErrorEnvelope. Stack traces are logged, never returned."""

import logging
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AppError(Exception):
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    retryable: bool = False

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(code=self.code, message=self.message, retryable=self.retryable)


class Unauthorized(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"


class Forbidden(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"


class NotFound(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"


class Gone(AppError):
    status_code = HTTPStatus.GONE
    code = "gone"


class ServiceUnavailable(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"
    retryable = True


def _respond(
    status: int, envelope: ErrorEnvelope, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope.model_dump(), headers=headers)


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthorized) else None
    return _respond(exc.status_code, exc.envelope(), headers)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = HTTPStatus(exc.status_code)
    code = status.phrase.lower().replace(" ", "_").replace("-", "_")
    message = exc.detail if isinstance(exc.detail, str) else status.phrase
    return _respond(exc.status_code, ErrorEnvelope(code=code, message=message), exc.headers)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = ", ".join(".".join(str(p) for p in err["loc"]) for err in exc.errors())
    return _respond(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorEnvelope(code="validation_error", message=f"Invalid request: {fields}"),
    )


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return _respond(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        ErrorEnvelope(code="internal_error", message="Something went wrong.", retryable=True),
    )


def install_error_handlers(app: FastAPI) -> None:
    # Starlette types handlers as taking `Exception`; each one only ever receives its own type.
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled)
