# Local task entry points. Apps run in Docker Compose; the scripts talk to the
# same Postgres through DATABASE_URL in .env.

.PHONY: seed-models seed-books seed-admin seed-eval-user smoke acceptance eval-gate-local

seed-models:
	cd apps/api && .venv/bin/python scripts/seed_models.py

seed-books:
	cd apps/api && .venv/bin/python scripts/seed_gutenberg.py

# The local admin `make acceptance` authenticates as. Needs ADMIN_EMAIL and
# ADMIN_PASSWORD in .env; idempotent, so it is also the password reset.
seed-admin:
	cd apps/api && .venv/bin/python scripts/seed_admin.py

# The fixed eval account `make acceptance` signs in as, which owns the eval-only
# corpora (KI-24). Needs EVAL_USER_PASSWORD in .env; idempotent. Assigns the
# seeded internal-eval plan once, here, rather than on every run (KI-20).
seed-eval-user:
	cd apps/api && .venv/bin/python scripts/seed_eval_user.py

smoke:
	cd apps/api && .venv/bin/python scripts/smoke_chat.py

acceptance:
	cd apps/api && .venv/bin/python scripts/acceptance.py

# The TRD §15 gate against a fresh ephemeral DB, same steps as ci.yml's
# eval-gate job. Baselines are written only this way (D3 item 2).
eval-gate-local:
	./scripts/eval_gate_local.sh
