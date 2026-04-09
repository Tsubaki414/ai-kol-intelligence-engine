"""
Supabase client wrapper for the KOL pipeline.

Single entry point for all DB access. Holds two clients:
- `get_client()` → service_role key, full R/W access (pipeline side)
- `get_anon_client()` → anon key, read-only via RLS (for testing what the
  React demo will see)

Usage:
    from pipeline.db import get_client
    c = get_client()
    c.table("users").upsert({"handle": "foo", "x_id": "123"}).execute()

Environment variables loaded from .env. Each role accepts multiple naming
conventions (we try them in order until one has a non-empty value), because
Supabase's dashboard now offers both the legacy `eyJ...` JWT format under
names like `SUPABASE_ANON_KEY` and the new `sb_publishable_*` / `sb_secret_*`
format under names like `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY`. Either
format works with supabase-py.

    SUPABASE_URL                                    (required — project URL)

    For get_client() — service_role / secret key (bypasses RLS, server-only):
        SUPABASE_SERVICE_KEY        (preferred)
        SUPABASE_SERVICE            (alternative)
        SUPABASE_SECRET             (new sb_secret_* format)

    For get_anon_client() — anon / publishable key (RLS-restricted, safe for browser):
        SUPABASE_ANON_KEY           (preferred)
        SUPABASE_ANON               (alternative)
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY   (new sb_publishable_* format)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# Accepted env var names per role, in preference order
_SERVICE_KEY_NAMES = (
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_SERVICE",
    "SUPABASE_SECRET",
)
_ANON_KEY_NAMES = (
    "SUPABASE_ANON_KEY",
    "SUPABASE_ANON",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY",
)


class DBConfigError(RuntimeError):
    """Raised when Supabase credentials are missing or invalid."""


def _first_env(names: tuple[str, ...]) -> tuple[str, str]:
    """Return (var_name_used, value) of the first non-empty env var in `names`."""
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return n, v
    raise DBConfigError(
        f"None of these env vars are set: {', '.join(names)}. "
        "See supabase/SETUP.md step 4."
    )


def _require(var: str) -> str:
    val = (os.environ.get(var) or "").strip()
    if not val:
        raise DBConfigError(
            f"{var} not set in .env — see supabase/SETUP.md step 4"
        )
    return val


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a cached Supabase client authenticated with the service_role / secret key.

    Use this for all pipeline writes (migration, scoring, graph rebuild, etc.).
    The secret key bypasses RLS, so it has full R/W on all tables.
    """
    url = _require("SUPABASE_URL")
    _name, key = _first_env(_SERVICE_KEY_NAMES)
    return create_client(url, key)


@lru_cache(maxsize=1)
def get_anon_client() -> Client:
    """Return a cached Supabase client authenticated with the anon / publishable key.

    Use this to test what the React demo will actually see through RLS policies.
    """
    url = _require("SUPABASE_URL")
    _name, key = _first_env(_ANON_KEY_NAMES)
    return create_client(url, key)


def ping() -> dict[str, Any]:
    """Health check: confirm we can connect and query the users table.

    Returns a dict with row counts per table. Raises on connection failure.
    """
    c = get_client()
    result: dict[str, Any] = {"connected": True, "tables": {}}
    for table in ("users", "follows", "tweets", "seeds"):
        r = c.table(table).select("*", count="exact").limit(0).execute()
        result["tables"][table] = r.count
    return result


if __name__ == "__main__":
    # CLI: python -m pipeline.db → print health check
    import json

    try:
        print(json.dumps(ping(), indent=2))
    except DBConfigError as e:
        print(f"CONFIG ERROR: {e}")
        raise SystemExit(1)
    except Exception as e:
        print(f"CONNECTION ERROR: {type(e).__name__}: {e}")
        raise SystemExit(2)
