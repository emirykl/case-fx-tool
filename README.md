# FX tool

A small HTTP tool that converts currencies with ECB reference rates from the
[Frankfurter v1 API](https://frankfurter.dev/v1/). It favors an explicit error
over a plausible but incorrect financial result.

## Run

Python 3.9 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

The service listens on `PORT` (default `8080`). It reads the upstream root from
`FX_UPSTREAM_BASE` (default `https://api.frankfurter.dev`), which makes it easy
to replace Frankfurter with a local fake:

```bash
PORT=9000 FX_UPSTREAM_BASE=http://localhost:9001 ./run.sh
```

## Use

```bash
curl 'http://localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28'
```

Example response:

```json
{
  "amount": 250,
  "from": "EUR",
  "to": "TRY",
  "rate": 47.1234,
  "result": 11780.85,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

`from` defaults to `EUR`, `to` defaults to `TRY`, and `date` is optional. With
no date the service requests Frankfurter's latest published rate and returns
`asked_date: null`.

### Decisions and edge cases

- **Weekends and ECB holidays:** Frankfurter may answer a dated request with the
  previous working day's rate. The service uses the response's actual date as
  `rate_date` and preserves the caller's date as `asked_date`; it never labels
  an older rate as belonging to the requested date.
- **Future or malformed dates:** rejected before contacting the upstream.
- **Dates before the available series:** return `rate_not_available` when the
  upstream reports no rate. There is no silent fallback to `latest`.
- **Currencies:** codes must contain exactly three ASCII letters and are
  normalized to uppercase. Unsupported codes and identical source/target codes
  are rejected.
- **Amounts:** required, greater than zero, at most `1000000000000`, and at most
  two decimal places. Scientific notation, `NaN`, and infinity are rejected.
- **Precision:** rates and amounts are parsed as decimal values. The rate is not
  rounded before multiplication; only the final result is rounded to two
  decimal places with `ROUND_HALF_UP`.
- **Upstream failures:** connection failures, timeouts, non-JSON bodies, error
  statuses, mismatched currencies, impossible dates, and malformed rates become
  explicit non-2xx errors. Upstream bodies and exception details are not exposed.
- **Caching:** a bounded in-memory LRU cache stores only validated successful
  quotes by `(from, to, asked_date)`. Amount is not part of the key because the
  conversion is calculated locally. The cache is per process and resets on
  restart.

Calculations use Decimal internally; values are converted to JSON numbers only
at the response boundary to match the endpoint contract.

## Errors

Every error response has the same shape:

```json
{"error": "invalid_amount", "message": "Amount must be greater than zero."}
```

| HTTP | Code | Meaning |
|---:|---|---|
| 422 | `invalid_request` | FastAPI could not parse the request structure. |
| 422 | `invalid_amount` | Amount is missing or violates the amount policy. |
| 422 | `invalid_currency` | A currency code is not three ASCII letters. |
| 422 | `unsupported_currency` | Frankfurter does not support a currency. |
| 422 | `same_currency` | Source and target currencies are identical. |
| 422 | `invalid_date` | Date is malformed or in the future. |
| 404 | `rate_not_available` | No rate exists for the pair/date. |
| 503 | `upstream_timeout` | The provider exceeded the configured timeout. |
| 503 | `upstream_unavailable` | The provider could not be reached. |
| 502 | `upstream_error` | The provider returned an HTTP error. |
| 502 | `invalid_upstream_response` | The provider returned unusable or unsafe data. |
| 500 | `internal_error` | An unexpected internal failure occurred. |

## Test

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
./test.sh
```

Tests use `httpx.MockTransport`; they never contact the internet. To reproduce
the review environment:

```bash
FX_UPSTREAM_BASE=http://127.0.0.1:1 ./test.sh
```
