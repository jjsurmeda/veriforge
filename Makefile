# Local task entry points. Apps run in Docker Compose; the scripts talk to the
# same Postgres through DATABASE_URL in .env.

.PHONY: seed-models seed-books smoke acceptance

seed-models:
	cd apps/api && .venv/bin/python scripts/seed_models.py

seed-books:
	cd apps/api && .venv/bin/python scripts/seed_gutenberg.py

smoke:
	cd apps/api && .venv/bin/python scripts/smoke_chat.py

acceptance:
	cd apps/api && .venv/bin/python scripts/acceptance.py
