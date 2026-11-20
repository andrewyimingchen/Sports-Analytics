"""Official NBA injury reports (scraped; personal/educational use only).

The league publishes a game-availability report every 15 minutes on game
days as a PDF (``ak-static.cms.nba.com/referee/injury/Injury-Report_<date>
_<hh>_<mm><AM|PM>.pdf``, US Eastern time), and lists the day's reports on
an index page at official.nba.com. Scraping them is permitted by owner
decision (2026-11-19) under the CLAUDE.md guardrails: minimal volume (the
index page plus one PDF per report, both through ``Cache.get_or_fetch``),
personal/educational use, and never exposed through the public API/PWA.

The PDF is a borderless table. :func:`parse_injury_words` rebuilds it from
word positions (pure, so tests stay offline):

- columns come from the header row's x positions;
- each player row is anchored by the text in the Player Name column, and
  the game/matchup/team cells carry forward until the next one appears;
- a multi-line Reason is vertically centered on its row, so reason lines
  are grouped into blocks (line gap under ``_SAME_BLOCK``) and each block
  is given to the row it spans; a block spanning no row is the tail of a
  reason split across a page break and joins the previous row.
"""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO

import pandas as pd
from nba_api.stats.static import teams as static_teams

INDEX_URL = "https://official.nba.com/nba-injury-report-{season}-season/"
_REPORT_LINK = re.compile(
    r"https://ak-static\.cms\.nba\.com/referee/injury/"
    r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf"
)

COLUMNS = [
    "GAME_DATE",
    "GAME_TIME",
    "MATCHUP",
    "AWAY",
    "HOME",
    "TEAM",
    "PLAYER",
    "PLAYER_NAME",
    "STATUS",
    "REASON",
]

# header words that start each column, in table order
_HEADER = {
    "GAME_DATE": "Game",
    "GAME_TIME": "Game",
    "MATCHUP": "Matchup",
    "TEAM": "Team",
    "PLAYER": "Player",
    "STATUS": "Current",
    "REASON": "Reason",
}
_SAME_BLOCK = 18.0  # points; lines of one reason sit ~14pt apart, rows ~22+
_ROW_SLACK = 2.0
_NOT_SUBMITTED = "NOT YET SUBMITTED"


def report_links(html: str) -> pd.DataFrame:
    """Every injury-report PDF linked from the index page, oldest first.

    REPORT_AT is the report's naive US Eastern timestamp. Raises ValueError
    when the page links none (layout changed, or the season page moved), so
    the cache keeps serving its last good copy.
    """
    rows = {}
    for match in _REPORT_LINK.finditer(html):
        day, hour, minute, half = match.groups()
        stamp = datetime.strptime(f"{day} {hour}:{minute} {half}", "%Y-%m-%d %I:%M %p")
        rows[match.group(0)] = stamp
    if not rows:
        raise ValueError("no injury report links on the index page")
    links = pd.DataFrame({"URL": list(rows), "REPORT_AT": list(rows.values())})
    return links.sort_values("REPORT_AT", ignore_index=True)


def _column_starts(words: list[dict]) -> dict[str, float]:
    # header cells may arrive as phrases ("Game Date"): match the first token
    header = [
        {**w, "text": w["text"].split()[0]}
        for w in words
        if w["page"] == words[0]["page"] and w["text"].strip()
    ]
    starts: dict[str, float] = {}
    game_words = sorted(w["x0"] for w in header if w["text"] == "Game")
    for column, label in _HEADER.items():
        if column == "GAME_DATE" and game_words:
            starts[column] = game_words[0]
        elif column == "GAME_TIME" and len(game_words) > 1:
            starts[column] = game_words[1]
        else:
            found = [w["x0"] for w in header if w["text"] == label]
            if found:
                starts[column] = min(found)
    if len(starts) != len(_HEADER):
        raise ValueError(f"injury report header not recognized (found {sorted(starts)})")
    return starts


def _column_of(x0: float, starts: dict[str, float]) -> str:
    # each word belongs to the last column starting at or left of it
    # (minus a little slack: cells sit a point or two right of the header)
    best = "GAME_DATE"
    for column, start in sorted(starts.items(), key=lambda item: item[1]):
        if x0 >= start - 4:
            best = column
    return best


def _is_furniture(text: str) -> bool:
    return text.startswith("Injury Report:") or bool(re.fullmatch(r"Page \d+ of \d+", text))


def _team_codes() -> dict[str, str]:
    codes = {t["full_name"].lower(): t["abbreviation"] for t in static_teams.get_teams()}
    codes["la clippers"] = "LAC"
    return codes


def _display_name(player: str) -> str:
    """'Butler III, Jimmy' -> 'Jimmy Butler III'."""
    last, _, first = player.partition(",")
    return f"{first.strip()} {last.strip()}".strip()


def parse_injury_words(words: list[dict]) -> pd.DataFrame:
    """Rebuild the report table from positioned words.

    *words* are dicts with ``page``, ``x0``, ``top``, and ``text`` (one per
    word or phrase, in any order). Returns one row per player (plus one row
    per team whose report is NOT YET SUBMITTED, with PLAYER empty).
    """
    if not words:
        raise ValueError("empty injury report")
    words = sorted(words, key=lambda w: (w["page"], round(w["top"]), w["x0"]))
    starts = _column_starts(words)
    header_top = min(w["top"] for w in words if w["text"].strip() == "Reason")

    # one "line" per (page, top, column): the text in that cell on that line
    cells: dict[tuple[int, float], dict[str, list[str]]] = {}
    for w in words:
        if w["page"] == words[0]["page"] and w["top"] <= header_top + 1:
            continue
        cells.setdefault((w["page"], round(w["top"], 1)), {}).setdefault(
            _column_of(w["x0"], starts), []
        ).append(w["text"])
    lines = [
        (key, {column: " ".join(parts) for column, parts in by_column.items()})
        for key, by_column in sorted(cells.items())
    ]
    lines = [
        (key, line) for key, line in lines if not _is_furniture(" ".join(line.values()).strip())
    ]

    rows: list[dict] = []
    anchors: list[tuple[int, float]] = []
    context = dict.fromkeys(("GAME_DATE", "GAME_TIME", "MATCHUP", "TEAM"), "")
    for key, line in lines:
        for column in context:
            if line.get(column):
                context[column] = line[column]
        player = line.get("PLAYER", "")
        if not player and _NOT_SUBMITTED in " ".join(line.values()).upper():
            player = _NOT_SUBMITTED  # printed across the status/reason cells
        if not player:
            continue
        submitted = player.upper() != _NOT_SUBMITTED
        rows.append(
            {
                **context,
                "PLAYER": player if submitted else "",
                "STATUS": line.get("STATUS", "") if submitted else "Not Yet Submitted",
                "REASON": [],
            }
        )
        anchors.append(key)

    # reason blocks: consecutive reason lines on one page, < _SAME_BLOCK apart
    blocks: list[list[tuple[tuple[int, float], str]]] = []
    for key, line in lines:
        text = line.get("REASON")
        if not text or _NOT_SUBMITTED in text.upper():
            continue
        previous = blocks[-1][-1][0] if blocks else None
        if previous and previous[0] == key[0] and key[1] - previous[1] < _SAME_BLOCK:
            blocks[-1].append((key, text))
        else:
            blocks.append([(key, text)])

    for block in blocks:
        page, first_top, last_top = block[0][0][0], block[0][0][1], block[-1][0][1]
        owner = next(
            (
                i
                for i, (a_page, a_top) in enumerate(anchors)
                if a_page == page and first_top - _ROW_SLACK <= a_top <= last_top + _ROW_SLACK
            ),
            None,
        )
        if owner is None:
            # spilled over a page break: belongs to the last row before it
            before = [i for i, anchor in enumerate(anchors) if anchor < block[0][0]]
            owner = before[-1] if before else None
        if owner is not None:
            rows[owner]["REASON"].extend(text for _, text in block)

    if not rows:
        raise ValueError("no player rows in injury report")
    codes = _team_codes()
    df = pd.DataFrame(rows)
    df["REASON"] = df["REASON"].map(lambda parts: re.sub(r"\s*/\s*", "/", " ".join(parts)))
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="%m/%d/%Y").dt.date.astype(str)
    teams = df["MATCHUP"].str.split("@", expand=True)
    df["AWAY"], df["HOME"] = teams[0], teams[1]
    df["TEAM"] = df["TEAM"].str.lower().map(codes).fillna(df["TEAM"])
    df["PLAYER_NAME"] = df["PLAYER"].map(_display_name)
    return df[COLUMNS]


def pdf_words(payload: bytes) -> list[dict]:
    """Positioned words from a report PDF (multi-word cells stay joined)."""
    import pdfplumber

    words = []
    with pdfplumber.open(BytesIO(payload)) as pdf:
        for page in pdf.pages:
            for w in page.extract_words(keep_blank_chars=True, x_tolerance=1.5):
                words.append(
                    {"page": page.page_number, "x0": w["x0"], "top": w["top"], "text": w["text"]}
                )
    return words


def _get(url: str) -> bytes:
    import requests

    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.content


def fetch_report_index(season: str) -> pd.DataFrame:
    """Today's report links from the season's index page (network)."""
    return report_links(_get(INDEX_URL.format(season=season)).decode("utf-8", "replace"))


def fetch_injury_report(url: str) -> pd.DataFrame:
    """Download and parse one report PDF (network)."""
    return parse_injury_words(pdf_words(_get(url)))
