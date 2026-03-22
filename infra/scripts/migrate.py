#!/usr/bin/env python3
"""
Idempotent migration runner for the platform schema.

Tracks applied migrations in the schema_migrations table.
Each V*.sql file is applied exactly once; subsequent runs skip it.

Usage:
    uv run python infra/scripts/migrate.py

Requires POSTGRES_URL in environment or .env file.
Stack must be up (make dev) before running.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parents[2] / "infra" / "docker" / "migrations"

_CREATE_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _to_asyncpg_dsn(url: str) -> str:
    """Strip SQLAlchemy dialect prefix so asyncpg can parse the DSN.

    postgresql+asyncpg://... → postgresql://...
    asyncpg://...            → postgresql://...
    """
    return re.sub(r"^(?:postgresql|postgres)\+asyncpg://", "postgresql://", url)


async def main() -> None:
    import asyncpg  # type: ignore[import]

    raw_url = os.getenv("POSTGRES_URL")
    if not raw_url:
        # Fall back to reading .env manually (avoids a pydantic-settings import)
        env_file = Path(__file__).parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("POSTGRES_URL="):
                    raw_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not raw_url:
        print("ERROR: POSTGRES_URL not set. Export it or add it to .env.", file=sys.stderr)
        sys.exit(1)

    dsn = _to_asyncpg_dsn(raw_url)
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        await conn.execute(_CREATE_TRACKING)

        applied: set[str] = {
            r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")
        }

        files = sorted(MIGRATIONS_DIR.glob("V*.sql"))
        if not files:
            print(f"No migration files found in {MIGRATIONS_DIR}")
            return

        any_applied = False
        for path in files:
            version = path.stem  # e.g. "V0__base_schema"
            if version in applied:
                print(f"  [skip]  {version}")
                continue

            print(f"  [apply] {version} ...", end=" ", flush=True)
            sql = path.read_text()
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)", version
            )
            print("done")
            any_applied = True

        if not any_applied:
            print("  All migrations already applied — nothing to do.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
