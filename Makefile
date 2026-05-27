SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose -f infra/docker/compose.yml -f infra/docker/compose.override.yml

.PHONY: help bootstrap dev down stop clean logs ps fmt lint typecheck test test-int \
        migrate downgrade revision build smoke env-lint precommit-install

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

precommit-install:  ## Install git hooks via pre-commit.
	uv run pre-commit install
