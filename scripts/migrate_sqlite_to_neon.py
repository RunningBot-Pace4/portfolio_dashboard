"""
Move local SQLite records from an older version into Neon Postgres.

Usage on Windows PowerShell:
  $env:DATABASE_URL="postgresql://..."
  python scripts/migrate_sqlite_to_neon.py --sqlite data/portfolio.db

This script is safe to run more than once. It skips duplicate records that match:
purchase_date + symbol + investment_amount + purchase_units.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import psycopg
from dotenv import load_dotenv


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    purchase_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    investment_amount NUMERIC(18, 6) NOT NULL CHECK (investment_amount > 0),
    purchase_units NUMERIC(18, 6) NOT NULL CHECK (purchase_units > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_transactions_symbol ON transactions(symbol);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(purchase_date);
"""


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="data/portfolio.db", help="Path to the old SQLite database")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is missing. Set it to your Neon connection string first.")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute(
        """
        SELECT purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
        FROM transactions
        ORDER BY id
        """
    ).fetchall()

    inserted = 0
    skipped = 0

    with psycopg.connect(database_url) as pg:
        with pg.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            for row in rows:
                duplicate = cur.execute(
                    """
                    SELECT id
                    FROM transactions
                    WHERE purchase_date = %s::date
                      AND symbol = %s
                      AND ABS(investment_amount - %s) < 0.000001
                      AND ABS(purchase_units - %s) < 0.000001
                    LIMIT 1
                    """,
                    (
                        row["purchase_date"],
                        row["symbol"],
                        row["investment_amount"],
                        row["purchase_units"],
                    ),
                ).fetchone()

                if duplicate:
                    skipped += 1
                    continue

                cur.execute(
                    """
                    INSERT INTO transactions
                        (purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at)
                    VALUES (%s::date, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["purchase_date"],
                        row["symbol"],
                        row["investment_amount"],
                        row["purchase_units"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
                inserted += 1

    print(f"Done. Inserted {inserted} records. Skipped {skipped} duplicates.")


if __name__ == "__main__":
    main()
