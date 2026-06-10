from __future__ import annotations

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
    transaction_type TEXT NOT NULL DEFAULT 'BUY',
    investment_amount NUMERIC(18, 4) NOT NULL CHECK (investment_amount >= 0),
    purchase_units NUMERIC(18, 8) NOT NULL CHECK (purchase_units > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE portfolio_records
    ADD COLUMN IF NOT EXISTS transaction_type TEXT NOT NULL DEFAULT 'BUY';

UPDATE portfolio_records
SET transaction_type = 'BUY'
WHERE transaction_type IS NULL OR TRIM(transaction_type) = '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'portfolio_records_transaction_type_check'
    ) THEN
        ALTER TABLE portfolio_records
            ADD CONSTRAINT portfolio_records_transaction_type_check
            CHECK (UPPER(TRIM(transaction_type)) IN ('BUY', 'SELL'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_portfolio_records_share_code
    ON portfolio_records (share_code);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_purchase_date
    ON portfolio_records (purchase_date);

CREATE INDEX IF NOT EXISTS idx_portfolio_records_transaction_type
    ON portfolio_records (transaction_type);
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


def _base_record_select() -> str:
    return """
        SELECT
            id,
            purchase_date,
            UPPER(TRIM(share_code)) AS share_code,
            UPPER(TRIM(transaction_type)) AS transaction_type,
            investment_amount,
            purchase_units,
            CASE
                WHEN purchase_units > 0 THEN investment_amount / purchase_units
                ELSE 0
            END AS average_price,
            created_at,
            updated_at
        FROM portfolio_records
    """


def list_records() -> list[dict[str, Any]]:
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            _base_record_select()
            + """
            ORDER BY purchase_date DESC, id DESC
            """
        ).fetchall()
    return [clean_row(dict(row)) for row in rows]


def list_distinct_share_codes() -> list[str]:
    """Return distinct share codes already saved in Neon.

    This drives the live market dashboard, so new tickers appear after they
    are added as a transaction or inserted directly into the database.
    """
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT UPPER(TRIM(share_code)) AS share_code
            FROM portfolio_records
            WHERE TRIM(share_code) <> ''
            ORDER BY UPPER(TRIM(share_code))
            """
        ).fetchall()
    return [str(row["share_code"]).upper() for row in rows if row.get("share_code")]


def _list_records_for_share(share_code: str, exclude_record_id: int | None = None) -> list[dict[str, Any]]:
    ensure_schema()
    share_code = share_code.strip().upper()
    params: list[Any] = [share_code]
    where = "WHERE UPPER(TRIM(share_code)) = %s"
    if exclude_record_id is not None:
        where += " AND id <> %s"
        params.append(exclude_record_id)

    with get_connection() as conn:
        rows = conn.execute(
            _base_record_select()
            + f"""
            {where}
            ORDER BY purchase_date ASC, id ASC
            """,
            params,
        ).fetchall()
    return [clean_row(dict(row)) for row in rows]


def get_record(record_id: int) -> dict[str, Any] | None:
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            _base_record_select()
            + """
            WHERE id = %s
            """,
            (record_id,),
        ).fetchone()
    return clean_row(dict(row)) if row else None


def _normalise_transaction_type(transaction_type: str | None) -> str:
    cleaned = (transaction_type or "BUY").strip().upper()
    if cleaned not in {"BUY", "SELL"}:
        raise ValueError("Transaction type must be BUY or SELL.")
    return cleaned


def _validate_average_cost_sequence(records: list[dict[str, Any]]) -> None:
    """Validate that sells never exceed previously bought shares.

    Calculation method:
    - BUY adds amount and units to the average-cost pool.
    - SELL removes units at current average cost.
    - No broker fee is included.
    """
    sorted_records = sorted(
        records,
        key=lambda row: (
            str(row.get("purchase_date", "")),
            int(row.get("id") or 0),
        ),
    )

    remaining_units = 0.0
    remaining_cost = 0.0

    for row in sorted_records:
        tx_type = _normalise_transaction_type(str(row.get("transaction_type") or "BUY"))
        amount = float(row.get("investment_amount") or 0)
        units = float(row.get("purchase_units") or 0)
        share_code = str(row.get("share_code") or "").upper()

        if tx_type == "BUY":
            remaining_units += units
            remaining_cost += amount
            continue

        if units > remaining_units + 0.00000001:
            raise ValueError(
                f"Cannot sell {units:g} {share_code} shares. Available units before this sell transaction: {remaining_units:g}."
            )

        if remaining_units <= 0:
            raise ValueError(f"Cannot sell {share_code}. No shares available.")

        average_cost = remaining_cost / remaining_units
        remaining_units -= units
        remaining_cost -= average_cost * units

        if abs(remaining_units) < 0.00000001:
            remaining_units = 0.0
            remaining_cost = 0.0


def _validate_candidate_transaction(
    *,
    purchase_date: str,
    share_code: str,
    transaction_type: str,
    investment_amount: float,
    purchase_units: float,
    record_id: int | None = None,
) -> None:
    existing = _list_records_for_share(share_code, exclude_record_id=record_id)
    candidate = {
        "id": record_id or 999999999999,
        "purchase_date": purchase_date,
        "share_code": share_code.strip().upper(),
        "transaction_type": transaction_type,
        "investment_amount": investment_amount,
        "purchase_units": purchase_units,
    }
    _validate_average_cost_sequence(existing + [candidate])


def insert_record(
    purchase_date: str,
    share_code: str,
    investment_amount: float,
    purchase_units: float,
    transaction_type: str = "BUY",
) -> dict[str, Any]:
    ensure_schema()
    share_code = share_code.strip().upper()
    transaction_type = _normalise_transaction_type(transaction_type)

    _validate_candidate_transaction(
        purchase_date=purchase_date,
        share_code=share_code,
        transaction_type=transaction_type,
        investment_amount=investment_amount,
        purchase_units=purchase_units,
    )

    with get_connection() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM portfolio_records
            WHERE purchase_date = %s
              AND UPPER(TRIM(share_code)) = %s
              AND UPPER(TRIM(transaction_type)) = %s
              AND investment_amount = %s
              AND purchase_units = %s
              AND created_at > now() - interval '15 seconds'
            ORDER BY id DESC
            LIMIT 1
            """,
            (purchase_date, share_code, transaction_type, investment_amount, purchase_units),
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
                transaction_type,
                investment_amount,
                purchase_units
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (purchase_date, share_code, transaction_type, investment_amount, purchase_units),
        ).fetchone()

    return get_record(int(row["id"]))


def update_record(
    record_id: int,
    purchase_date: str,
    share_code: str,
    investment_amount: float,
    purchase_units: float,
    transaction_type: str = "BUY",
) -> dict[str, Any] | None:
    ensure_schema()
    share_code = share_code.strip().upper()
    transaction_type = _normalise_transaction_type(transaction_type)

    _validate_candidate_transaction(
        purchase_date=purchase_date,
        share_code=share_code,
        transaction_type=transaction_type,
        investment_amount=investment_amount,
        purchase_units=purchase_units,
        record_id=record_id,
    )

    with get_connection() as conn:
        row = conn.execute(
            """
            UPDATE portfolio_records
            SET
                purchase_date = %s,
                share_code = %s,
                transaction_type = %s,
                investment_amount = %s,
                purchase_units = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING id
            """,
            (purchase_date, share_code, transaction_type, investment_amount, purchase_units, record_id),
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
            _base_record_select()
            + """
            ORDER BY UPPER(TRIM(share_code)), purchase_date ASC, id ASC
            """
        ).fetchall()

    grouped: dict[str, dict[str, Any]] = {}

    for raw in rows:
        row = clean_row(dict(raw))
        share_code = str(row["share_code"]).upper()
        tx_type = _normalise_transaction_type(row.get("transaction_type"))
        amount = float(row.get("investment_amount") or 0)
        units = float(row.get("purchase_units") or 0)

        if share_code not in grouped:
            grouped[share_code] = {
                "share_code": share_code,
                "total_buy_amount": 0.0,
                "total_sell_amount": 0.0,
                "buy_units": 0.0,
                "sell_units": 0.0,
                "remaining_units": 0.0,
                "cost_basis": 0.0,
                "realized_return": 0.0,
                "transaction_count": 0,
            }

        item = grouped[share_code]
        item["transaction_count"] += 1

        if tx_type == "BUY":
            item["total_buy_amount"] += amount
            item["buy_units"] += units
            item["remaining_units"] += units
            item["cost_basis"] += amount
        else:
            item["total_sell_amount"] += amount
            item["sell_units"] += units

            if item["remaining_units"] > 0:
                sell_units = min(units, item["remaining_units"])
                average_cost = item["cost_basis"] / item["remaining_units"]
                sold_cost = average_cost * sell_units
                item["realized_return"] += amount - sold_cost
                item["remaining_units"] -= sell_units
                item["cost_basis"] -= sold_cost

                if abs(item["remaining_units"]) < 0.00000001:
                    item["remaining_units"] = 0.0
                    item["cost_basis"] = 0.0

    output: list[dict[str, Any]] = []
    for share_code in sorted(grouped):
        item = grouped[share_code]
        remaining_units = float(item["remaining_units"])
        cost_basis = float(item["cost_basis"])
        total_buy_amount = float(item["total_buy_amount"])
        average_price = (cost_basis / remaining_units) if remaining_units > 0 else 0.0

        # Backward-compatible keys used by older UI/PDF names.
        item["total_invested"] = cost_basis
        item["total_units"] = remaining_units
        item["average_price"] = average_price
        item["return_percent_base"] = total_buy_amount
        output.append(item)

    return output


def ping_database() -> bool:
    ensure_schema()
    with get_connection() as conn:
        conn.execute("SELECT 1")
    return True
