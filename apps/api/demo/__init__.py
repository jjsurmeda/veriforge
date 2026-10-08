"""Demo mode (lane E item 4, PRD AC-2).

A read-only demo account on the shared demo corpus, for the private beta's
visitors. The pieces, in the order a request meets them:

- `settings` — the numbers, and why they are those numbers.
- `service`  — creating and expiring the accounts.
- `cleanup`  — the periodic sweep.
- `router`   — `POST /auth/demo`, rate limited per IP.

Settings live here rather than in `config.py` because lane C is editing that
file in parallel and this feature is not allowed to touch it.
"""