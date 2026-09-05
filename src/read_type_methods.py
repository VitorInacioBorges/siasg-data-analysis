import os
from datetime import date, timedelta

class ConfigError(Exception):
    """Raised when a value in the .env file is missing or malformed."""

def _read_text(key: str, default: str = "") -> str:
    raw = os.getenv(key)
    return raw.strip() if raw and raw.strip() else default


def _read_int(key: str, default: int) -> int:
    raw = _read_text(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"'{key}' precisa ser um número inteiro (recebido: {raw!r})")


def _read_float(key: str, default: float) -> float:
    raw = _read_text(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"'{key}' precisa ser um número (recebido: {raw!r})")


def _read_bool(key: str, default: bool) -> bool:
    raw = _read_text(key).lower()
    if not raw:
        return default
    if raw in {"true", "1", "sim", "yes"}:
        return True
    if raw in {"false", "0", "nao", "não", "no"}:
        return False
    raise ConfigError(f"'{key}' precisa ser true ou false (recebido: {raw!r})")


def _read_date(key: str, default: date) -> date:
    raw = _read_text(key)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ConfigError(f"'{key}' precisa estar no formato AAAA-MM-DD (recebido: {raw!r})")


def _read_optional(key: str) -> str | None:
    """Returns None for empty values, so the filter is simply not sent."""
    return _read_text(key) or None


def _read_list(key: str) -> list[str]:
    raw = _read_text(key)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else []