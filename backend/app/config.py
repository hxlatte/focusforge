"""Runtime configuration, read from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Tiny .env loader so we don't need an extra dependency."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    project_id: str = "focusforge-3a4f7"
    allowed_origins: list[str] = field(default_factory=list)


def get_settings() -> Settings:
    _load_dotenv()
    origins = os.environ.get(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:5504,http://localhost:5504",
    )
    return Settings(
        project_id=os.environ.get("FIREBASE_PROJECT_ID", "focusforge-3a4f7"),
        allowed_origins=[o.strip() for o in origins.split(",") if o.strip()],
    )
