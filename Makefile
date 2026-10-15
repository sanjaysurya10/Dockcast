.PHONY: setup db-up db-down lint typecheck pytest test

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

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

pytest:
	uv run pytest --cov --cov-report=term-missing

test: lint typecheck pytest
