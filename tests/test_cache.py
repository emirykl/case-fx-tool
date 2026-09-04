"""Caching policy: a dated rate is permanent, `latest` is not."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import List, Optional

from fx_tool.errors import ServiceError
from fx_tool.models import RateQuote
from fx_tool.service import ConversionService, RateCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingClient:
    """Stands in for FrankfurterClient and reports one quote per call.

    A `ServiceError` in the queue is raised instead of returned, which is how
    the real client reports an upstream failure.
    """

    def __init__(self, quotes: List[object]) -> None:
        self._quotes = list(quotes)
        self.calls = 0

    async def fetch_rate(
        self, base: str, target: str, requested_date: Optional[date]
    ) -> RateQuote:
        self.calls += 1
        answer = self._quotes.pop(0)
        if isinstance(answer, ServiceError):
            raise answer
        assert isinstance(answer, RateQuote)
        return answer


def quote(rate: str, day: str) -> RateQuote:
    return RateQuote(rate=Decimal(rate), rate_date=date.fromisoformat(day))


def build_service(client: RecordingClient, clock: FakeClock) -> ConversionService:
    return ConversionService(
        client, cache=RateCache(clock=clock), latest_ttl_seconds=60.0
    )


def test_latest_is_refetched_once_the_ttl_expires() -> None:
    clock = FakeClock()
    client = RecordingClient([quote("47.5", "2026-09-04"), quote("99.0", "2026-09-05")])
    service = build_service(client, clock)

    async def scenario() -> None:
        first = await service.convert(Decimal("1"), "EUR", "TRY", None)
        clock.advance(59.0)
        cached = await service.convert(Decimal("1"), "EUR", "TRY", None)
        clock.advance(2.0)
        refreshed = await service.convert(Decimal("1"), "EUR", "TRY", None)

        assert first.rate_date == date(2026, 9, 4)
        assert cached.rate_date == date(2026, 9, 4)
        assert refreshed.rate_date == date(2026, 9, 5)
        assert refreshed.rate == Decimal("99.0")
        assert client.calls == 2

    asyncio.run(scenario())


def test_dated_quotes_never_expire() -> None:
    clock = FakeClock()
    client = RecordingClient([quote("47.1234", "2026-08-28")])
    service = build_service(client, clock)
    asked = date(2026, 8, 28)

    async def scenario() -> None:
        await service.convert(Decimal("1"), "EUR", "TRY", asked)
        clock.advance(86_400.0)
        again = await service.convert(Decimal("1"), "EUR", "TRY", asked)

        assert again.rate == Decimal("47.1234")
        assert client.calls == 1

    asyncio.run(scenario())


def test_a_failed_fetch_is_not_cached() -> None:
    clock = FakeClock()
    client = RecordingClient(
        [ServiceError(503, "upstream_unavailable", "down"), quote("47.5", "2026-09-04")]
    )
    service = build_service(client, clock)

    async def scenario() -> None:
        try:
            await service.convert(Decimal("1"), "EUR", "TRY", None)
        except ServiceError as exc:
            assert exc.code == "upstream_unavailable"
        else:
            raise AssertionError("the failure should have propagated")

        recovered = await service.convert(Decimal("1"), "EUR", "TRY", None)

        assert recovered.rate == Decimal("47.5")
        assert client.calls == 2

    asyncio.run(scenario())


def test_cache_evicts_the_least_recently_used_entry() -> None:
    cache = RateCache(max_size=2, clock=FakeClock())
    first = ("EUR", "TRY", date(2026, 8, 26))
    second = ("EUR", "TRY", date(2026, 8, 27))
    third = ("EUR", "TRY", date(2026, 8, 28))
    for key in (first, second):
        cache.put(key, quote("1.0", "2026-08-28"))

    cache.get(first)  # first is now the most recently used
    cache.put(third, quote("1.0", "2026-08-28"))

    assert cache.get(second) is None
    assert cache.get(first) is not None
    assert cache.get(third) is not None
