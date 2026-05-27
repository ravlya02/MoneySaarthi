#!/usr/bin/env python
"""Apply MoneySaarthi database migrations to Supabase Postgres.

Runs three SQL files in order:
  1. schema.sql   — tables, indexes, RLS enable (all idempotent via IF NOT EXISTS)
  2. policies.sql — RLS policies (CREATE POLICY is not idempotent; re-running
                    will error on duplicate policy names — use with care on a
                    populated DB; the schema.sql tables will still be fine)
  3. triggers.sql — trigger function + trigger (idempotent via CREATE OR REPLACE
                    and DROP TRIGGER IF EXISTS)

Usage:
  python app/db/apply.py            # execute against live Supabase Postgres
  python app/db/apply.py --dry-run  # print SQL statements, no execution

Environment variables:
  DATABASE_URL   Supabase direct Postgres connection string, e.g.:
                 postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres
                 Do NOT use the REST/PostgREST URL here.
"""
import argparse
import os
import sys
from pathlib import Path

# Load .env from the repo root automatically so DATABASE_URL doesn't have to be
# exported manually in the shell. python-dotenv is already installed as a
# transitive dependency of pydantic-settings.
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parents[2] / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv not available; rely on the shell environment

SQL_DIR = Path(__file__).parent
FILES = ["schema.sql", "policies.sql", "triggers.sql"]


def split_statements(sql: str) -> list[str]:
    """Split a SQL file into individual statements on ';'.

    Strips comments-only and whitespace-only chunks so we don't send empty
    statements to Postgres.
    """
    raw = sql.split(";")
    stmts = []
    for chunk in raw:
        stripped = chunk.strip()
        if not stripped:
            continue
        # Skip chunks that are nothing but SQL line comments
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        non_comment = [ln for ln in lines if not ln.startswith("--")]
        if non_comment:
            stmts.append(stripped)
    return stmts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply MoneySaarthi DB migrations to Supabase Postgres."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL statements without executing them.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")

    conn = None
    if not args.dry_run:
        if not database_url:
            sys.exit(
                "ERROR: DATABASE_URL environment variable is not set.\n"
                "Set it to your Supabase direct Postgres connection string, e.g.:\n"
                "  postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres\n"
                "Tip: use --dry-run to preview SQL without a live database connection."
            )
        try:
            import psycopg2  # noqa: PLC0415 — lazy import; dry-run never needs it
        except ImportError:
            sys.exit(
                "ERROR: psycopg2 is not installed. Run: pip install psycopg2-binary"
            )
        try:
            conn = psycopg2.connect(database_url)
            conn.autocommit = True
            print(f"Connected to Postgres at {database_url.split('@')[-1]}")
        except psycopg2.OperationalError as exc:
            sys.exit(f"ERROR: Could not connect to Postgres:\n{exc}")

    total_applied = 0

    for fname in FILES:
        fpath = SQL_DIR / fname
        if not fpath.exists():
            print(f"WARNING: {fname} not found — skipping.")
            continue

        sql = fpath.read_text(encoding="utf-8")
        stmts = split_statements(sql)

        if args.dry_run:
            print(f"\n-- {fname} ({len(stmts)} statements) " + "-" * 40)
            for stmt in stmts:
                print(stmt + ";\n")
        else:
            cur = conn.cursor()
            failed = 0
            for stmt in stmts:
                try:
                    cur.execute(stmt)
                except psycopg2.Error as exc:
                    # Policy creation is not idempotent: "already exists" errors
                    # on re-runs are expected — report but do not abort.
                    if "already exists" in str(exc):
                        print(f"  SKIP (already exists): {stmt[:60].strip()}…")
                        conn.rollback() if not conn.autocommit else None
                    else:
                        print(f"  ERROR executing statement:\n  {stmt}\n  {exc}")
                        failed += 1
            cur.close()
            applied = len(stmts) - failed
            total_applied += applied
            print(f"Applied {applied}/{len(stmts)} statements from {fname}")

    if conn:
        conn.close()

    if args.dry_run:
        print("\n-- Dry run complete. No statements were executed.")
    else:
        print(f"\nDone. {total_applied} statement(s) applied in total.")


if __name__ == "__main__":
    main()
