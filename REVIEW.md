# Review of `tool.py`

Findings are ranked by customer harm, not style severity.

## 1. `from` and `date` are silently ignored on every request

The endpoint declares `from_` and `on`, so the documented call
`?amount=250&from=USD&to=EUR&date=2026-08-28` never reaches the parameters it
was meant to. `from` falls back to its `EUR` default and `date` is dropped, so
the service converts the wrong currency using today's rate — and labels it with
the requested date. Nothing in the response reveals the substitution: the status
is 200 and the number is plausible. A customer asking to convert dollars is
quoted euros.

**Verify:** call `?amount=250&from=USD&to=EUR&date=2026-08-28` and read
`from` in the response; it comes back `EUR`. `GET /openapi.json` confirms the
parameter names as `amount, from_, to, on`. The fix is
`Query(alias="from")` and `Query(alias="date")`, plus a test that asserts the
upstream was called with the currency the caller actually asked for.

## 2. The cache can return a real rate for the wrong date

The cache key is only `base-target`, so the first rate fetched for a currency
pair is reused for every historical and latest request. Worse, the cached path
labels that rate with the newly requested date instead of the date returned by
Frankfurter. A customer can therefore receive a credible-looking but incorrect
number and date—the most dangerous outcome for a financial tool.

**Verify:** fake the upstream with distinct EUR/TRY rates for two dates, request
both dates in sequence, and assert the second response has its own rate and the
upstream's actual date. The current implementation returns the first rate and
labels it as the second date.

## 3. Failures become HTTP 200 responses containing a zero exchange rate

A broad `except Exception` converts timeouts, 500s, invalid JSON, programming
errors, and missing currencies into a normal-looking response with `rate: 0.0`.
An agent cannot distinguish “the provider is down” from a valid conversion and
may tell a paying customer that their money is worth zero.

**Verify:** point the client at a closed port, and separately return HTTP 500 and
HTML. Each request currently returns 200 and a zero result instead of a stable
non-2xx error.

## 4. The fallback and returned date hide which observation was used

When a requested date has no target rate, the code silently requests `latest`.
It then returns `str(on or date.today())`, never the upstream payload's `date`.
For weekends, holidays, pre-series dates, or malformed payloads, a customer may
be shown a current rate as though it belonged to a historical date.

**Verify:** have the fake dated endpoint omit the target and have `/latest`
return a known older/different `date`. Assert `rate_date` equals that payload
date and `asked_date` remains the requested date. The current response reports
the requested date and has no `asked_date` field.

## 5. Rounding the rate before multiplication changes customer totals

The code rounds the exchange rate to two decimals before multiplying. FX rates
often need four or more decimal places; at larger amounts this creates material
errors. For example, `250 * 47.1234` is `11780.85`, while using `47.12` produces
`11780.00`.

**Verify:** return `47.1234` from the fake upstream for an amount of 250 and
compare the output against Decimal multiplication with only the final monetary
result rounded.

## The one I would fix before shipping tonight

Finding 1, the two aliases. It is the smallest change in the file and the only
defect that corrupts every single request made through the documented contract —
including the example in our own docs — while looking completely healthy from
the outside. Finding 2 is the one I would fix immediately after: store
`(rate, actual_rate_date)` under a key that includes base, target and requested
date, and only insert into the cache after the upstream response is fully
validated.

## Things that look suspicious but are fine

- An in-process cache is reasonable for this deliberately small service; a
  database or Redis would add complexity the brief does not require. Its key,
  value, and size policy are the actual problems.
- `httpx.AsyncClient` is appropriate in an async FastAPI service and provides
  connection pooling. It should be created/closed through application lifespan,
  but choosing an async shared client is not itself a defect.
- Returning a previous working-day rate for a weekend can be valid if the policy
  is explicit and both the asked date and actual rate date are returned. The
  silent, incorrectly dated fallback—not the idea of a prior rate—is the defect.
