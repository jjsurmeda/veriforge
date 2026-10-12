# Local task entry points. Apps run in Docker Compose; the scripts talk to the
# same Postgres through DATABASE_URL in .env.

.PHONY: seed-models seed-books seed-admin seed-eval-user seed-demo smoke acceptance eval-gate-local check-work

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

# Lane E item 4. Creates the `demo` plan demo accounts run on and reports
# whether the Shared library holds the books. Idempotent, and it never writes
# `free`, `pro` or `internal-eval`. The plan's limits ARE the demo budget —
# there is no separate quota path for the demo role.
seed-demo:
	cd apps/api && .venv/bin/python scripts/seed_demo.py

smoke:
	cd apps/api && .venv/bin/python scripts/smoke_chat.py

acceptance:
	cd apps/api && .venv/bin/python scripts/acceptance.py

# The TRD §15 gate against a fresh ephemeral DB, same steps as ci.yml's
# eval-gate job. Baselines are written only this way (D3 item 2).
eval-gate-local:
	./scripts/eval_gate_local.sh

# --- phase 1 finish line: does the product work? ------------------------------
# `make check-work` runs nine steps in order and stops at the first failure,
# printing one PASS/FAIL line per step with the number that decided it: the api
# unit gate (ruff, mypy --strict, pytest), the web unit gate (vitest, OpenAPI
# export + drift), a check that no config or seed default resolves to a `:free`
# model, the TRD §15 eval gate against both stored baselines (fast20 AND the
# counterfactual subset, each on a fresh ephemeral database), the
# entity-mismatch set at 12/12 clean declines with 0 confident wrong, and the
# 57-item books acceptance set at PRD §5's bar for one run (0 confident wrong,
# ≥18/20 clean declines, ≤1/33 false abstentions, smalltalk and library pass).
# It SPENDS PROVIDER CREDIT in its last three steps — check the OpenRouter
# balance first (docs/conventions/agents.md) — and is therefore not the
# three-minute command the unit gate alone is. Every step is classified from the
# run's own recorded fields, never inferred from a stream: a decline streams a
# delta too, and lane B2's probe nearly reported a false failure rate for
# exactly that reason. The acceptance step runs against an api started from this
# checkout and fails if that api is not serving `git rev-parse HEAD` — the
# running dev stack serves the main checkout's code, so `make acceptance` in a
# worktree scores the wrong commit.
check-work:
	./scripts/check_work.sh

# --- beta deployment images (lane A) ----------------------------------------
# Tag by git SHA so a deployed artefact names its own commit. up.sh overrides
# IMAGE_TAG for the pushed tags; these are the local build names.
IMAGE_TAG ?= $(shell git rev-parse --short HEAD)
REGISTRY   ?= veriforge
API_IMAGE  ?= $(REGISTRY)/api:$(IMAGE_TAG)
WEB_IMAGE  ?= $(REGISTRY)/web:$(IMAGE_TAG)

# linux/arm64 explicitly. The owner's Mac is arm64 so this is a native build,
# but pinning the platform keeps a future builder from silently producing an
# amd64 image that cannot run on t4g.
PLATFORM ?= linux/arm64

.PHONY: image-build image-build-api image-build-web image-smoke image-prune
.PHONY: infra-check infra-check-caddy infra-check-scripts infra-check-backup

# The api and the workers are one image; they differ only by command.
image-build: image-build-api image-build-web

image-build-api:
	docker buildx build --platform $(PLATFORM) \
		-f Dockerfile.api --tag $(API_IMAGE) apps/api

# The SPA is compiled here and baked into the Caddy image, so the instance
# pulls a static bundle instead of building on boot.
#
# Context is the repository root, not apps/web, because the Caddyfile is a root
# file and has to go into the image. The root .dockerignore narrows that
# context back down to the Caddyfile plus apps/web.
image-build-web:
	docker buildx build --platform $(PLATFORM) \
		-f Dockerfile.web --tag $(WEB_IMAGE) .

# Proves the built api image actually starts and answers /healthz, against a
# throwaway database on a port that does not clash with the dev stack.
image-smoke:
	./infra/image_smoke.sh

# --- local verification -----------------------------------------------------
# Everything the beta deployment claims, re-checkable without AWS and without
# spending provider credit. Run this before believing any of it.
infra-check: infra-check-caddy infra-check-scripts infra-check-cdk

infra-check-caddy:
	python3 infra/tests/test_caddyfile_parity.py

infra-check-scripts:
	./infra/tests/test_scripts.sh

# Dumps the dev database and restores it into a scratch one. Not part of
# `infra-check` because it moves ~160 MB and builds an HNSW index.
infra-check-backup:
	./infra/tests/test_backup_restore.sh

infra-check-cdk:
	cd infra/cdk && npx jest && npx cdk synth --quiet

# The whole production compose, locally, on ports that do not clash with dev.
infra-check-compose:
	./infra/prod_compose_check.sh

# Only this lane's build cache. `docker system prune` would take the dev
# stack's images with it, which is not this lane's to delete.
image-prune:
	docker builder prune --filter "until=24h" --force
	docker builder prune --force
