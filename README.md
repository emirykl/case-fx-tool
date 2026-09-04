# FX Tool

An HTTP service with one endpoint that converts an amount between two
currencies. Rates are European Central Bank reference rates, read from the
[Frankfurter v1 API](https://frankfurter.dev/v1/).

The caller is an agent answering a paying customer, so a wrong number costs more
than a missing one. When the service cannot establish that a result is correct,
it returns an error instead of a figure.

## Requirements

Python 3.9 or later.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | Port the service listens on. |
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` | Root URL of the rate provider. |

No upstream host is written into the code. The provider can be replaced through
`FX_UPSTREAM_BASE` alone.

## Running the service

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

With a different port and provider:

```bash
PORT=9000 FX_UPSTREAM_BASE=http://localhost:9001 ./run.sh
```

## Running the tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
./test.sh
```

The upstream is replaced by `httpx.MockTransport`, so no test opens a network
connection. The review environment can be reproduced with:

```bash
FX_UPSTREAM_BASE=http://127.0.0.1:1 ./test.sh
```

## The endpoint

```
GET /tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28
```

| Parameter | Required | Default | Notes |
|---|---|---|---|
| `amount` | Yes | | Positive decimal, at most two decimal places. |
| `from` | No | `EUR` | Three letters, normalised to uppercase. |
| `to` | No | `TRY` | Three letters, normalised to uppercase. |
| `date` | No | latest | `YYYY-MM-DD`. Without it the latest published rate is used. |

A successful call returns 200 and:

```json
{
  "amount": 250.0,
  "from": "EUR",
  "to": "TRY",
  "rate": 47.1234,
  "result": 11780.85,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

| Field | Type | Meaning |
|---|---|---|
| `amount` | number | The amount the caller sent. |
| `from` | string | Source currency code. |
| `to` | string | Target currency code. |
| `rate` | number | The rate as published upstream, not rounded. |
| `result` | number | `amount × rate`, rounded to two decimal places. |
| `rate_date` | string | The date the applied rate belongs to, taken from the upstream payload. |
| `asked_date` | string or null | The date the caller asked for, or `null` if none was given. |
| `source` | string | Attribution of the rate data. |

The two dates are separate on purpose. `rate_date` is never inferred from the
request; it is read from the upstream response. `asked_date` records what was
asked. They differ whenever the ECB published nothing for the requested day, and
the difference is what lets the caller say which day the figure belongs to.

## What the endpoint does in each case

| Case | Behaviour | Response |
|---|---|---|
| No rate published for the date (weekend, holiday) | The upstream answers with the previous working day. That rate is used, and dated as the earlier day, while `asked_date` keeps the requested one. | `200` |
| Date is in the future | Rejected before the upstream is called. | `422 invalid_date` |
| Date is malformed | The format must be `YYYY-MM-DD`. | `422 invalid_date` |
| Date is earlier than the published series | There is no quiet retry against `latest`. | `404 rate_not_available` |
| Currency code does not exist | The upstream returns 404 for an unknown code and for a date with no rate alike, so the list at `/v1/currencies` is read once to separate the two. | `422 unsupported_currency` |
| Currency code is not three ASCII letters | Checked locally. | `422 invalid_currency` |
| `from` and `to` are the same | Rejected, since there is nothing to convert. | `422 same_currency` |
| Upstream is slow | Two seconds to connect, five to read. | `503 upstream_timeout` |
| Upstream cannot be reached | Refused connection, failed DNS lookup. | `503 upstream_unavailable` |
| Upstream returns 500 | Its body is not passed on to the caller. | `502 upstream_error` |
| Upstream returns something that is not JSON | Also covers a missing rate, a base currency that does not match the request, a rate that is not a number, and a rate dated after the requested day. | `502 invalid_upstream_response` |
| `amount` is missing | The parameter is required. | `422 invalid_amount` |
| `amount` is zero or negative | It must be greater than zero. | `422 invalid_amount` |
| `amount` has ten decimal places | Two are the maximum. Scientific notation, `NaN`, infinity and values above `1000000000000` are rejected as well. | `422 invalid_amount` |

## Error codes

Every error, including an unknown path or an unsupported method, has one shape:

```json
{"error": "invalid_amount", "message": "Amount must be greater than zero."}
```

| HTTP | Code | Meaning |
|---:|---|---|
| 422 | `invalid_amount` | The amount is missing or breaks the amount rules. |
| 422 | `invalid_currency` | A currency code is not three ASCII letters. |
| 422 | `unsupported_currency` | The provider does not support one of the currencies. |
| 422 | `same_currency` | Source and target currencies are identical. |
| 422 | `invalid_date` | The date is malformed or in the future. |
| 422 | `invalid_request` | The request structure could not be parsed. |
| 404 | `rate_not_available` | No rate exists for that pair and date. |
| 404 | `not_found` | The endpoint does not exist. |
| 405 | `method_not_allowed` | The method is not allowed on this endpoint. |
| 502 | `upstream_error` | The provider returned an HTTP error. |
| 502 | `invalid_upstream_response` | The provider returned data the service cannot trust. |
| 503 | `upstream_timeout` | The provider went past the configured timeout. |
| 503 | `upstream_unavailable` | The provider could not be reached. |
| 500 | `internal_error` | An unexpected internal failure. |

Any other routing status is reported as `request_failed` in the same shape.
Upstream bodies and exception details never reach the caller; they go to the
service log.

## Precision

Amounts and rates are parsed as `Decimal`. The rate is not rounded before the
multiplication, only the final result is, to two places with `ROUND_HALF_UP`.
Rounding the rate first would turn `250 × 47.1234` from `11780.85` into
`11780.00`. Values become JSON numbers only when the response is written, which
keeps them within the contract above.

## Caching

A repeated question does not reach the upstream twice. A bounded in-process LRU
cache holds validated quotes under the key `(from, to, asked_date)`. The amount
is left out of the key because the multiplication happens locally.

The two kinds of key do not live equally long. A dated quote is kept until it is
evicted, since a rate published for a past day does not change. A `latest` quote
expires after sixty seconds; without that limit a service left running would
keep answering a question about the current rate with a previous day's figure.
The cache belongs to one process and is lost on restart.
