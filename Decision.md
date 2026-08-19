# Decisions

How I got here: I worked through the tradeoffs before writing any code, decided
the mechanism for each hard part, then had the model implement my design and
verified every stage against a checklist. The through-line is that correctness is
delegated to SQLite constraints and transactions rather than to application logic,
so the guarantees hold even under concurrent retries.

## Bounding the loop

I bound spend, not iterations, because cost is the actual concern. Before every
step the loop checks `total_credits(run) + step_cost > credit_budget` and stops if
it would exceed. The check is before execution, so the budget can never be
overshot: a tool call is the irreversible part, and checking afterward would only
observe the overspend. A run that stops this way ends in a distinct
`LIMIT_REACHED` state with its partial steps and charges kept, because it did not
fail, it ran out of allowance, and those are different signals for retrying and
for paging. I also keep a `MAX_STEPS` backstop, since a planner returning
zero-cost actions forever would pass the budget check indefinitely. The two bounds
cover different failure modes.

## Mid-run failure

A failing step is retried in place up to a small limit with backoff. If it still
fails, the step is marked `FAILED` with no ledger entry, the run is marked
`FAILED`, and earlier successful steps keep their charges. Recovery is a resume,
not a restart: `POST /runs/{id}/retry` rebuilds state from the steps table, reuses
the checkpointed outputs of the successful steps without re-executing or
re-charging them, and continues from the first non-successful step. Resume matters
because real tool calls are not idempotent, and re-running succeeded steps would
either double-charge or repeat side effects. A failure plus recovery costs the
same as a clean run.

## Counting credits

Credits are integers everywhere, so there is no floating point drift by
construction. Spend is recorded in an append-only ledger, one row per step, and
the total is always `SUM(amount)` with no cached counter to fall out of sync. A
step result and its charge are written in one transaction, so a crash can never
leave a succeeded step uncharged or a charge without work. Double-charging is
prevented by a unique constraint on `ledger.step_id`, not by application code: I
forced a duplicate charge directly and the database rejected it, and a ten-way
concurrent retry produced zero duplicate charges.

## Idempotency

Retries are recognized by a client `Idempotency-Key` header, following the Stripe
model, because the same goal submitted twice on purpose is legitimately two runs
and only a key distinguishes retry from repeat. Enforcement is an atomic insert
against a unique constraint on the key, not a check-then-insert: I insert directly
and, on conflict, return the existing run. A check-then-insert has a race under
concurrent retries, which I demonstrated: with the constraint it raises an
unhandled error, and without the constraint it created seventeen duplicate runs
for one key. Same key with a different body returns 422.

## The tradeoff I am least sure about

Charging for completed steps when a run fails. I charge for delivered work and
refund nothing on the successful steps, which is defensible because those outputs
are real and are reused on resume. But a customer-hostile reading exists: the user
asked for a finished result and did not get one, so charging for partial progress
they cannot use on their own may feel wrong. An alternative is to hold the charges
in escrow and only realize them once the run reaches `COMPLETED`, refunding
everything if it never does. I chose pay-for-delivered-work because it keeps the
economics honest under automatic retries, but I am not certain it is the right call
for a consumer product versus an enterprise API, and it is the decision I would
most want to test with real users.
