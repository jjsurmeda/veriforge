# Local task entry points. Apps run in Docker Compose; the scripts talk to the
# same Postgres through DATABASE_URL in .env.

.PHONY: seed-models seed-books smoke acceptance eval-gate-local

seed-models:
	cd apps/api && .venv/bin/python scripts/seed_models.py

seed-books:
	cd apps/api && .venv/bin/python scripts/seed_gutenberg.py

smoke:
	cd apps/api && .venv/bin/python scripts/smoke_chat.py

acceptance:
	cd apps/api && .venv/bin/python scripts/acceptance.py

# The TRD §15 gate against a fresh ephemeral DB, same steps as ci.yml's
# eval-gate job. Baselines are written only this way (D3 item 2).
eval-gate-local:
	./scripts/eval_gate_local.sh
