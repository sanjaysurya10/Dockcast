"""FastAPI application (PRD 15): read-only JSON, ``/v1`` base path, OpenAPI at ``/docs``.

``make serve`` runs it with Uvicorn against ``DATABASE_URL``. Errors use
``{"error": {"code", "message"}}`` (PRD 15.3); requests are limited per IP (PRD 15.4).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import Engine

from dockcast import __version__
from dockcast.api.errors import ApiError
from dockcast.api.routes import health, model, stations
from dockcast.config import get_env_settings, load_project_config
from dockcast.db.engine import make_engine


def _error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status, headers=headers
    )


def create_app(engine: Engine | None = None, rate_limit: str | None = None) -> FastAPI:
    """Build the app.

    Args:
        engine: Database engine (default: ``DATABASE_URL``).
        rate_limit: slowapi limit string (default: ``serving.api_rate_limit``).

    Returns:
        The application.
    """
    app = FastAPI(title="DockCast API", version=__version__)
    app.state.engine = engine or make_engine()
    limit = rate_limit or load_project_config().serving.api_rate_limit
    per_ip = parse(limit)
    backend = Limiter(key_func=get_remote_address).limiter

    # slowapi's own middleware finds limits by route and skips FastAPI's included routers,
    # so every request is counted here instead.
    @app.middleware("http")
    async def limit_per_ip(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not backend.hit(per_ip, get_remote_address(request)):
            return _error(
                429, "rate_limited", f"rate limit exceeded: {limit}", {"Retry-After": "60"}
            )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_env_settings().cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> Any:
        return _error(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> Any:
        return _error(422, "invalid_request", str(exc.errors()[0].get("msg", "invalid request")))

    app.include_router(health.router)
    app.include_router(stations.router, prefix="/v1")
    app.include_router(model.router, prefix="/v1")
    return app


def main() -> None:
    """``make serve``."""
    import uvicorn

    uvicorn.run("dockcast.api.app:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
