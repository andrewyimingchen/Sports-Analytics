"""Player contract data scraped from Basketball-Reference.

Owner decision 2026-07-16 (see CLAUDE.md): scraping is permitted at
minimal volume for personal/educational use — this module reads exactly
one summary page (every current contract, seasons forward) and the
client caches it for a week. Scraped data must never be exposed through
the public API/PWA or redistributed; license the data for anything
commercial.

:func:`parse_contracts` is the pure HTML→DataFrame step, kept separate
from the network fetch so tests stay offline.
"""

from __future__ import annotations

import re
from io import StringIO

import pandas as pd

CONTRACTS_URL = "https://www.basketball-reference.com/contracts/players.html"

# B-Ref tricodes that differ from stats.nba.com's
_TEAM_FIX = {"BRK": "BKN", "PHO": "PHX", "CHO": "CHA"}

_SEASON_RE = re.compile(r"\d{4}-\d{2}")


def _money(col: pd.Series) -> pd.Series:
    """"$62,587,158" → 62587158.0 (NaN for blanks)."""
    return pd.to_numeric(
        col.astype("string").str.replace(r"[$,]", "", regex=True), errors="coerce"
    )


def parse_contracts(html: str) -> pd.DataFrame:
    """One row per player: team, per-season salary, and guaranteed total.

    Season columns keep their labels ("2026-27", …), values in dollars.
    B-Ref serves a two-level header and repeats the header row inside the
    body; both are stripped. Raises ValueError when the page shape isn't
    recognized, so the cache serves a stale copy instead of pinning junk.
    """
    try:
        table = pd.read_html(StringIO(html))[0]
    # ImportError: on a table-less page lxml gives up and pandas reaches
    # for the optional html5lib parser instead of raising ValueError
    except (ValueError, IndexError, ImportError) as e:
        raise ValueError("no contracts table found in page") from e
    if isinstance(table.columns, pd.MultiIndex):
        table.columns = [c[-1] for c in table.columns]
    if "Player" not in table.columns or "Tm" not in table.columns:
        raise ValueError(f"unexpected contracts table columns: {list(table.columns)}")
    table = table[table["Player"].notna() & (table["Player"] != "Player")]

    seasons = [c for c in table.columns if _SEASON_RE.fullmatch(str(c))]
    if not seasons:
        raise ValueError("no season salary columns found")
    out = pd.DataFrame(
        {
            "PLAYER_NAME": table["Player"].astype(str),
            "TEAM_ABBREVIATION": table["Tm"].astype(str).replace(_TEAM_FIX),
        }
    )
    for season in seasons:
        out[season] = _money(table[season]).values
    if "Guaranteed" in table.columns:
        out["GUARANTEED"] = _money(table["Guaranteed"]).values
    return out.reset_index(drop=True)


def fetch_contracts() -> pd.DataFrame:
    """Download and parse the contracts summary page (network, one page)."""
    import requests

    r = requests.get(
        CONTRACTS_URL, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}, timeout=30
    )
    r.raise_for_status()
    # B-Ref omits the charset header; without this, requests decodes as
    # latin-1 and every diacritic name breaks the league-table join
    r.encoding = "utf-8"
    return parse_contracts(r.text)
