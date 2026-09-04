from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator, Callable, List

import httpx

from fx_tool.app import create_app


def upstream_response(
    *, date: str = "2026-08-28", base: str = "EUR", target: str = "TRY", rate=47.1234
) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps({"amount": 1.0, "base": base, "date": date, "rates": {target: rate}}),
        headers={"content-type": "application/json"},
    )


@asynccontextmanager
async def api_client(
    handler: Callable[[httpx.Request], httpx.Response]
) -> AsyncIterator[httpx.AsyncClient]:
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(upstream)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    await upstream.aclose()


def run(coro):
    return asyncio.run(coro)


def test_success_uses_decimal_math_and_actual_rate_date(monkeypatch) -> None:
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://fake-upstream")
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return upstream_response(date="2026-08-28", rate=47.1234)

    async def scenario() -> None:
        async with api_client(handler) as client:
            response = await client.get(
                "/tools/convert",
                params={"amount": "250", "from": "eur", "to": "try", "date": "2026-08-30"},
            )
        assert response.status_code == 200
        assert response.json() == {
            "amount": 250.0,
            "from": "EUR",
            "to": "TRY",
            "rate": 47.1234,
            "result": 11780.85,
            "rate_date": "2026-08-28",
            "asked_date": "2026-08-30",
            "source": "ECB via frankfurter.dev",
        }
        assert len(seen) == 1
        assert seen[0].url.path == "/v1/2026-08-30"
        assert dict(seen[0].url.params) == {"base": "EUR", "symbols": "TRY"}

    run(scenario())


def test_latest_request_has_null_asked_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/latest"
        return upstream_response()

    async def scenario() -> None:
        async with api_client(handler) as client:
            response = await client.get("/tools/convert?amount=1")
        assert response.status_code == 200
        assert response.json()["asked_date"] is None
        assert response.json()["rate_date"] == "2026-08-28"

    run(scenario())


def test_repeated_rate_question_uses_cache() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return upstream_response(date=_request.url.path.rsplit("/", 1)[-1])

    async def scenario() -> None:
        async with api_client(handler) as client:
            first = await client.get("/tools/convert?amount=2&date=2026-08-28")
            second = await client.get("/tools/convert?amount=3&date=2026-08-28")
            different_date = await client.get("/tools/convert?amount=3&date=2026-08-27")
        assert first.status_code == second.status_code == different_date.status_code == 200
        assert first.json()["result"] == 94.25
        assert second.json()["result"] == 141.37
        assert calls == 2

    run(scenario())


def test_invalid_inputs_never_call_upstream() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called")

    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    cases = [
        ("/tools/convert", "invalid_amount"),
        ("/tools/convert?amount=0", "invalid_amount"),
        ("/tools/convert?amount=-1", "invalid_amount"),
        ("/tools/convert?amount=1.001", "invalid_amount"),
        ("/tools/convert?amount=NaN", "invalid_amount"),
        ("/tools/convert?amount=1e2", "invalid_amount"),
        ("/tools/convert?amount=1000000000001", "invalid_amount"),
        ("/tools/convert?amount=1&from=EU", "invalid_currency"),
        ("/tools/convert?amount=1&from=TRY&to=try", "same_currency"),
        ("/tools/convert?amount=1&date=28-08-2026", "invalid_date"),
        (f"/tools/convert?amount=1&date={future}", "invalid_date"),
    ]

    async def scenario() -> None:
        async with api_client(handler) as client:
            for url, error in cases:
                response = await client.get(url)
                assert response.status_code == 422, url
                assert set(response.json()) == {"error", "message"}
                assert response.json()["error"] == error

    run(scenario())


def test_upstream_failures_have_safe_consistent_errors() -> None:
    responses = [
        (httpx.Response(404, json={"message": "not found"}), 404, "rate_not_available"),
        (httpx.Response(422, json={"message": "bad currency"}), 422, "unsupported_currency"),
        (httpx.Response(500, text="secret details"), 502, "upstream_error"),
        (httpx.Response(200, text="<html>bad</html>"), 502, "invalid_upstream_response"),
        (httpx.Response(200, json={"date": "2026-08-28", "base": "EUR", "rates": {}}), 502, "invalid_upstream_response"),
        (upstream_response(base="USD"), 502, "invalid_upstream_response"),
        (upstream_response(date="2026-08-31"), 502, "invalid_upstream_response"),
        (upstream_response(rate=-1), 502, "invalid_upstream_response"),
    ]

    async def scenario() -> None:
        for upstream_response_value, status, error in responses:
            async with api_client(lambda _request, value=upstream_response_value: value) as client:
                response = await client.get(
                    "/tools/convert?amount=1&date=2026-08-30"
                )
            assert response.status_code == status
            assert response.json()["error"] == error
            assert set(response.json()) == {"error", "message"}
            assert "secret" not in response.text

    run(scenario())


def test_unknown_currency_is_told_apart_from_a_missing_observation() -> None:
    """The upstream answers 404 for both, so the service asks which one it was."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/currencies":
            return httpx.Response(200, json={"EUR": "Euro", "TRY": "Turkish Lira"})
        return httpx.Response(404, json={"message": "not found"})

    async def scenario() -> None:
        async with api_client(handler) as client:
            unknown = await client.get("/tools/convert?amount=1&to=ZZZ")
            missing = await client.get("/tools/convert?amount=1&date=1998-01-01")
        assert unknown.status_code == 422
        assert unknown.json()["error"] == "unsupported_currency"
        assert missing.status_code == 404
        assert missing.json()["error"] == "rate_not_available"

    run(scenario())


def test_an_unusable_currency_list_never_upgrades_the_error() -> None:
    """An empty or broken list must not mark every currency as unsupported."""
    unusable = [
        httpx.Response(500, text="down"),
        httpx.Response(200, text="<html>bad</html>"),
        httpx.Response(200, json={}),
        httpx.Response(200, json=["EUR", "TRY"]),
    ]

    async def scenario() -> None:
        for currencies in unusable:
            def handler(
                request: httpx.Request, value=currencies
            ) -> httpx.Response:
                if request.url.path == "/v1/currencies":
                    return value
                return httpx.Response(404, json={"message": "not found"})

            async with api_client(handler) as client:
                response = await client.get("/tools/convert?amount=1&to=ZZZ")
            assert response.status_code == 404
            assert response.json()["error"] == "rate_not_available"

    run(scenario())


def test_timeout_and_connection_errors_are_distinct() -> None:
    errors = [
        (httpx.ReadTimeout("slow"), "upstream_timeout"),
        (httpx.ConnectError("closed"), "upstream_unavailable"),
    ]

    async def scenario() -> None:
        for raised, expected in errors:
            def handler(request: httpx.Request, error=raised) -> httpx.Response:
                error.request = request
                raise error

            async with api_client(handler) as client:
                response = await client.get("/tools/convert?amount=1")
            assert response.status_code == 503
            assert response.json()["error"] == expected

    run(scenario())


def test_environment_base_is_read_at_startup(monkeypatch) -> None:
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://review-fake/base/")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("http://review-fake/base/v1/latest?")
        return upstream_response()

    async def scenario() -> None:
        async with api_client(handler) as client:
            response = await client.get("/tools/convert?amount=1")
        assert response.status_code == 200

    run(scenario())
