"""API errors rendered as ``{"error": {"code", "message"}}`` (PRD 15.3)."""


class ApiError(Exception):
    """An error with an HTTP status, a stable code and optional headers."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        """Create the error."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def station_not_found(station_key: int) -> ApiError:
    """404 for an unknown station."""
    return ApiError(404, "station_not_found", f"no station with station_key {station_key}")


def stale(message: str, retry_after_s: int = 300) -> ApiError:
    """503 when the data behind a response is too old."""
    return ApiError(503, "data_stale", message, {"Retry-After": str(retry_after_s)})
