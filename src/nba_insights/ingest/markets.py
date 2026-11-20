"""NBA game-winner prices from Kalshi and Polymarket public market data.

Both exchanges publish read-only market data without authentication:

- Kalshi lists one binary market per team per game in the ``KXNBAGAME``
  series (tickers like ``KXNBAGAME-26NOV19GSWMEM-MEM``: date, away+home
  tricodes, then the team the market pays out on).
- Polymarket's Gamma API lists one event per game in a per-season series
  (slug ``nba-<start year>``); its ``moneyline`` market prices both teams.

:func:`decode_kalshi` and :func:`decode_polymarket` are the pure flattening
steps (kept separate so tests stay offline); the ``fetch_*`` functions do the
network calls. Both return one row per game with the home team's price as a
probability in [0, 1].

Prices are for personal research (scoring the outcome model against the
market). Check each exchange's API terms before exposing them anywhere public;
like scraped contracts, they stay out of the public API/PWA.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import pandas as pd

KALSHI_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
KALSHI_NBA_SERIES = "KXNBAGAME"
POLYMARKET_API = "https://gamma-api.polymarket.com"
_PAGE = 50  # Gamma serves pages above 50 only gzip-compressed
_MAX_PAGES = 40

COLUMNS = [
    "SOURCE",
    "MARKET_ID",
    "GAME_DATE",
    "AWAY",
    "HOME",
    "HOME_PRICE",
    "HOME_BID",
    "HOME_ASK",
    "VOLUME",
]

# KXNBAGAME-26NOV19GSWMEM: yy, month, day, away tricode, home tricode
_KALSHI_EVENT = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})$")


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _mid(bid: float | None, ask: float | None, last: float | None) -> float | None:
    """Midpoint of a two-sided quote, else the last trade, else None.

    A side quoted at 0 (or an ask at 1) means no resting order on that
    side, so a one-sided book falls back to the last trade price.
    """
    if bid is not None and ask is not None and 0 < bid <= ask < 1:
        return round((bid + ask) / 2, 4)
    if last is not None and 0 < last < 1:
        return last
    return None


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.dropna(subset=["HOME_PRICE"]).reset_index(drop=True)


def decode_kalshi(markets: list[dict]) -> pd.DataFrame:
    """One row per game from Kalshi ``KXNBAGAME`` market records.

    Uses the home team's market (yes = home wins). Markets whose event
    ticker doesn't parse are skipped; a payload with markets but no
    parseable game raises ValueError so the cache keeps its last good copy.
    """
    rows = []
    for market in markets:
        match = _KALSHI_EVENT.search(market.get("event_ticker") or "")
        if not match:
            continue
        yy, mon, dd, away, home = match.groups()
        if (market.get("ticker") or "").rsplit("-", 1)[-1] != home:
            continue  # the away team's market mirrors the home one
        game_date = datetime.strptime(f"20{yy}{mon}{dd}", "%Y%b%d").date().isoformat()
        bid = _float(market.get("yes_bid_dollars"))
        ask = _float(market.get("yes_ask_dollars"))
        rows.append(
            {
                "SOURCE": "kalshi",
                "MARKET_ID": market["event_ticker"],
                "GAME_DATE": game_date,
                "AWAY": away,
                "HOME": home,
                "HOME_PRICE": _mid(bid, ask, _float(market.get("last_price_dollars"))),
                "HOME_BID": bid or None,
                "HOME_ASK": ask if ask and ask < 1 else None,
                "VOLUME": _float(market.get("volume_fp")),
            }
        )
    if markets and not rows:
        raise ValueError("no parseable KXNBAGAME markets in Kalshi payload")
    return _frame(rows)


def _json_list(value) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value or [])


def decode_polymarket(events: list[dict]) -> pd.DataFrame:
    """One row per game from Polymarket NBA game events.

    Reads the event's ``moneyline`` market and its ``teams`` (which carry
    the home/away ordering and tricode); events without both are skipped.
    The market's best bid/ask quote its first outcome, so the home side's
    quote is mirrored when home is listed second.
    """
    rows = []
    for event in events:
        teams = {t.get("ordering"): t for t in event.get("teams") or []}
        moneyline = [
            m for m in event.get("markets") or [] if m.get("sportsMarketType") == "moneyline"
        ]
        if not moneyline or not {"home", "away"} <= set(teams):
            continue
        market = moneyline[0]
        outcomes = _json_list(market.get("outcomes"))
        prices = [_float(p) for p in _json_list(market.get("outcomePrices"))]
        home_name = teams["home"].get("name")
        if home_name not in outcomes or len(prices) != len(outcomes):
            continue
        home_first = outcomes.index(home_name) == 0
        bid, ask = _float(market.get("bestBid")), _float(market.get("bestAsk"))
        if not home_first:
            bid, ask = (1 - ask if ask else None), (1 - bid if bid else None)
        home_price = _mid(bid, ask, prices[outcomes.index(home_name)])
        rows.append(
            {
                "SOURCE": "polymarket",
                "MARKET_ID": event.get("slug"),
                "GAME_DATE": event.get("eventDate"),
                "AWAY": str(teams["away"].get("abbreviation", "")).upper(),
                "HOME": str(teams["home"].get("abbreviation", "")).upper(),
                "HOME_PRICE": home_price,
                "HOME_BID": round(bid, 4) if bid else None,
                "HOME_ASK": round(ask, 4) if ask and ask < 1 else None,
                "VOLUME": _float(market.get("volumeNum") or market.get("volume")),
            }
        )
    return _frame(rows)


def _stamped(prices: pd.DataFrame) -> pd.DataFrame:
    """Record when prices were fetched: the cache serves its last good copy
    when a refresh fails, and a stale quote must not pass as a fresh one."""
    return prices.assign(FETCHED_AT=pd.Timestamp.now("UTC"))


def _get(url: str, params: dict) -> Any:
    import requests

    response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_kalshi_nba() -> pd.DataFrame:
    """Every open Kalshi NBA game-winner market (network, paginated)."""
    markets: list[dict] = []
    cursor = ""
    for _ in range(_MAX_PAGES):
        params = {"series_ticker": KALSHI_NBA_SERIES, "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        page = _get(KALSHI_MARKETS_URL, params)
        markets.extend(page.get("markets") or [])
        cursor = page.get("cursor") or ""
        if not cursor:
            break
    return _stamped(decode_kalshi(markets))


def polymarket_series_slug(season: str) -> str:
    """Gamma series slug for an NBA season ("2026-27" -> "nba-2026")."""
    return f"nba-{season[:4]}"


def fetch_polymarket_nba(season: str) -> pd.DataFrame:
    """Every open Polymarket NBA game event for *season* (network, paginated)."""
    series = _get(f"{POLYMARKET_API}/series", {"slug": polymarket_series_slug(season)})
    if not series:
        raise ValueError(f"no Polymarket series for {season}")
    events: list[dict] = []
    for page in range(_MAX_PAGES):
        batch = _get(
            f"{POLYMARKET_API}/events",
            {
                "series_id": series[0]["id"],
                "closed": "false",
                "limit": _PAGE,
                "offset": page * _PAGE,
            },
        )
        events.extend(batch)
        if len(batch) < _PAGE:
            break
    return _stamped(decode_polymarket(events))
