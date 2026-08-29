"""
config.py — plain-env-var settings for the API layer. No new config
management dependency (pydantic-settings) added for six variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ApiSettings:
    host: str = os.environ.get("CAUSA_API_HOST", "0.0.0.0")
    port: int = int(os.environ.get("CAUSA_API_PORT", "8000"))
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip() for o in os.environ.get(
                "CAUSA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if o.strip()
        ]
    )


settings = ApiSettings()
