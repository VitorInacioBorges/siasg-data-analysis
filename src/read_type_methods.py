"""
Typed readers for .env values.

Everything that configures this program arrives as a string from the
environment, so each function here does the same three things: read the raw
string, decide whether it is absent (fall back to the default), and otherwise
convert it — raising ConfigError instead of letting a bad value fail later,
deep inside a request loop.

Two of them go one step further and also check a lower bound, because a value
that parses fine can still be nonsense: MAX_RETRIES=0 or REQUEST_DELAY=-1 are
both valid integers and both break the download.

The leading underscore marks them as internal helpers: they are meant to be
called by Settings.from_env(), not by application code.
"""

# Postpones evaluation of type annotations, so builtin generics and the `X |
# None` union syntax work on Python versions before 3.9/3.10 — the same reason
# main.py imports it.
from __future__ import annotations

import os  # reads the process environment (already populated by load_dotenv)
from datetime import date


class ConfigError(Exception):
    """Raised when a value in the .env file is missing or malformed."""


def _read_text(key: str, default: str = "") -> str:
    """Base reader every other reader is built on.

    Treats an unset variable, an empty one, and one holding only whitespace as
    the same thing: absent. That is why `KEY=` in the .env file behaves exactly
    like leaving the line out.
    """
    raw = os.getenv(key)
    # `raw and raw.strip()` guards both None and the whitespace-only case.
    return raw.strip() if raw and raw.strip() else default


def _read_int(key: str, default: int) -> int:
    """Reads a whole number (page size, retries, day counts)."""
    raw = _read_text(key)
    if not raw:
        # Absent value: the caller's default wins, no error.
        return default
    try:
        # int() accepts the digit grouping Python itself uses, so a .env line
        # reading SUMMARY_CHUNK_ROWS=200_000 parses as 200000.
        return int(raw)
    except ValueError:
        # Present but unparseable — a typo the user must see now, not later.
        # `from None` hides the original ValueError, so the user gets this one
        # clear message instead of a chained traceback.
        raise ConfigError(f"'{key}' precisa ser um número inteiro (recebido: {raw!r})") from None


def _read_float(key: str, default: float) -> float:
    """Reads a decimal number — used for sub-second delays such as REQUEST_DELAY."""
    raw = _read_text(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"'{key}' precisa ser um número (recebido: {raw!r})") from None


def _read_int_min(key: str, default: int, minimum: int) -> int:
    """Reads a whole number and refuses anything below `minimum`.

    Exists so from_env() can reject values the program cannot work with at all
    — a zero chunk width, a retry budget of nothing — in the first second of
    the run rather than hours into the download.
    """
    value = _read_int(key, default)
    if value < minimum:
        raise ConfigError(f"'{key}' precisa ser no mínimo {minimum} (recebido: {value})")
    return value


def _read_float_min(key: str, default: float, minimum: float) -> float:
    """Decimal counterpart of _read_int_min, for REQUEST_DELAY."""
    value = _read_float(key, default)
    if value < minimum:
        raise ConfigError(f"'{key}' precisa ser no mínimo {minimum} (recebido: {value})")
    return value


def _read_bool(key: str, default: bool) -> bool:
    """Reads a flag, accepting English and Portuguese spellings.

    Lower-casing first means TRUE, True and true are all equivalent. Anything
    outside the two accepted sets is rejected rather than silently read as
    False, so `RESUME=yep` cannot quietly wipe an existing download.
    """
    raw = _read_text(key).lower()
    if not raw:
        return default
    if raw in {"true", "1", "sim", "yes"}:
        return True
    if raw in {"false", "0", "nao", "não", "no"}:
        return False
    raise ConfigError(f"'{key}' precisa ser true ou false (recebido: {raw!r})")


def _read_date(key: str, default: date) -> date:
    """Reads a calendar date in ISO form (YYYY-MM-DD).

    ISO is required because the same format is sent straight back to the API as
    a query parameter, so no reformatting step can go wrong in between.
    """
    raw = _read_text(key)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ConfigError(
            f"'{key}' precisa estar no formato AAAA-MM-DD (recebido: {raw!r})"
        ) from None


def _read_optional(key: str) -> str | None:
    """Returns None for empty values, so the filter is simply not sent."""
    # Settings.from_env() drops every None from the filter dict; that is how an
    # unset filter becomes "no restriction" instead of "match the empty string".
    return _read_text(key) or None


def _read_list(key: str) -> list[str]:
    """Reads a comma-separated list, e.g. COLUMNS=a,b,c.

    Each entry is stripped so `a, b , c` works, and empty entries produced by a
    trailing or doubled comma are discarded. An absent key yields an empty list,
    which callers read as "no explicit choice".
    """
    raw = _read_text(key)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else []
