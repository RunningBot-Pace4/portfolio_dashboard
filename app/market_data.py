from __future__ import annotations

from urllib.parse import quote

import requests

from .config import PORTFOLIO_CURRENCY


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
    # Telix Pharmaceuticals on ASX. It returns AUD, then the app converts it to the portfolio currency.
    "TLX": "TLX.AX",
}



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
    """Fetch latest market price and convert it into the portfolio currency.

    No backend cache is used. Every dashboard/API refresh calls the market-data provider again.
    The UI and portfolio calculations use ``price`` in PORTFOLIO_CURRENCY.
    The original market quote is still returned as ``native_price`` and ``native_currency``.
    """
    code = normalize_share_code(raw_code)
    yahoo_symbol = to_yahoo_symbol(code)
    portfolio_currency = PORTFOLIO_CURRENCY

    return _fetch_from_yahoo_chart(code, yahoo_symbol, portfolio_currency)


def _fetch_from_yahoo_chart(code: str, yahoo_symbol: str, portfolio_currency: str) -> dict:
    try:
        meta = _fetch_chart_meta(yahoo_symbol)
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose")
        native_currency = str(meta.get("currency") or portfolio_currency or "USD").upper()
        display_name = meta.get("longName") or meta.get("shortName") or code
        change_percent = meta.get("regularMarketChangePercent")

        if price is None:
            price = previous_close

        if price is None:
            return _error_quote(code, yahoo_symbol, "Price not available.", portfolio_currency)

        if change_percent is None and previous_close not in (None, 0):
            change_percent = ((float(price) - float(previous_close)) / float(previous_close)) * 100.0

        native_price, native_currency = _normalise_native_price(float(price), native_currency)
        converted_price = native_price
        fx_rate = 1.0
        fx_symbol = None
        conversion_error = None
        converted = False

        if native_currency and native_currency != portfolio_currency:
            fx = _fetch_fx_rate(native_currency, portfolio_currency)
            fx_rate = fx.get("rate")
            fx_symbol = fx.get("symbol")
            conversion_error = fx.get("error")

            if fx_rate is None:
                return {
                    "share_code": code,
                    "market_symbol": yahoo_symbol,
                    "price": None,
                    "currency": portfolio_currency,
                    "native_price": native_price,
                    "native_currency": native_currency,
                    "fx_rate": None,
                    "fx_symbol": fx_symbol,
                    "converted": False,
                    "conversion_error": conversion_error,
                    "source": "yahoo_chart",
                    "error": f"Could not convert {native_currency} to {portfolio_currency}: {conversion_error}",
                }

            converted_price = native_price * float(fx_rate)
            converted = True

        return {
            "share_code": code,
            "market_symbol": yahoo_symbol,
            "display_name": display_name,
            "change_percent": float(change_percent) if change_percent is not None else None,
            "price": float(converted_price),
            "currency": portfolio_currency,
            "native_price": float(native_price),
            "native_currency": native_currency,
            "fx_rate": float(fx_rate) if fx_rate is not None else None,
            "fx_symbol": fx_symbol,
            "converted": converted,
            "conversion_error": conversion_error,
            "source": "yahoo_chart",
            "error": None,
        }
    except Exception as exc:
        return _error_quote(code, yahoo_symbol, str(exc), portfolio_currency)


def _fetch_chart_meta(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
    params = {
        "range": "1d",
        "interval": "1m",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 portfolio-dashboard/1.0",
        "Accept": "application/json",
    }

    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    payload = response.json()

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(str(error))

    results = chart.get("result") or []
    if not results:
        raise RuntimeError("No market data returned.")

    return results[0].get("meta", {})


def _normalise_native_price(price: float, currency: str) -> tuple[float, str]:
    """Normalise quote currencies that are not full currency units.

    Yahoo commonly returns London prices in GBp/GBX, meaning pence instead of GBP.
    """
    cleaned = (currency or "").strip()
    if cleaned in {"GBp", "GBX"}:
        return price / 100.0, "GBP"
    return price, cleaned.upper()


def _fetch_fx_rate(from_currency: str, to_currency: str) -> dict:
    from_currency = from_currency.strip().upper()
    to_currency = to_currency.strip().upper()

    if not from_currency or not to_currency or from_currency == to_currency:
        return {"rate": 1.0, "symbol": None, "error": None}

    direct_symbol = f"{from_currency}{to_currency}=X"
    direct = _fetch_fx_symbol(direct_symbol)
    if direct.get("rate") is not None:
        return {"rate": direct["rate"], "symbol": direct_symbol, "error": None}

    inverse_symbol = f"{to_currency}{from_currency}=X"
    inverse = _fetch_fx_symbol(inverse_symbol)
    if inverse.get("rate") not in (None, 0):
        return {"rate": 1.0 / float(inverse["rate"]), "symbol": inverse_symbol, "error": None}

    return {
        "rate": None,
        "symbol": direct_symbol,
        "error": direct.get("error") or inverse.get("error") or "FX rate not available.",
    }


def _fetch_fx_symbol(symbol: str) -> dict:
    try:
        meta = _fetch_chart_meta(symbol)
        rate = meta.get("regularMarketPrice")
        if rate is None:
            rate = meta.get("previousClose")
        if rate is None:
            return {"rate": None, "error": "FX price not available."}
        return {"rate": float(rate), "error": None}
    except Exception as exc:
        return {"rate": None, "error": str(exc)}


def _error_quote(code: str, yahoo_symbol: str, message: str, portfolio_currency: str) -> dict:
    return {
        "share_code": code,
        "market_symbol": yahoo_symbol,
        "display_name": code,
        "change_percent": None,
        "price": None,
        "currency": portfolio_currency,
        "native_price": None,
        "native_currency": "",
        "fx_rate": None,
        "fx_symbol": None,
        "converted": False,
        "conversion_error": None,
        "source": "yahoo_chart",
        "error": message,
    }
