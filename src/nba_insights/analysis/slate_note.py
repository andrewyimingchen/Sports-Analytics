"""Game-day slate note for an Obsidian vault (pure, no I/O).

One Markdown note per game day: each game's exchange price next to the
outcome model (full strength and injury-adjusted), the injury report's
notable absences, the biggest model-vs-market gaps as a parlay check, and
-- once the games are final -- results. :mod:`nba_insights.markets` writes
it (``markets note``); this module only turns frames into text.

The generated part sits between :data:`NOTE_START` and :data:`NOTE_END`
(Obsidian comments, invisible in reading view). Rewrites replace only that
block and the frontmatter, so anything the owner writes below it survives.

Prices and injuries are personal research data (CLAUDE.md guardrails): the
note goes to a local vault, never through the public API/PWA.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from nba_insights.analysis.injuries import EASTERN

NOTE_START = "%% possession-lab:start %%"
NOTE_END = "%% possession-lab:end %%"
NOTE_FOLDER = "NBA"

# a gap smaller than this is noise (exchange fees alone are ~1-2 cents)
MIN_GAP = 0.03
PARLAY_LEGS = 3
# finished, tracked games before the model's edge counts as evidence
MIN_TRACKED_GAMES = 100
# injury rows shown: players expected to play at least this many minutes
MIN_SHOWN_MINUTES = 5.0


def note_name(date: str) -> str:
    """Note title (and file stem) for a game day, e.g. ``2026-11-20 NBA Slate``."""
    return f"{date} NBA Slate"


def slate_table(lines: pd.DataFrame, games: pd.DataFrame, date: str) -> pd.DataFrame:
    """One row per scheduled game on *date* with its latest pre-tip line.

    *lines* is :func:`~nba_insights.analysis.markets.opening_closing` output
    (so "close" means the last snapshot before tip-off seen so far). The
    exchanges are averaged; BID/ASK are the best quotes across them. PROB is
    the injury-adjusted model where the report covered the game, otherwise
    full strength; GAP is PROB minus the market (positive: model likes home).
    Games without prices keep NaN price columns.
    """
    day = games[games["GAME_DATE"] == date][["GAME_ID", "TIP_UTC", "AWAY", "HOME", "HOME_WIN"]]
    if lines.empty:
        priced = pd.DataFrame(
            columns=["GAME_ID", "OPEN", "PRICE", "BID", "ASK", "MODEL", "MODEL_INJ"]
        )
    else:
        priced = (
            lines.groupby("GAME_ID")
            .agg(
                OPEN=("OPEN_PRICE", "mean"),
                PRICE=("CLOSE_PRICE", "mean"),
                BID=("HOME_BID", "max"),
                ASK=("HOME_ASK", "min"),
                MODEL=("CLOSE_MODEL", "mean"),
                MODEL_INJ=("CLOSE_MODEL_INJ", "mean"),
            )
            .reset_index()
        )
    table = day.merge(priced, on="GAME_ID", how="left").sort_values(["TIP_UTC", "HOME"])
    table["PROB"] = table["MODEL_INJ"].fillna(table["MODEL"])
    table["GAP"] = table["PROB"] - table["PRICE"]
    return table.reset_index(drop=True)


def parlay_legs(
    slate: pd.DataFrame, n: int = PARLAY_LEGS, min_gap: float = MIN_GAP
) -> pd.DataFrame:
    """The *n* biggest model-over-market sides, each at least *min_gap*.

    Each leg is the side the model likes more than the market: TEAM, PROB
    (model), PRICE (market), RATIO (PROB / PRICE: the expected return per
    unit if the model were right), and WON (1/0, NaN until final).
    """
    rows = []
    for game in slate.dropna(subset=["GAP"]).itertuples():
        home = game.GAP > 0
        won = game.HOME_WIN if home else 1 - game.HOME_WIN
        rows.append(
            {
                "TEAM": game.HOME if home else game.AWAY,
                "OPPONENT": game.AWAY if home else game.HOME,
                "PROB": game.PROB if home else 1 - game.PROB,
                "PRICE": game.PRICE if home else 1 - game.PRICE,
                "EDGE": abs(game.GAP),
                "WON": won,
            }
        )
    legs = pd.DataFrame(rows, columns=["TEAM", "OPPONENT", "PROB", "PRICE", "EDGE", "WON"])
    legs = legs[legs["EDGE"] >= min_gap].nlargest(n, "EDGE")
    legs["RATIO"] = legs["PROB"] / legs["PRICE"]
    return legs.reset_index(drop=True)


def track_record(scorecard: pd.DataFrame) -> tuple[bool, str]:
    """Whether the model has earned parlays yet, and a one-line summary.

    *scorecard* is ``markets report`` output. It uses the injury-adjusted
    model when it has scored games, otherwise full strength. The model has
    earned it only with at least :data:`MIN_TRACKED_GAMES` finished games
    and a lower log loss than every exchange's closing price.
    """
    if scorecard.empty:
        return False, "No finished games tracked yet: the model has no record against the market."
    model = "MODEL_INJ" if (scorecard["MODEL"] == "MODEL_INJ").any() else "MODEL"
    card = scorecard[scorecard["MODEL"] == model]
    games = int(card["GAMES"].max())
    beats = bool((card["MODEL_LOG_LOSS"] < card["MARKET_LOG_LOSS"]).all())
    label = "injury-adjusted model" if model == "MODEL_INJ" else "model"
    losses = ", ".join(f"{row.SOURCE} {row.MARKET_LOG_LOSS:.3f}" for row in card.itertuples())
    summary = (
        f"{games} finished games tracked: {label} log loss "
        f"{card['MODEL_LOG_LOSS'].mean():.3f} vs closing price ({losses}). Lower is better."
    )
    return games >= MIN_TRACKED_GAMES and beats, summary


def _pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.3f}".lstrip("0")


def _gap(game: pd.Series) -> str:
    if pd.isna(game["GAP"]):
        return "—"
    side = game["HOME"] if game["GAP"] > 0 else game["AWAY"]
    text = f"+{abs(game['GAP']):.3f}".replace("0.", ".") + f" {side}"
    return f"**{text}**" if abs(game["GAP"]) >= MIN_GAP else text


def _tip(tip: pd.Timestamp) -> str:
    return tip.tz_convert(EASTERN).strftime("%I:%M %p").lstrip("0")


def _result(game: pd.Series) -> str:
    if pd.isna(game["HOME_WIN"]):
        return ""
    winner = game["HOME"] if game["HOME_WIN"] == 1 else game["AWAY"]
    if pd.isna(game["GAP"]) or abs(game["GAP"]) < MIN_GAP:
        return f"{winner} won"
    hit = (game["GAP"] > 0) == (game["HOME_WIN"] == 1)
    return f"{winner} won {'✅' if hit else '❌'}"


def _slate_section(slate: pd.DataFrame) -> list[str]:
    final = slate["HOME_WIN"].notna().any()
    header = "| Tip (ET) | Game | Open | Market | Model | Injury-adj. | Gap |"
    rule = "|---|---|---:|---:|---:|---:|---|"
    if final:
        header += " Result |"
        rule += "---|"
    out = [header, rule]
    for _, game in slate.iterrows():
        row = (
            f"| {_tip(game['TIP_UTC'])} | {game['AWAY']} @ **{game['HOME']}** "
            f"| {_pct(game['OPEN'])} | {_pct(game['PRICE'])} | {_pct(game['MODEL'])} "
            f"| {_pct(game['MODEL_INJ'])} | {_gap(game)} |"
        )
        out.append(row + (f" {_result(game)} |" if final else ""))
    return out


def _injury_section(players: pd.DataFrame, teams: list[str]) -> list[str]:
    shown = players[
        players["TEAM"].isin(teams)
        & (players["WEIGHT"] > 0)
        & (players["EXP_MIN"] >= MIN_SHOWN_MINUTES)
    ]
    if shown.empty:
        return ["No regular is listed out or questionable."]
    totals = players.groupby("TEAM")["MISSING_MIN"].sum()
    out = ["| Team | Minutes out | Players |", "|---|---:|---|"]
    order = totals.reindex(shown["TEAM"].unique()).sort_values(ascending=False)
    for team, minutes in order.items():
        rows = shown[shown["TEAM"] == team].sort_values("EXP_MIN", ascending=False)
        names = ", ".join(
            f"**{r.PLAYER_NAME} (Q)**"
            if r.STATUS == "Questionable"
            else f"{r.PLAYER_NAME} ({r.STATUS.lower()})"
            for r in rows.itertuples()
        )
        out.append(f"| {team} | {minutes:.1f} | {names} |")
    return out


def _parlay_section(legs: pd.DataFrame, earned: bool, record: str) -> list[str]:
    out = []
    if earned:
        out += [
            "> [!success] The model has a track record",
            f"> {record}",
        ]
    else:
        out += [
            "> [!danger] Skip parlays: the model hasn't beaten the market yet",
            f"> {record}",
            f"> Parlays need at least {MIN_TRACKED_GAMES} tracked games and a model that beats "
            "the closing price. Until then, a big gap is more likely a model blind spot than a "
            "market mistake, and a parlay multiplies that error across every leg.",
        ]
    out.append("")
    if legs.empty:
        out.append(f"No side differs from the market by {MIN_GAP:.2f} or more.")
        return out
    out += ["| Leg | Model | Price | Model ÷ price | Won |", "|---|---:|---:|---:|---|"]
    for leg in legs.itertuples():
        won = "" if pd.isna(leg.WON) else ("✅" if leg.WON == 1 else "❌")
        out.append(
            f"| {leg.TEAM} vs {leg.OPPONENT} | {_pct(leg.PROB)} | {_pct(leg.PRICE)} "
            f"| {leg.RATIO:.3f} | {won} |"
        )
    hit = float(np.prod(legs["PROB"]))
    ratio = float(np.prod(legs["RATIO"]))
    won = "" if legs["WON"].isna().any() else ("✅" if (legs["WON"] == 1).all() else "❌")
    out.append(f"| **{len(legs)}-leg parlay** | **{_pct(hit)}** | — | **{ratio:.3f}** | {won} |")
    out += [
        "",
        f"If the model is right, all legs win {hit:.0%} of the time for an expected return of "
        f"{ratio - 1:+.0%}. This assumes independent legs and ignores exchange fees "
        "(Kalshi charges about 1–2¢ per contract near even odds).",
    ]
    return out


def render_note(
    date: str,
    slate: pd.DataFrame,
    *,
    players: pd.DataFrame,
    report_at: pd.Timestamp | None,
    scorecard: pd.DataFrame,
    updated: pd.Timestamp,
    previous: str | None = None,
    following: str | None = None,
) -> tuple[str, str]:
    """(frontmatter, generated block) for one game day's note.

    *players* is :func:`~nba_insights.analysis.injuries.injured_minutes`
    output for the report that applied to *date* (*report_at*, naive ET),
    or empty. *previous* / *following* are adjacent game dates for links.
    """
    final = bool(len(slate)) and slate["HOME_WIN"].notna().all()
    earned, record = track_record(scorecard)
    legs = parlay_legs(slate)
    report_text = "none" if report_at is None else f"{report_at:%Y-%m-%d %H:%M} ET"

    frontmatter = "\n".join(
        [
            "---",
            f"date: {date}",
            "type: nba-slate",
            f"games: {len(slate)}",
            f"updated: {updated.tz_convert('UTC').isoformat(timespec='seconds')}",
            f'injury_report: "{report_text}"',
            f"final: {str(final).lower()}",
            "tags:",
            "  - nba",
            "  - nba/slate",
            "  - prediction-markets",
            "---",
        ]
    )

    nav = []
    if previous:
        nav.append(f"← [[{note_name(previous)}]]")
    if following:
        nav.append(f"[[{note_name(following)}]] →")
    stamp = updated.tz_convert(EASTERN).strftime("%Y-%m-%d %I:%M %p ET")
    status = (
        "Final: closing lines and results."
        if final
        else "Lines so far; refreshed at 10:00 ET, 15:00 ET, and 45 minutes before the first tip."
    )
    lines = [
        f"# {date} NBA slate",
        "",
        *([" · ".join(nav), ""] if nav else []),
        "> [!info] Snapshot",
        f"> Updated {stamp}. {status}",
        f"> Injury report: {report_text}. Probabilities are for the **home team** (bold); "
        "Market averages Kalshi and Polymarket at the last snapshot before tip-off.",
        "",
        "## Slate",
        "",
        *_slate_section(slate),
        "",
        "## Injuries",
        "",
        *(
            _injury_section(players, [*slate["AWAY"], *slate["HOME"]])
            if not players.empty
            else ["No injury report logged for this day."]
        ),
        "",
        "## Parlay check",
        "",
        *_parlay_section(legs, earned, record),
    ]
    return frontmatter, "\n".join(lines)


_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)


def merge_note(existing: str | None, frontmatter: str, block: str) -> str:
    """The note text with *frontmatter* and *block* replacing the generated parts.

    Text outside the markers (the owner's notes) is kept. A note without
    markers (new, or hand-written) gets the generated part on top and its
    old body, if any, below.
    """
    generated = f"{NOTE_START}\n{block}\n{NOTE_END}"
    if existing is None:
        return f"{frontmatter}\n{generated}\n\n## My notes\n\n"
    body = _FRONTMATTER.sub("", existing, count=1)
    start, end = body.find(NOTE_START), body.find(NOTE_END)
    if start != -1 and end > start:
        body = body[:start] + generated + body[end + len(NOTE_END) :]
    else:
        body = f"{generated}\n\n{body.lstrip()}"
    return f"{frontmatter}\n{body}"


def note_frontmatter(text: str) -> dict[str, str]:
    """Top-level ``key: value`` pairs of a note's frontmatter (lists skipped)."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    pairs = {}
    for line in match.group(0).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" ") and value.strip():
            pairs[key.strip()] = value.strip().strip('"')
    return pairs
