from __future__ import annotations

import os
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL


class DatabaseNotConfigured(RuntimeError):
    pass


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS portfolio_records (
    id BIGSERIAL PRIMARY KEY,
    purchase_date DATE NOT NULL,
    share_code TEXT NOT NULL,
    investment_amount NUMERIC(18, 4) NOT NULL CHECK (investment_amount >= 0),
    purchase_units NUMERIC(18, 8) NOT NULL CHECK (purchase_units > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_share_code
    ON portfolio_records (share_code);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_purchase_date
    ON portfolio_records (purchase_date);
"""

_schema_ready = False


def _require_database_url() -> str:
    if not DATABASE_URL:
        raise DatabaseNotConfigured("DATABASE_URL is missing. Add your Neon connection string in Vercel Environment Variables.")
    return DATABASE_URL


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    url = _require_database_url()
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with get_connection() as conn:
        conn.execute(SCHEMA_SQL)
    _schema_ready = True


def decimal_to_float(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            cleaned[key] = value.isoformat()
        else:
            cleaned[key] = decimal_to_float(value)
    return cleaned


def list_records() -> list[dict[str, Any]]:
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                purchase_date,
                UPPER(TRIM(share_code)) AS share_code,
                investment_amount,
                purchase_units,
                CASE
                    WHEN purchase_units > 0 THEN investment_amount / purchase_units
                    ELSE 0
                END AS average_price,
                created_at,
                updated_at
            FROM portfolio_records
            ORDER BY purchase_date DESC, id DESC
            """
        ).fetchall()
    return [clean_row(dict(row)) for row in rows]


def get_record(record_id: int) -> dict[str, Any] | None:
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                purchase_date,
                UPPER(TRIM(share_code)) AS share_code,
                investment_amount,
                purchase_units,
                CASE
                    WHEN purchase_units > 0 THEN investment_amount / purchase_units
                    ELSE 0
                END AS average_price,
                created_at,
                updated_at
            FROM portfolio_records
            WHERE id = %s
            """,
            (record_id,),
        ).fetchone()
    return clean_row(dict(row)) if row else None


def insert_record(
    purchase_date: str,
    share_code: str,
    investment_amount: float,
    purchase_units: float,
) -> dict[str, Any]:
    ensure_schema()
    share_code = share_code.strip().upper()

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM portfolio_records
            WHERE purchase_date = %s
              AND UPPER(TRIM(share_code)) = %s
              AND investment_amount = %s
              AND purchase_units = %s
              AND created_at > now() - interval '15 seconds'
            ORDER BY id DESC
            LIMIT 1
            """,
            (purchase_date, share_code, investment_amount, purchase_units),
        ).fetchone()

        if duplicate:
            existing = get_record(int(duplicate["id"]))
            if existing:
                existing["duplicate_blocked"] = True
                return existing

        row = conn.execute(
            """
            INSERT INTO portfolio_records (
                purchase_date,
                share_code,
                investment_amount,
                purchase_units
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (purchase_date, share_code, investment_amount, purchase_units),
        ).fetchone()

    return get_record(int(row["id"]))


def update_record(
    record_id: int,
    purchase_date: str,
    share_code: str,
    investment_amount: float,
    purchase_units: float,
) -> dict[str, Any] | None:
    ensure_schema()
    share_code = share_code.strip().upper()

    with get_connection() as conn:
        row = conn.execute(
            """
            UPDATE portfolio_records
            SET
                purchase_date = %s,
                share_code = %s,
                investment_amount = %s,
                purchase_units = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING id
            """,
            (purchase_date, share_code, investment_amount, purchase_units, record_id),
        ).fetchone()

    if not row:
        return None
    return get_record(int(row["id"]))


def delete_record(record_id: int) -> bool:
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM portfolio_records WHERE id = %s",
            (record_id,),
        )
    return result.rowcount > 0


def holdings_summary_rows() -> list[dict[str, Any]]:
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                UPPER(TRIM(share_code)) AS share_code,
                SUM(investment_amount) AS total_invested,
                SUM(purchase_units) AS total_units,
                CASE
                    WHEN SUM(purchase_units) > 0
                    THEN SUM(investment_amount) / SUM(purchase_units)
                    ELSE 0
                END AS average_price,
                COUNT(*) AS transaction_count
            FROM portfolio_records
            GROUP BY UPPER(TRIM(share_code))
            ORDER BY UPPER(TRIM(share_code))
            """
        ).fetchall()
    return [clean_row(dict(row)) for row in rows]


def ping_database() -> bool:
    ensure_schema()
    with get_connection() as conn:
        conn.execute("SELECT 1")
    return True
