import os

# No hardcoded watchlist. The app builds the market dashboard from share codes saved in Neon.
# New symbols can be searched from Yahoo Finance in the Add/Edit form.
DEFAULT_SHARE_CODES: list[str] = []

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PORTFOLIO_CURRENCY = os.getenv("PORTFOLIO_CURRENCY", "USD").strip().upper() or "USD"
BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "").strip()
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "").strip()

# Market prices are always fetched live. No backend quote cache is used.


def auth_is_enabled() -> bool:
    return bool(BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD)
