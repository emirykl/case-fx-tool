from __future__ import annotations

from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from .client import FrankfurterClient
from .models import ConversionResponse, RateQuote


CacheKey = Tuple[str, str, Optional[date]]


class RateCache:
    """A bounded in-memory LRU cache for validated quotes."""

    def __init__(self, max_size: int = 512) -> None:
        self._max_size = max_size
        self._values: OrderedDict[CacheKey, RateQuote] = OrderedDict()

    def get(self, key: CacheKey) -> Optional[RateQuote]:
        value = self._values.get(key)
        if value is not None:
            self._values.move_to_end(key)
        return value

    def put(self, key: CacheKey, value: RateQuote) -> None:
        self._values[key] = value
        self._values.move_to_end(key)
        if len(self._values) > self._max_size:
            self._values.popitem(last=False)


class ConversionService:
    def __init__(self, client: FrankfurterClient, cache: Optional[RateCache] = None) -> None:
        self._client = client
        self._cache = cache or RateCache()

    async def convert(
        self,
        amount: Decimal,
        base: str,
        target: str,
        requested_date: Optional[date],
    ) -> ConversionResponse:
        key = (base, target, requested_date)
        quote = self._cache.get(key)
        if quote is None:
            quote = await self._client.fetch_rate(base, target, requested_date)
            self._cache.put(key, quote)

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

