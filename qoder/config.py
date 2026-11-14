"""Runtime configuration for the Research Continuation Station backend.

Only the server process reads these values. The PowerContext bearer token is
kept here and NEVER forwarded to the browser or written into any log line or
evidence file. Use :func:`redact` before logging anything derived from an
outbound request.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a simple KEY=VALUE .env file (no override)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    powercontext_url: str
    powercontext_token: str
    app_host: str
    app_port: int

    @property
    def data_dir(self) -> Path:
        return DATA_DIR


_SECRET_PATTERNS = [
    re.compile(r"(Authorization\s*[:=]\s*Bearer\s+)\S+", re.IGNORECASE),
    re.compile(r"(POWERCONTEXT_TOKEN\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(scp_[0-9a-z]{6,})"),  # scope ids are partition keys, still mask tail
]


def redact(text: str) -> str:
    """Mask bearer tokens and abbreviate scope ids before any log/evidence write."""
    if text is None:
        return ""
    out = str(text)
    out = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", out)
    out = _SECRET_PATTERNS[1].sub(r"\1[REDACTED]", out)
    return out


def mask_scope(scope_id: str) -> str:
    """Show only a short prefix of a scope id in UI/evidence (it is a partition key)."""
    if not scope_id:
        return ""
    return scope_id[:8] + "…"


def load_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    return Settings(
        powercontext_url=os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8777").rstrip("/"),
        powercontext_token=os.environ.get("POWERCONTEXT_TOKEN", ""),
        app_host=os.environ.get("APP_HOST", "127.0.0.1"),
        app_port=int(os.environ.get("APP_PORT", "8688")),
    )
