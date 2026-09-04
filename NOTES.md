# Notes

## Decisions

I optimized for “no answer is better than a wrong answer.” A weekend or holiday
request may use the earlier working-day rate returned by Frankfurter, but the
response always distinguishes `asked_date` from the upstream's real
`rate_date`. I do not retry with `latest` when a historical query has no data.

Money is parsed and calculated with `Decimal`. Inputs are deliberately narrow:
positive conventional decimals with two fraction digits at most. Only the final
result is rounded. A bounded in-process LRU cache keeps the solution small while
ensuring a repeated pair/date does not call the upstream again. The two keys are
not equally durable: a dated rate is permanent, so it is cached indefinitely,
while `latest` expires after 60 seconds. Without that split a long-running
process would answer "what is the rate now" with a rate from a previous day.

Frankfurter returns `404` both for a currency it does not know and for a date it
has no observation for. Collapsing the two would tell an agent to retry other
dates for a code that will never exist, so the service resolves the ambiguity
against `/v1/currencies` once per process. The lookup only happens on a 404, so
the happy path never pays for it, and if the lookup itself fails or comes back
unusable the answer stays the more conservative `rate_not_available`.

## With another day

I would add request coalescing so simultaneous identical cache misses share one
upstream call, structured metrics, and a response-size guard. In a multi-worker
deployment I would evaluate a shared cache, but would first measure whether the
added operational dependency is justified.

## AI tools

I used Codex to inspect the brief, challenge edge-case decisions, and implement
the service and tests. I then ran a second pass with Claude Code, deliberately
as a reviewer rather than an author: it ran the service against a local fake
upstream and probed the cases below. I verified every finding myself before
changing anything, and used the official Frankfurter documentation to confirm
the upstream contract, including the response date and Decimal guidance.

## Two things the AI got wrong

**A cache entry that was correct and still went stale.** The first
implementation cached every quote forever. That is right for a dated rate and
wrong for `latest`: after a day the service kept returning the previous day's
number. It was never mislabelled — `rate_date` stayed honest — but an agent
asking "what is the rate now" would have been told something old. Reproduced by
moving the fake upstream to a new day and re-asking. Fixed with a 60-second TTL
on the `latest` key only.

**A documented error code that could never fire.** `unsupported_currency` was
mapped to upstream `400`/`422`, but the real API answers `404` for an unknown
code — the same status it uses for a date it has no rate for. So an unknown
currency surfaced as `rate_not_available`, telling an agent to retry other dates
for a code that will never exist. Confirmed against the live API before
changing anything. Fixed by resolving the ambiguity against `/v1/currencies`.

Earlier, the first offline test run had also caught the response field being
serialised as `from_` instead of `from`: the generated code used Pydantic v1's
class-based alias settings while the pinned dependency resolves to v2. Replaced
with `ConfigDict` and `Field(alias="from")`.
