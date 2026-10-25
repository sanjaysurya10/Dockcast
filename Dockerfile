FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-default-groups --no-install-project

COPY dockcast ./dockcast
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-default-groups

RUN useradd --create-home --uid 10001 dockcast && mkdir -p /app/data && chown dockcast /app/data
USER dockcast

CMD ["python", "-m", "dockcast.ingest.collector"]
