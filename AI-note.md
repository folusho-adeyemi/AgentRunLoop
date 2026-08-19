# AI note

I built this with an AI coding agent and drove it throughout.

What I used AI for: scaffolding, the SQLite boilerplate, writing tests and verification harnesses, and executing each stage. I designed the system first though. Before any code I worked through the tradeoffs for each hard part and
decided the mechanism myself: an idempotency key rather than a body hash because a body hash creates a conflict if the user genuinely want to a similar action but in different scenarios, an
append-only ledger rather than a mutable counter, integer credits instead of floats or decimals so as to prevent drifts, insert-on-conflict rather than check-then-insert, and a resume-from-checkpoint recovery
rather than a fresh restart. I fed the agent one scoped stage at a time with those decisions specified, and reviewed every diff against a checklist before moving on, so the model implemented my design rather than choosing the architecture for me.

Where I accepted output as-is: the mechanical parts. The connection helper and its pragmas, the uuid id generation, the request-hash normalization, and the shape of the test files. These were correct and I understand each line, so I did not rewrite
them.

Where I overrode it: the first UI it produced was overdesigned, with gradients, rounded pills, and color used decoratively. I rejected it and specified a minimalist black-white-purple layout with square edges and color reserved strictly for status, green for success, red for failure, yellow for running and limit
reached. I also pushed the failure scenario to be genuinely testable: a step that fails once is rescued by the in-run retry and reaches COMPLETED, which would never exercise the resume path, so I had it add a harder failure variant that outlasts the in-run retries and forces the run to FAILED.

One thing it got wrong that I also saw: I believe it was the stale-UI bug: clicking Run left the previous run's finished status and steps on screen until the new POST resolved, and a late poll from the old run could paint over the new one. As a result, the rendered state was wrong, and the fix was to reset the panel and stop the old poller at the top of the submit handler. 

The verification was real and accurate, not decorative. Every stage was checked against a live server: the three demo scenarios, a thirty-way concurrent retry race, a headless browser driving the actual UI, and database invariants after each run, no succeeded step uncharged, no failed step charged, no step charged twice, and no run over budget.
