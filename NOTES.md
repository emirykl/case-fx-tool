# Notes

## Decisions

I optimized for “no answer is better than a wrong answer.” A weekend or holiday
request may use the earlier working-day rate returned by Frankfurter, but the
response always distinguishes `asked_date` from the upstream's real
`rate_date`. I do not retry with `latest` when a historical query has no data.

Money is parsed and calculated with `Decimal`. Inputs are deliberately narrow:
positive conventional decimals with two fraction digits at most. Only the final
result is rounded. A bounded in-process LRU cache keeps the solution small while
ensuring a repeated pair/date does not call the upstream again.

## With another day

I would add request coalescing so simultaneous identical cache misses share one
upstream call, short expiration for the mutable `latest` key, structured metrics,
and a response-size guard. In a multi-worker deployment I would evaluate a
shared cache, but would first measure whether the added operational dependency
is justified.

## AI tools

I used Codex to inspect the brief, challenge edge-case decisions, implement the
service and tests, and check the final repository. I reviewed the resulting code
and used the official Frankfurter documentation to verify the upstream contract,
including the response date and Decimal guidance.

## One thing the AI got wrong

The first implementation used Pydantic v1's class-based field alias settings
while the pinned dependency resolves to Pydantic v2. The first offline test run
showed the response field as `from_` instead of `from`. I replaced the deprecated
configuration with `ConfigDict` and `Field(alias="from")`, then reran the full
suite. The same run also exposed a test fixture that returned a later date for a
different historical request; I made the fake upstream date-aware rather than
weakening the production date-safety check.
