"""Best-effort links from Trading212 instrument codes to Trading212 web pages.

Trading212 publishes no deep-link format. The public instrument page pattern
``/trading-instruments/invest/<SYMBOL>.<COUNTRY>`` is confirmed for US shares
(e.g. ``BABA.US``); the country suffixes for other exchanges are guesses.
"""
from __future__ import annotations

import re

INSTRUMENT_PAGE_URL = "https://www.trading212.com/trading-instruments/invest/{symbol}.{country}"

# T212 code suffix (after the symbol, before "_EQ") -> instrument page country code
_EXCHANGE_COUNTRIES = {
    "_US": "US",
    "l": "UK",  # London Stock Exchange
    "d": "DE",  # Xetra
    "a": "NL",  # Euronext Amsterdam
    "p": "FR",  # Euronext Paris
    "e": "ES",  # Bolsa de Madrid
}

_T212_CODE = re.compile(r"^(?P<symbol>[A-Z0-9.]+?)(?P<exchange>_US|[a-z])_EQ$")


def instrument_url(t212_ticker: str) -> str | None:
    """Build the Trading212 instrument page URL for a T212 instrument code.

    Args:
        t212_ticker: Trading212 instrument code, e.g. ``"TSLA_US_EQ"`` or ``"RIOl_EQ"``.

    Returns:
        The instrument page URL, or None if the code's exchange is not recognised.
    """
    match = _T212_CODE.match(t212_ticker)
    if match is None:
        return None
    country = _EXCHANGE_COUNTRIES.get(match["exchange"])
    if country is None:
        return None
    return INSTRUMENT_PAGE_URL.format(symbol=match["symbol"], country=country)
