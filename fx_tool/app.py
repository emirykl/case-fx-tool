from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .client import FrankfurterClient
from .errors import ServiceError
from .models import ConversionResponse, ErrorResponse
from .service import ConversionService
from .validation import (
    parse_amount,
    parse_currency,
    parse_requested_date,
    validate_pair,
)


logger = logging.getLogger(__name__)
DEFAULT_UPSTREAM_BASE = "https://api.frankfurter.dev"

# Routing errors are answered in the same envelope as everything else, so a
# caller never has to parse two different error shapes. The framework's own
# detail text is replaced rather than forwarded.
ROUTING_ERRORS = {
    404: ("not_found", "The requested endpoint does not exist."),
    405: ("method_not_allowed", "The requested method is not allowed here."),
}


def error_response(error: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.code, "message": error.message},
    )


def create_app(http_client: Optional[httpx.AsyncClient] = None) -> FastAPI:
    owns_client = http_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
        )
        upstream_base = os.getenv("FX_UPSTREAM_BASE", DEFAULT_UPSTREAM_BASE)
        app.state.conversion_service = ConversionService(
            FrankfurterClient(client, upstream_base)
        )
        try:
            yield
        finally:
            if owns_client:
                await client.aclose()

    app = FastAPI(title="fx-tool", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            ServiceError(422, "invalid_request", "The request parameters are invalid.")
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_routing_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code, message = ROUTING_ERRORS.get(
            exc.status_code, ("request_failed", "The request could not be handled.")
        )
        return error_response(ServiceError(exc.status_code, code, message))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected conversion service failure", exc_info=exc)
        return error_response(
            ServiceError(500, "internal_error", "The service could not complete the request.")
        )

    @app.get(
        "/tools/convert",
        response_model=ConversionResponse,
        response_model_by_alias=True,
        responses={
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def convert(
        request: Request,
        amount: Optional[str] = Query(default=None),
        from_: str = Query(default="EUR", alias="from"),
        to: str = Query(default="TRY"),
        on: Optional[str] = Query(default=None, alias="date"),
    ) -> ConversionResponse:
        parsed_amount = parse_amount(amount)
        base = parse_currency(from_, "from")
        target = parse_currency(to, "to")
        validate_pair(base, target)
        requested_date = parse_requested_date(on)
        service: ConversionService = request.app.state.conversion_service
        return await service.convert(parsed_amount, base, target, requested_date)

    return app


app = create_app()
