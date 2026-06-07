from __future__ import annotations

import base64
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse

import requests
from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - lets local SQLite mode run even before psycopg is installed
    psycopg = None
    dict_row = None


load_dotenv()

APP_TITLE = "Share Portfolio Dashboard"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "data/portfolio.db")
PRICE_CACHE_SECONDS = int(os.getenv("PRICE_CACHE_SECONDS", "300"))

# Optional: set both environment variables in Vercel to protect the public URL.
BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "").strip()
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "").strip()

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
price_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=512, ttl=PRICE_CACHE_SECONDS)
security = HTTPBasic(auto_error=False)


# Default live dashboard symbols from your screenshot.
WATCHLIST_SYMBOLS = [
    "NVDA",
    "ORCL",
    "GOOGL",
    "NU",
    "GRAB",
    "TSM",
    "HROW",
    "SAIL",
    "TLX",
    "META",
    "MSFT",
    "AVGO",
    "GLDM",
]

COMMON_SYMBOLS = WATCHLIST_SYMBOLS + [
    "GOOG", "AAPL", "AMZN", "TSLA", "AMD", "PLTR", "NFLX", "BABA",
    "V", "MA", "JPM", "KO", "PEP", "DIS", "NKE", "MCD", "COST", "WMT",
    "0700.HK", "9988.HK", "3690.HK", "1810.HK", "9618.HK",
    "D05.SI", "O39.SI", "U11.SI", "C6L.SI",
    "MAYBANK.KL", "CIMB.KL", "PBBANK.KL", "TENAGA.KL",
    "TLX.AX",
]

# Accept Yahoo-style symbols and common Google Finance-style exchange prefixes.
# Examples:
#   NASDAQ:NVDA  -> NVDA
#   NYSE:ORCL    -> ORCL
#   HKG:0700     -> 0700.HK
#   SGX:D05      -> D05.SI
#   KLSE:MAYBANK -> MAYBANK.KL
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^:]{0,29}$")

GOOGLE_TO_YAHOO_EXCHANGE_SUFFIX = {
    "NASDAQ": "",
    "NASD": "",
    "NYSE": "",
    "NYSEARCA": "",
    "AMEX": "",
    "HKG": ".HK",
    "HKEX": ".HK",
    "HK": ".HK",
    "SGX": ".SI",
    "KLSE": ".KL",
    "BURSA": ".KL",
    "ASX": ".AX",
    "TYO": ".T",
    "TSEJ": ".T",
    "TSE": ".TO",
    "TSX": ".TO",
    "CVE": ".V",
    "LON": ".L",
    "EPA": ".PA",
    "PAR": ".PA",
    "ETR": ".DE",
    "FRA": ".F",
    "NSE": ".NS",
    "BOM": ".BO",
    "BSE": ".BO",
    "TPE": ".TW",
}

# Some popular tickers are ambiguous without an exchange suffix.
SYMBOL_ALIASES = {
    "TLX": "TLX.AX",  # Telix Pharmaceuticals on ASX
}


class TransactionIn(BaseModel):
    purchase_date: str = Field(..., min_length=8, max_length=10)
    symbol: str = Field(..., min_length=1, max_length=30)
    investment_amount: float = Field(..., gt=0)
    purchase_units: float = Field(..., gt=0)

    @field_validator("purchase_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Date must use YYYY-MM-DD format") from exc
        return value

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        symbol = normalize_symbol(value)
        if not SYMBOL_RE.match(symbol):
            raise ValueError("Invalid share code")
        return symbol


def require_basic_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    """Protect the public Vercel URL when BASIC_AUTH_USERNAME/PASSWORD are set."""
    if not BASIC_AUTH_USERNAME and not BASIC_AUTH_PASSWORD:
        return

    if not credentials:
        raise_auth_required()

    username_ok = constant_time_compare(credentials.username, BASIC_AUTH_USERNAME)
    password_ok = constant_time_compare(credentials.password, BASIC_AUTH_PASSWORD)

    if not (username_ok and password_ok):
        raise_auth_required()


def constant_time_compare(value: str, expected: str) -> bool:
    # Avoid importing secrets for very old Python runtimes; hmac is standard and constant time.
    import hmac

    return hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def raise_auth_required() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Basic"},
    )


def normalize_symbol(value: str) -> str:
    """Convert common Google Finance symbols to Yahoo Finance symbols."""
    raw = value.strip().upper()

    # If user pastes =GOOGLEFINANCE("NASDAQ:NVDA","price"), extract NASDAQ:NVDA.
    quoted = re.search(r"""['"]([A-Z0-9._:\-=^]+)['"]""", raw)
    if quoted:
        raw = quoted.group(1)

    raw = raw.replace(" ", "")

    if raw in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[raw]

    if ":" not in raw:
        return SYMBOL_ALIASES.get(raw, raw)

    exchange, code = raw.split(":", 1)
    exchange = exchange.strip()
    code = code.strip()

    if not exchange or not code:
        return raw

    suffix = GOOGLE_TO_YAHOO_EXCHANGE_SUFFIX.get(exchange)

    # Unknown Google exchange; remove prefix as a best effort for US-style tickers.
    if suffix is None:
        return SYMBOL_ALIASES.get(code, code)

    # Yahoo Hong Kong tickers are normally 4 digits, e.g. 700 -> 0700.HK.
    if suffix == ".HK" and code.isdigit():
        code = code.zfill(4)

    return SYMBOL_ALIASES.get(f"{code}{suffix}", f"{code}{suffix}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def money(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "-"
    return f"${value:,.2f}"


def number(value: float | None, decimals: int = 4) -> str:
    if value is None or not math.isfinite(value):
        return "-"
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")


def pct(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "-"
    return f"{value:,.2f}%"


def using_postgres() -> bool:
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


def database_label() -> str:
    if using_postgres():
        parsed = urlparse(DATABASE_URL)
        return f"Neon Postgres: {parsed.hostname or 'configured'}"
    return f"Local SQLite: {SQLITE_DB_PATH}"


@contextmanager
def get_conn() -> Generator[Any, None, None]:
    """
    Use Neon Postgres when DATABASE_URL is configured.
    Fall back to SQLite for local development only.
    """
    if using_postgres():
        if psycopg is None:
            raise RuntimeError("psycopg is not installed. Run: pip install 'psycopg[binary]'")
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
        return

    Path(SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def execute(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    """Execute SQL with the right placeholder style for Postgres or SQLite."""
    if using_postgres():
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def init_db() -> None:
    with get_conn() as conn:
        if using_postgres():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    purchase_date DATE NOT NULL,
                    symbol TEXT NOT NULL,
                    investment_amount NUMERIC(18, 6) NOT NULL CHECK (investment_amount > 0),
                    purchase_units NUMERIC(18, 6) NOT NULL CHECK (purchase_units > 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    investment_amount REAL NOT NULL CHECK (investment_amount > 0),
                    purchase_units REAL NOT NULL CHECK (purchase_units > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_symbol ON transactions(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(purchase_date)")


app = FastAPI(title=APP_TITLE)


@app.on_event("startup")
def startup() -> None:
    init_db()


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not isinstance(row, dict):
        row = dict(row)

    purchase_date = row["purchase_date"]
    if hasattr(purchase_date, "isoformat"):
        purchase_date = purchase_date.isoformat()

    created_at = row["created_at"]
    updated_at = row["updated_at"]
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat(timespec="seconds")
    if hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat(timespec="seconds")

    return {
        "id": int(row["id"]),
        "purchase_date": str(purchase_date),
        "symbol": str(row["symbol"]),
        "investment_amount": float(row["investment_amount"]),
        "purchase_units": float(row["purchase_units"]),
        "created_at": str(created_at),
        "updated_at": str(updated_at),
    }


def list_transactions() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
            FROM transactions
            ORDER BY purchase_date DESC, id DESC
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_owned_symbols() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT symbol FROM transactions ORDER BY symbol").fetchall()
    if using_postgres():
        return [row["symbol"] for row in rows]
    return [row["symbol"] for row in rows]


def create_transaction(payload: TransactionIn) -> dict[str, Any]:
    timestamp = now_iso()
    symbol = normalize_symbol(payload.symbol)

    with get_conn() as conn:
        if using_postgres():
            duplicate = conn.execute(
                """
                SELECT id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
                FROM transactions
                WHERE purchase_date = %s::date
                  AND symbol = %s
                  AND ABS(investment_amount - %s) < 0.000001
                  AND ABS(purchase_units - %s) < 0.000001
                  AND created_at >= NOW() - INTERVAL '15 seconds'
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    payload.purchase_date,
                    symbol,
                    payload.investment_amount,
                    payload.purchase_units,
                ),
            ).fetchone()
        else:
            duplicate = conn.execute(
                """
                SELECT id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
                FROM transactions
                WHERE purchase_date = ?
                  AND symbol = ?
                  AND ABS(investment_amount - ?) < 0.000001
                  AND ABS(purchase_units - ?) < 0.000001
                  AND created_at >= datetime('now', '-15 seconds')
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    payload.purchase_date,
                    symbol,
                    payload.investment_amount,
                    payload.purchase_units,
                ),
            ).fetchone()

        if duplicate:
            return row_to_dict(duplicate)

        if using_postgres():
            row = conn.execute(
                """
                INSERT INTO transactions
                    (purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at)
                VALUES (%s::date, %s, %s, %s, NOW(), NOW())
                RETURNING id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
                """,
                (
                    payload.purchase_date,
                    symbol,
                    payload.investment_amount,
                    payload.purchase_units,
                ),
            ).fetchone()
        else:
            cur = conn.execute(
                """
                INSERT INTO transactions
                    (purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.purchase_date,
                    symbol,
                    payload.investment_amount,
                    payload.purchase_units,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                """
                SELECT id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
                FROM transactions
                WHERE id = ?
                """,
                (cur.lastrowid,),
            ).fetchone()

    return row_to_dict(row)


def update_transaction(transaction_id: int, payload: TransactionIn) -> dict[str, Any]:
    timestamp = now_iso()
    symbol = normalize_symbol(payload.symbol)

    with get_conn() as conn:
        if using_postgres():
            row = conn.execute(
                """
                UPDATE transactions
                SET purchase_date = %s::date,
                    symbol = %s,
                    investment_amount = %s,
                    purchase_units = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
                """,
                (
                    payload.purchase_date,
                    symbol,
                    payload.investment_amount,
                    payload.purchase_units,
                    transaction_id,
                ),
            ).fetchone()
        else:
            result = conn.execute(
                """
                UPDATE transactions
                SET purchase_date = ?, symbol = ?, investment_amount = ?, purchase_units = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.purchase_date,
                    symbol,
                    payload.investment_amount,
                    payload.purchase_units,
                    timestamp,
                    transaction_id,
                ),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Transaction not found")
            row = conn.execute(
                """
                SELECT id, purchase_date, symbol, investment_amount, purchase_units, created_at, updated_at
                FROM transactions
                WHERE id = ?
                """,
                (transaction_id,),
            ).fetchone()

    return row_to_dict(row)


def delete_transaction(transaction_id: int) -> None:
    with get_conn() as conn:
        result = execute(conn, "DELETE FROM transactions WHERE id = ?", (transaction_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Transaction not found")


def fetch_price_from_yahoo_chart(symbol: str) -> tuple[float | None, str | None, str | None]:
    """
    Lightweight market quote lookup.

    It intentionally avoids yfinance/pandas so the Vercel function bundle stays small.
    For official trading-grade prices, replace this with a paid market-data API.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = requests.get(
        url,
        params={"range": "5d", "interval": "1d"},
        headers={"User-Agent": "Mozilla/5.0 portfolio-dashboard"},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        return None, None, error.get("description") or str(error)

    result = (chart.get("result") or [None])[0]
    if not result:
        return None, None, "No quote result returned"

    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    currency = meta.get("currency")

    if price is None:
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        closes = [x for x in quote.get("close", []) if x is not None]
        if closes:
            price = closes[-1]

    return (float(price), currency, None) if price is not None else (None, currency, "No price returned")


def fetch_market_price(symbol: str) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    if symbol in price_cache:
        return price_cache[symbol]

    result = {
        "symbol": symbol,
        "price": None,
        "currency": None,
        "source": "Yahoo Finance chart endpoint",
        "error": None,
        "updated_at": now_iso(),
    }

    try:
        price, currency, error = fetch_price_from_yahoo_chart(symbol)
        if price is not None and math.isfinite(float(price)):
            result["price"] = float(price)
            result["currency"] = currency
            price_cache[symbol] = result
            return result

        result["currency"] = currency
        result["error"] = (
            f"Could not fetch price for {symbol}. "
            "Check that the share code is Yahoo Finance format, e.g. NVDA, GOOGL, 0700.HK, D05.SI, MAYBANK.KL. "
            f"Details: {error or 'No price returned'}"
        )
    except Exception as exc:
        result["error"] = (
            f"Could not fetch price for {symbol}. "
            "Check that Vercel can access the internet and that the share code exists. "
            f"Details: {exc}"
        )

    price_cache[symbol] = result
    return result


def enrich_transaction(tx: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    units = tx["purchase_units"]
    invested = tx["investment_amount"]
    avg_price = invested / units if units else None
    market_price = quote.get("price")
    current_value = market_price * units if market_price is not None else None
    total_earn = current_value - invested if current_value is not None else None
    return_pct = (total_earn / invested * 100) if total_earn is not None and invested else None

    return {
        **tx,
        "average_price": avg_price,
        "current_market_price": market_price,
        "current_value": current_value,
        "total_earn": total_earn,
        "return_pct": return_pct,
        "currency": quote.get("currency"),
        "price_error": quote.get("error"),
        "investment_amount_fmt": money(invested),
        "purchase_units_fmt": number(units),
        "average_price_fmt": money(avg_price),
        "current_market_price_fmt": money(market_price),
        "current_value_fmt": money(current_value),
        "total_earn_fmt": money(total_earn),
        "return_pct_fmt": pct(return_pct),
    }


def build_watchlist(quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for display_symbol in WATCHLIST_SYMBOLS:
        lookup_symbol = normalize_symbol(display_symbol)
        quote = quotes.get(lookup_symbol) or fetch_market_price(lookup_symbol)
        price = quote.get("price")
        rows.append(
            {
                "display_symbol": display_symbol,
                "lookup_symbol": lookup_symbol,
                "current_market_price": price,
                "current_market_price_fmt": money(price),
                "currency": quote.get("currency"),
                "updated_at": quote.get("updated_at"),
                "price_error": quote.get("error"),
            }
        )
    return rows


def build_portfolio() -> dict[str, Any]:
    transactions = list_transactions()
    transaction_symbols = sorted({tx["symbol"] for tx in transactions})
    watchlist_lookup_symbols = sorted({normalize_symbol(symbol) for symbol in WATCHLIST_SYMBOLS})
    all_quote_symbols = sorted(set(transaction_symbols + watchlist_lookup_symbols))
    quotes = {symbol: fetch_market_price(symbol) for symbol in all_quote_symbols}

    enriched = [enrich_transaction(tx, quotes.get(tx["symbol"], {})) for tx in transactions]

    total_invested = sum(tx["investment_amount"] for tx in enriched)
    total_units = sum(tx["purchase_units"] for tx in enriched)
    current_value_values = [tx["current_value"] for tx in enriched if tx["current_value"] is not None]
    total_current_value = sum(current_value_values)
    total_earn = total_current_value - total_invested if current_value_values else None
    total_return_pct = (total_earn / total_invested * 100) if total_earn is not None and total_invested else None

    holdings_map: dict[str, dict[str, Any]] = {}
    for tx in enriched:
        symbol = tx["symbol"]
        if symbol not in holdings_map:
            holdings_map[symbol] = {
                "symbol": symbol,
                "investment_amount": 0.0,
                "purchase_units": 0.0,
                "current_market_price": tx["current_market_price"],
                "currency": tx["currency"],
                "price_error": tx["price_error"],
            }
        holdings_map[symbol]["investment_amount"] += tx["investment_amount"]
        holdings_map[symbol]["purchase_units"] += tx["purchase_units"]

    holdings = []
    for holding in holdings_map.values():
        invested = holding["investment_amount"]
        units = holding["purchase_units"]
        market_price = holding["current_market_price"]
        avg_price = invested / units if units else None
        current_value = market_price * units if market_price is not None else None
        total_earn_holding = current_value - invested if current_value is not None else None
        return_pct_holding = (
            total_earn_holding / invested * 100
            if total_earn_holding is not None and invested
            else None
        )
        holdings.append(
            {
                **holding,
                "average_price": avg_price,
                "current_value": current_value,
                "total_earn": total_earn_holding,
                "return_pct": return_pct_holding,
                "investment_amount_fmt": money(invested),
                "purchase_units_fmt": number(units),
                "average_price_fmt": money(avg_price),
                "current_market_price_fmt": money(market_price),
                "current_value_fmt": money(current_value),
                "total_earn_fmt": money(total_earn_holding),
                "return_pct_fmt": pct(return_pct_holding),
            }
        )
    holdings.sort(key=lambda x: x["investment_amount"], reverse=True)

    watchlist = build_watchlist(quotes)
    errors = [q["error"] for q in quotes.values() if q.get("error")]

    available_symbols = sorted(set(COMMON_SYMBOLS + transaction_symbols))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price_cache_seconds": PRICE_CACHE_SECONDS,
        "database": database_label(),
        "using_postgres": using_postgres(),
        "summary": {
            "total_records": len(enriched),
            "total_symbols": len(transaction_symbols),
            "total_units": total_units,
            "total_invested": total_invested,
            "total_current_value": total_current_value if current_value_values else None,
            "total_earn": total_earn,
            "total_return_pct": total_return_pct,
            "total_units_fmt": number(total_units),
            "total_invested_fmt": money(total_invested),
            "total_current_value_fmt": money(total_current_value if current_value_values else None),
            "total_earn_fmt": money(total_earn),
            "total_return_pct_fmt": pct(total_return_pct),
        },
        "symbols": available_symbols,
        "watchlist": watchlist,
        "holdings": holdings,
        "transactions": enriched,
        "errors": errors,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(require_basic_auth)) -> HTMLResponse:
    portfolio = build_portfolio()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"title": APP_TITLE, "portfolio": portfolio},
    )


@app.get("/api/portfolio")
def api_portfolio(_: None = Depends(require_basic_auth)) -> JSONResponse:
    return JSONResponse(build_portfolio())


@app.get("/api/watchlist")
def api_watchlist(_: None = Depends(require_basic_auth)) -> JSONResponse:
    portfolio = build_portfolio()
    return JSONResponse({"watchlist": portfolio["watchlist"], "generated_at": portfolio["generated_at"]})


@app.get("/api/symbols")
def api_symbols(q: str = "", _: None = Depends(require_basic_auth)) -> JSONResponse:
    q_upper = q.strip().upper()
    symbols = sorted(set(COMMON_SYMBOLS + get_owned_symbols()))
    if q_upper:
        symbols = [symbol for symbol in symbols if q_upper in symbol]
    return JSONResponse({"symbols": symbols[:50]})


@app.get("/api/quote/{symbol:path}")
def api_quote(symbol: str, _: None = Depends(require_basic_auth)) -> JSONResponse:
    symbol = normalize_symbol(symbol)
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Invalid share code")
    return JSONResponse(fetch_market_price(symbol))


@app.post("/api/transactions", status_code=201)
def api_create_transaction(payload: TransactionIn, _: None = Depends(require_basic_auth)) -> JSONResponse:
    return JSONResponse(create_transaction(payload), status_code=201)


@app.put("/api/transactions/{transaction_id}")
def api_update_transaction(
    transaction_id: int,
    payload: TransactionIn,
    _: None = Depends(require_basic_auth),
) -> JSONResponse:
    return JSONResponse(update_transaction(transaction_id, payload))


@app.delete("/api/transactions/{transaction_id}", status_code=204)
def api_delete_transaction(transaction_id: int, _: None = Depends(require_basic_auth)) -> Response:
    delete_transaction(transaction_id)
    return Response(status_code=204)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "database": "postgres" if using_postgres() else "sqlite",
        "auth": "enabled" if BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD else "disabled",
    }
