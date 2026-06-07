from __future__ import annotations

import time
from urllib.parse import quote

import requests

from .config import PRICE_CACHE_SECONDS


# GoogleFinance-style exchange prefix -> Yahoo Finance suffix conversion.
# Add your own exchange mapping here when needed.
EXCHANGE_PREFIX_TO_YAHOO_SUFFIX = {
    "NASDAQ": "",
    "NYSE": "",
    "AMEX": "",
    "ASX": ".AX",
    "HKG": ".HK",
    "HKEX": ".HK",
    "SGX": ".SI",
    "KLSE": ".KL",
    "BURSA": ".KL",
    "LON": ".L",
    "TSE": ".TO",
    "TSX": ".TO",
}

# Some short codes are ambiguous on Yahoo Finance.
SYMBOL_OVERRIDES = {
    # Telix Pharmaceuticals on ASX. Change to "TLX" if you intentionally want a US ticker.
    "TLX": "TLX.AX",
}

_quote_cache: dict[str, dict] = {}


def normalize_share_code(raw_code: str) -> str:
    return raw_code.strip().upper()


def to_yahoo_symbol(raw_code: str) -> str:
    code = normalize_share_code(raw_code)

    if ":" in code:
        exchange, ticker = code.split(":", 1)
        suffix = EXCHANGE_PREFIX_TO_YAHOO_SUFFIX.get(exchange, "")
        return f"{ticker}{suffix}"

    return SYMBOL_OVERRIDES.get(code, code)


def fetch_market_price(raw_code: str) -> dict:
    code = normalize_share_code(raw_code)
    yahoo_symbol = to_yahoo_symbol(code)

    now = time.time()
    cached = _quote_cache.get(yahoo_symbol)
    if cached and (now - cached["cached_at"] < PRICE_CACHE_SECONDS):
        return {**cached["data"], "cached": True}

    data = _fetch_from_yahoo_chart(code, yahoo_symbol)
    _quote_cache[yahoo_symbol] = {
        "cached_at": now,
        "data": data,
    }
    return {**data, "cached": False}


def _fetch_from_yahoo_chart(code: str, yahoo_symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(yahoo_symbol)}"
    params = {
        "range": "1d",
        "interval": "1m",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 portfolio-dashboard/1.0",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()

        chart = payload.get("chart", {})
        error = chart.get("error")
        if error:
            return _error_quote(code, yahoo_symbol, str(error))

        results = chart.get("result") or []
        if not results:
            return _error_quote(code, yahoo_symbol, "No market data returned.")

        meta = results[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose")
        currency = meta.get("currency") or ""

        if price is None:
            price = previous_close

        if price is None:
            return _error_quote(code, yahoo_symbol, "Price not available.")

        return {
            "share_code": code,
            "market_symbol": yahoo_symbol,
            "price": float(price),
            "currency": currency,
            "source": "yahoo_chart",
            "error": None,
        }
    except Exception as exc:
        return _error_quote(code, yahoo_symbol, str(exc))


def _error_quote(code: str, yahoo_symbol: str, message: str) -> dict:
    return {
        "share_code": code,
        "market_symbol": yahoo_symbol,
        "price": None,
        "currency": "",
        "source": "yahoo_chart",
        "error": message,
    }
