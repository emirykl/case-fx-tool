from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

import httpx

from .errors import ServiceError
from .models import RateQuote


class FrankfurterClient:
    def __init__(self, http_client: httpx.AsyncClient, upstream_base: str) -> None:
        self._http_client = http_client
        self._upstream_base = upstream_base.rstrip("/")

    async def fetch_rate(
        self, base: str, target: str, requested_date: Optional[date]
    ) -> RateQuote:
        period = requested_date.isoformat() if requested_date else "latest"
        url = f"{self._upstream_base}/v1/{period}"
        try:
            response = await self._http_client.get(
                url,
                params={"base": base, "symbols": target},
            )
        except httpx.TimeoutException as exc:
            raise ServiceError(
                503,
                "upstream_timeout",
                "The exchange-rate provider did not respond in time.",
            ) from exc
        except httpx.RequestError as exc:
            raise ServiceError(
                503,
                "upstream_unavailable",
                "The exchange-rate provider is temporarily unavailable.",
            ) from exc

        if response.status_code in (400, 422):
            raise ServiceError(
                422,
                "unsupported_currency",
                "One or both currency codes are not supported.",
            )
        if response.status_code == 404:
            raise ServiceError(
                404,
                "rate_not_available",
                "No exchange rate is available for the requested currencies and date.",
            )
        if response.status_code >= 500:
            raise ServiceError(
                502,
                "upstream_error",
                "The exchange-rate provider returned an error.",
            )
        if not 200 <= response.status_code < 300:
            raise ServiceError(
                502,
                "upstream_error",
                "The exchange-rate provider returned an unexpected response.",
            )

        try:
            payload = json.loads(response.content, parse_float=Decimal)
            rate_date = date.fromisoformat(payload["date"])
            returned_base = payload["base"]
            rate = Decimal(str(payload["rates"][target]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ServiceError(
                502,
                "invalid_upstream_response",
                "The exchange-rate provider returned invalid data.",
            ) from exc

        if returned_base != base or not rate.is_finite() or rate <= 0:
            raise ServiceError(
                502,
                "invalid_upstream_response",
                "The exchange-rate provider returned invalid data.",
            )
        if requested_date is not None and rate_date > requested_date:
            raise ServiceError(
                502,
                "invalid_upstream_response",
                "The exchange-rate provider returned a rate from a later date.",
            )
        return RateQuote(rate=rate, rate_date=rate_date)

