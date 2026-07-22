"""Player contract data scraped from Basketball-Reference.

Owner decision 2026-07-16 (see CLAUDE.md): scraping is permitted at
minimal volume for personal/educational use — this module reads exactly
one summary page (every current contract, seasons forward) plus a player
page only when its local profile is opened. The client caches those pages
for a week/month respectively. Scraped data must never be exposed through
the public API/PWA or redistributed; license the data for anything
commercial.

:func:`parse_contracts` is the pure HTML→DataFrame step, kept separate
from the network fetch so tests stay offline.
"""

from __future__ import annotations

import re
from io import StringIO

import pandas as pd
from lxml import html as lxml_html

CONTRACTS_URL = "https://www.basketball-reference.com/contracts/players.html"
PLAYER_URL = "https://www.basketball-reference.com/players/{slug}"

# B-Ref tricodes that differ from stats.nba.com's
_TEAM_FIX = {"BRK": "BKN", "PHO": "PHX", "CHO": "CHA"}

_SEASON_RE = re.compile(r"\d{4}-\d{2}")
_PLAYER_SLUG_RE = re.compile(r"[a-z]/[a-z0-9]+\.html")


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
    slugs: dict[str, str] = {}
    try:
        root = lxml_html.fromstring(html)
        for cell in root.xpath('//tbody/tr/*[@data-stat="player"]'):
            hrefs = cell.xpath('.//a[starts-with(@href, "/players/")]/@href')
            if hrefs:
                slugs[" ".join(cell.text_content().split())] = hrefs[0].removeprefix(
                    "/players/"
                )
    except (ValueError, TypeError):
        pass

    out = pd.DataFrame(
        {
            "PLAYER_NAME": table["Player"].astype(str),
            "TEAM_ABBREVIATION": table["Tm"].astype(str).replace(_TEAM_FIX),
            "BREF_SLUG": table["Player"].astype(str).map(slugs),
        }
    )
    for season in seasons:
        out[season] = _money(table[season]).values
    if "Guaranteed" in table.columns:
        out["GUARANTEED"] = _money(table["Guaranteed"]).values
    return out.reset_index(drop=True)


def parse_career_salaries(html: str) -> pd.DataFrame:
    """Parse one player's complete salary history, including commented tables."""
    match = re.search(
        r'<table\b[^>]*\bid=["\']all_salaries["\'][\s\S]*?</table>',
        html,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("no career salaries table found in player page")
    try:
        table = pd.read_html(StringIO(match.group(0)))[0]
    except (ValueError, IndexError, ImportError) as error:
        raise ValueError("career salaries table could not be parsed") from error
    if isinstance(table.columns, pd.MultiIndex):
        table.columns = [column[-1] for column in table.columns]
    team_column = "Team" if "Team" in table.columns else "Tm"
    required = {"Season", team_column, "Salary"}
    if not required.issubset(table.columns):
        raise ValueError(f"unexpected career salary columns: {list(table.columns)}")
    rows = table[table["Season"].astype("string").str.fullmatch(_SEASON_RE.pattern, na=False)]
    if rows.empty:
        raise ValueError("no season salary rows found")
    return pd.DataFrame(
        {
            "SEASON": rows["Season"].astype(str),
            "TEAM": rows[team_column].astype(str),
            "SALARY": _money(rows["Salary"]).values,
        }
    ).reset_index(drop=True)


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


def fetch_career_salaries(slug: str) -> pd.DataFrame:
    """Download one player's salary table after validating its B-Ref path."""
    if not _PLAYER_SLUG_RE.fullmatch(slug):
        raise ValueError("invalid Basketball-Reference player slug")
    import requests

    response = requests.get(
        PLAYER_URL.format(slug=slug),
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_career_salaries(response.text)
