from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import FrozenSet, Optional

import httpx

from .errors import (
    ServiceError,
    invalid_upstream_response,
    rate_not_available,
    unsupported_currency,
    upstream_error,
)
from .models import RateQuote


class FrankfurterClient:
    def __init__(self, http_client: httpx.AsyncClient, upstream_base: str) -> None:
        self._http_client = http_client
        self._upstream_base = upstream_base.rstrip("/")
        self._supported_codes: Optional[FrozenSet[str]] = None

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
            raise unsupported_currency()
        if response.status_code == 404:
            raise await self._explain_not_found(base, target)
        if response.status_code >= 500:
            raise upstream_error("The exchange-rate provider returned an error.")
        if not 200 <= response.status_code < 300:
            raise upstream_error(
                "The exchange-rate provider returned an unexpected response."
            )

        try:
            payload = json.loads(response.content, parse_float=Decimal)
            rate_date = date.fromisoformat(payload["date"])
            returned_base = payload["base"]
            rate = Decimal(str(payload["rates"][target]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise invalid_upstream_response() from exc

        if returned_base != base or not rate.is_finite() or rate <= 0:
            raise invalid_upstream_response()
        if requested_date is not None and rate_date > requested_date:
            raise invalid_upstream_response(
                "The exchange-rate provider returned a rate from a later date."
            )
        return RateQuote(rate=rate, rate_date=rate_date)

    async def _explain_not_found(self, base: str, target: str) -> ServiceError:
        """Frankfurter answers 404 both for a currency it does not know and for
        a date it has no observation for. The caller needs to tell them apart:
        an unknown code is worth reporting, another date is worth retrying."""
        supported = await self._load_supported_codes()
        if supported is not None and not supported.issuperset({base, target}):
            return unsupported_currency()
        return rate_not_available()

    async def _load_supported_codes(self) -> Optional[FrozenSet[str]]:
        """The supported list changes very rarely, so one successful lookup per
        process is enough. `None` means the list is unusable — a failed lookup
        is not cached and never fails the request; it only leaves the cause of
        the 404 undetermined."""
        if self._supported_codes is not None:
            return self._supported_codes
        try:
            response = await self._http_client.get(
                f"{self._upstream_base}/v1/currencies"
            )
            if not 200 <= response.status_code < 300:
                return None
            payload = json.loads(response.content)
        except (httpx.RequestError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        codes = frozenset(code.upper() for code in payload if isinstance(code, str))
        if not codes:
            # An empty list would mark every currency as unsupported.
            return None
        self._supported_codes = codes
        return codes
