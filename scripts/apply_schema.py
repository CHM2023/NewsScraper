"""Apply a SQL file to Supabase over the Postgres wire protocol.

PostgREST cannot run DDL, so the schema has to go over a real Postgres
connection. `psql` is not on this machine's PATH and installing the Postgres
client tools for one statement is heavier than a script, so this does the same
job with psycopg.

Usage:
    python -m scripts.apply_schema                 # applies sql/001_init.sql
    python -m scripts.apply_schema sql/002_x.sql   # or any other file
    python -m scripts.apply_schema --check         # verify only, apply nothing

Reads DATABASE_URL from the environment (via common.config, so .env is picked
up). Supabase gives two forms of that string: the session pooler on port 5432
and the transaction pooler on 6543. DDL needs the session pooler - the
transaction pooler cannot hold the statement-level state some DDL requires.
The whole file is sent as one statement batch inside a transaction, so a
failure half way leaves nothing behind.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from common import config
from common.logging_setup import configure_logging

log = logging.getLogger("scripts.apply_schema")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQL = REPO_ROOT / "sql" / "001_init.sql"

EXPECTED_TABLES = ("event_weights", "events", "prices_daily", "notifications_log", "headlines")
EXPECTED_WEIGHTS = 27


def _connect(url: str):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit(
            "psycopg is not installed. Run: pip install -r requirements.txt"
        ) from exc
    # A short timeout so a wrong host fails fast instead of hanging the session.
    return psycopg.connect(url, connect_timeout=20)


def apply_sql(url: str, path: Path) -> None:
    """Run every statement in ``path`` inside one transaction."""
    sql = path.read_text(encoding="utf-8")
    log.info("applying %s (%d bytes)", path.name, len(sql))
    with _connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    log.info("applied cleanly")


def verify(url: str) -> bool:
    """Check the five tables exist and the weights are seeded."""
    ok = True
    with _connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'public'
                order by table_name
                """
            )
            found = {row[0] for row in cur.fetchall()}
            log.info("tables in public: %s", ", ".join(sorted(found)) or "(none)")
            for table in EXPECTED_TABLES:
                if table not in found:
                    log.error("missing table: %s", table)
                    ok = False

            if "event_weights" in found:
                cur.execute("select count(*) from event_weights")
                count = cur.fetchone()[0]
                log.info("event_weights rows: %d (expected %d)", count, EXPECTED_WEIGHTS)
                if count != EXPECTED_WEIGHTS:
                    log.error("event_weights has %d rows, expected %d", count, EXPECTED_WEIGHTS)
                    ok = False

            cur.execute("select current_database(), version()")
            database, version = cur.fetchone()
            log.info("connected to %s, %s", database, version.split(",")[0])

    log.info("verification %s", "passed" if ok else "FAILED")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "sql_file", nargs="?", default=str(DEFAULT_SQL), help="SQL file to apply"
    )
    parser.add_argument(
        "--check", action="store_true", help="verify only, apply nothing"
    )
    args = parser.parse_args()

    configure_logging()
    url = config.require("DATABASE_URL")

    if not args.check:
        apply_sql(url, Path(args.sql_file))

    sys.exit(0 if verify(url) else 1)


if __name__ == "__main__":
    main()
