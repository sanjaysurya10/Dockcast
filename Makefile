.PHONY: setup db-up db-down backfill backfill-new gaps collect health lint typecheck pytest test

-include .env
export

setup:
	uv sync
	uv run pre-commit install
	@if [ -f web/package.json ]; then cd web && npm ci; else echo "web/ not scaffolded yet (M13)"; fi

db-up:
	docker compose up -d --wait postgres
	uv run alembic upgrade head

db-down:
	docker compose down

backfill:
	uv run python -m dockcast.ingest.historical.backfill

backfill-new:
	uv run python -m dockcast.ingest.historical.monthly

gaps:
	uv run python -m dockcast.quality.gaps

collect:
	uv run python -m dockcast.ingest.collector

health:
	uv run python -m dockcast.quality.health

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

pytest:
	uv run pytest --cov --cov-report=term-missing

test: lint typecheck pytest
