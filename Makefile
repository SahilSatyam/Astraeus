SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml

.PHONY: help bootstrap dev down stop clean logs ps fmt lint typecheck test test-int \
        migrate downgrade revision build smoke env-lint precommit-install \
        dev-k8s k8s-down k8s-clean helm-lint tf-validate tf-plan \
        load-test generate-client

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

bootstrap:  ## First-time setup: copy .env, sync uv deps, install pre-commit.
	./scripts/bootstrap.sh

dev:  ## Build app images and bring the full stack up; wait on health.
	$(COMPOSE) build
	$(COMPOSE) up -d --wait
	$(COMPOSE) --profile init run --rm minio-init
	./scripts/verify-stack.sh

stop:  ## Stop containers but keep volumes.
	$(COMPOSE) stop

down:  ## Stop and remove containers; keep named volumes.
	$(COMPOSE) down

clean:  ## Stop, remove containers AND volumes (destructive).
	$(COMPOSE) down -v

logs:  ## Tail logs for all services.
	$(COMPOSE) logs -f --tail=100

ps:  ## Show container status.
	$(COMPOSE) ps

fmt:  ## Auto-format code (ruff format + ruff fix).
	uv run ruff format .
	uv run ruff check --fix .

lint:  ## Lint (ruff check + format check, no autofix).
	uv run ruff check .
	uv run ruff format --check .

typecheck:  ## mypy strict over apps + libs.
	uv run mypy apps libs

test:  ## Unit tests only (no containers).
	uv run pytest -m unit

test-int:  ## Integration tests (testcontainers).
	uv run pytest -m integration

migrate:  ## Apply alembic migrations to head.
	cd libs/db && uv run alembic upgrade head

downgrade:  ## Roll back one alembic revision.
	cd libs/db && uv run alembic downgrade -1

revision:  ## Create a new alembic revision: make revision MSG="add foo"
	@if [ -z "$(MSG)" ]; then echo "MSG=... is required"; exit 1; fi
	cd libs/db && uv run alembic revision --autogenerate -m "$(MSG)"

build:  ## Build all docker images.
	$(COMPOSE) build

smoke:  ## Run the post-up smoke verification.
	./scripts/verify-stack.sh

env-lint:  ## Confirm .env.example is a superset of every Settings variable.
	uv run python scripts/env-lint.py

backfill:  ## Run market data backfill: make backfill SYMBOLS=SPY,AAPL START=2024-01-01 END=2024-12-31
	@if [ -z "$(SYMBOLS)" ] || [ -z "$(START)" ] || [ -z "$(END)" ]; then \
	  echo "Usage: make backfill SYMBOLS=SPY,AAPL START=2024-01-01 END=2024-12-31"; exit 1; fi
	uv run python scripts/md-backfill.py --source $(or $(SOURCE),yahoo) \
	  --symbols $(SYMBOLS) --start $(START) --end $(END)

backfill-universe:  ## Backfill the full universe from data/universe.txt.
	@if [ -z "$(START)" ] || [ -z "$(END)" ]; then \
	  echo "Usage: make backfill-universe START=2020-01-01 END=2024-12-31"; exit 1; fi
	uv run python scripts/md-backfill.py --source $(or $(SOURCE),yahoo) \
	  --symbols-file data/universe.txt --start $(START) --end $(END)

replay:  ## Replay market data: make replay SOURCE=yahoo START=2024-01-01 END=2024-01-31
	@if [ -z "$(SOURCE)" ] || [ -z "$(START)" ] || [ -z "$(END)" ]; then \
	  echo "Usage: make replay SOURCE=yahoo START=2024-01-01 END=2024-01-31 [SYMBOL=AAPL] [DRY_RUN=1]"; exit 1; fi
	uv run python scripts/md-replay.py --source $(SOURCE) --from $(START) --to $(END) \
	  $(if $(SYMBOL),--symbol $(SYMBOL)) $(if $(DRY_RUN),--dry-run) $(if $(VERIFY),--verify)

precommit-install:  ## Install git hooks via pre-commit.
	uv run pre-commit install

# ─── Phase 10: Kubernetes / Production Hardening ─────────────────────────────

dev-k8s:  ## Spin up full local stack on kind (requires kind, helm, kubectl).
	bash infra/kind/bootstrap.sh

k8s-down:  ## Delete the local kind cluster.
	kind delete cluster --name astraeus-local

k8s-clean: k8s-down  ## Delete cluster and prune docker resources.
	docker system prune -f

helm-lint:  ## Lint all Helm charts.
	@for chart in apps/*/deploy/chart; do \
	  echo "==> Linting $$chart"; \
	  helm lint "$$chart" --strict || exit 1; \
	done

helm-template:  ## Render all Helm charts (dry-run validation).
	@for chart in apps/*/deploy/chart; do \
	  echo "==> Templating $$chart"; \
	  helm template test "$$chart" > /dev/null || exit 1; \
	done

tf-validate:  ## Validate all Terraform modules.
	@for env in infra/terraform/envs/*/; do \
	  echo "==> Validating $$env"; \
	  terraform -chdir="$$env" init -backend=false > /dev/null 2>&1; \
	  terraform -chdir="$$env" validate || exit 1; \
	done

tf-plan:  ## Run terraform plan against dev (requires AWS creds).
	terraform -chdir=infra/terraform/envs/dev init
	terraform -chdir=infra/terraform/envs/dev plan

load-test:  ## Run load test against local API: make load-test [DURATION=30] [CONCURRENCY=10]
	uv run python scripts/load-test.py \
	  --duration $(or $(DURATION),30) --concurrency $(or $(CONCURRENCY),10)

generate-client:  ## Generate TypeScript API client from OpenAPI spec (requires running API).
	./scripts/generate-api-client.sh
