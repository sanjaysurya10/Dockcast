"""Write the API's OpenAPI document to ``web/openapi.json`` (PRD 15: typed TS client).

``make web-api`` runs this, then ``openapi-typescript`` turns it into ``web/src/api/schema.d.ts``.
No database connection is opened: the schema comes from the route and response models only.
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from dockcast.api.app import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "web" / "openapi.json"


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document of :func:`dockcast.api.app.create_app`."""
    return create_app(engine=create_engine("sqlite://")).openapi()


def render(document: dict[str, Any]) -> str:
    """Stable JSON text (sorted keys, 2-space indent, trailing newline)."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> None:
    """``make web-api``."""
    OPENAPI_PATH.write_text(render(openapi_document()), encoding="utf-8")


if __name__ == "__main__":
    main()
