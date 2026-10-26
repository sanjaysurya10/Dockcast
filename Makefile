.PHONY: setup db-up db-down backfill backfill-new gaps weather resample capacity calendar eda backtest collect collector-up collector-down collector-logs health lint typecheck pytest test

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

weather:
	uv run python -m dockcast.ingest.weather_history
	uv run python -m dockcast.ingest.weather_forecast

resample:
	uv run python -m dockcast.transform.resample

capacity:
	uv run python -m dockcast.transform.capacity

calendar:
	uv run python -m dockcast.ingest.calendar

eda:
	uv run python -m dockcast.quality.eda

backtest:
	uv run python -m dockcast.experiments.$(shell echo $(E) | tr A-Z a-z)

collect:
	uv run python -m dockcast.ingest.collector

collector-up:
	docker compose --profile collector up -d --build collector

collector-down:
	docker compose --profile collector stop collector

collector-logs:
	docker compose --profile collector logs --tail 50 collector

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
