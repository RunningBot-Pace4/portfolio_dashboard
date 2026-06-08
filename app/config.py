import os

DEFAULT_SHARE_CODES = [
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

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "").strip()
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "").strip()

try:
    PRICE_CACHE_SECONDS = int(os.getenv("PRICE_CACHE_SECONDS", "120"))
except ValueError:
    PRICE_CACHE_SECONDS = 120


def auth_is_enabled() -> bool:
    return bool(BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD)
