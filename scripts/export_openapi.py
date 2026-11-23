"""Описание API (OpenAPI) → frontend/src/api/openapi.json — из него генерируются типы клиента нового фронтенда.

    .venv/bin/python -m scripts.export_openapi      (или в frontend/: npm run api — заодно пересоберёт типы)
"""
from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parent.parent / "frontend" / "src" / "api" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"OpenAPI: {len(schema['paths'])} путей → {OUT}")


if __name__ == "__main__":
    main()
