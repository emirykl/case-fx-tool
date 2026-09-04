from __future__ import annotations

import time
from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, NamedTuple, Optional, Tuple

from .client import FrankfurterClient
from .models import ConversionResponse, RateQuote


CacheKey = Tuple[str, str, Optional[date]]

# A published rate for a past date never changes, but "latest" moves to a new
# observation every working day. Cache it briefly instead of forever.
LATEST_TTL_SECONDS = 60.0


class _Entry(NamedTuple):
    quote: RateQuote
    expires_at: Optional[float]


class RateCache:
    """A bounded in-memory LRU cache for validated quotes.

    Expiry is measured on a monotonic clock, so a wall-clock adjustment can
    neither extend nor cut short the life of an entry.
    """

    def __init__(
        self,
        max_size: int = 512,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_size = max_size
        self._clock = clock
        self._entries: OrderedDict[CacheKey, _Entry] = OrderedDict()

    def get(self, key: CacheKey) -> Optional[RateQuote]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and entry.expires_at <= self._clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry.quote

    def put(
        self, key: CacheKey, quote: RateQuote, ttl_seconds: Optional[float] = None
    ) -> None:
        expires_at = None if ttl_seconds is None else self._clock() + ttl_seconds
        self._entries[key] = _Entry(quote, expires_at)
        self._entries.move_to_end(key)
        if len(self._entries) > self._max_size:
            self._entries.popitem(last=False)


class ConversionService:
    def __init__(
        self,
        client: FrankfurterClient,
        cache: Optional[RateCache] = None,
        latest_ttl_seconds: float = LATEST_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._cache = cache if cache is not None else RateCache()
        self._latest_ttl_seconds = latest_ttl_seconds

    async def convert(
        self,
        amount: Decimal,
        base: str,
        target: str,
        requested_date: Optional[date],
    ) -> ConversionResponse:
        quote = await self._quote(base, target, requested_date)
        result = (amount * quote.rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return ConversionResponse(
            amount=amount,
            from_=base,
            to=target,
            rate=quote.rate,
            result=result,
            rate_date=quote.rate_date,
            asked_date=requested_date,
            source="ECB via frankfurter.dev",
        )

    async def _quote(
        self, base: str, target: str, requested_date: Optional[date]
    ) -> RateQuote:
        key = (base, target, requested_date)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        # A failed fetch raises before this point, so only validated quotes
        # ever enter the cache.
        quote = await self._client.fetch_rate(base, target, requested_date)
        ttl = None if requested_date is not None else self._latest_ttl_seconds
        self._cache.put(key, quote, ttl)
        return quote
