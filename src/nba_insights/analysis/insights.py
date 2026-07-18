"""Rule-based scouting takes: turn percentile ranks and team form into a
short natural-language read, so a page states a conclusion instead of
leaving the reader to decode every number.

Pure functions (strings in, string out) — deterministic and offline, like
the rest of the analysis layer. If richer prose is ever wanted, an LLM call
can replace a call site without changing the data these consume.
"""

from __future__ import annotations

import pandas as pd

# the box-score and shooting skills a scouting take describes. Composite
# impact stats (NET_RATING, DPM) are deliberately excluded — "elite net
# rating" is a consequence, not a skill, and listing it beside "elite
# scoring" reads as redundant filler.
_SKILL_PHRASES = {
    "PTS": "scoring",
    "AST": "playmaking",
    "REB": "rebounding",
    "STL": "steals",
    "BLK": "rim protection",
    "FG_PCT": "finishing",
    "FG3_PCT": "outside shooting",
    "FT_PCT": "free-throw shooting",
}

_ELITE = 90.0
_STRONG = 80.0
_WEAK = 30.0


def _join(phrases: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b, and c'."""
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def _ordinal(n: int) -> str:
    """3 -> '3rd'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def player_scouting_take(ranks: pd.Series, max_per_clause: int = 3) -> str:
    """A one-line read of a player from their league percentile ranks.

    *ranks* is the raw-keyed percentile Series from
    :func:`percentile_ranks` (0-100 per stat code). Names the elite and
    strong skills, then the standout weakness if there is one. Returns an
    empty string when no skill stats are present.
    """
    present = {
        stat: float(v)
        for stat, v in ranks.items()
        if stat in _SKILL_PHRASES and pd.notna(v)
    }
    if not present:
        return ""

    ranked = sorted(present.items(), key=lambda kv: kv[1], reverse=True)
    elite = [_SKILL_PHRASES[s] for s, v in ranked if v >= _ELITE][:max_per_clause]
    strong = [_SKILL_PHRASES[s] for s, v in ranked if _STRONG <= v < _ELITE][:max_per_clause]
    weak = [_SKILL_PHRASES[s] for s, v in sorted(present.items(), key=lambda kv: kv[1])
            if v <= _WEAK][:2]

    clauses: list[str] = []
    if elite:
        clauses.append(f"Elite {_join(elite)}")
        if strong:
            clauses.append(f"also strong at {_join(strong)}")
    elif strong:
        clauses.append(f"Strong {_join(strong)}")
    else:
        # no standout skill: anchor on the single best rank
        best_stat, best_val = ranked[0]
        clauses.append(
            f"A balanced profile, best at {_SKILL_PHRASES[best_stat]} "
            f"({_ordinal(round(best_val))} percentile)"
        )

    if weak:
        # the skill phrases are gerunds ("playmaking"), so no article
        if clauses:
            clauses.append(f"though below-average {_join(weak)}")
        else:
            clauses.append(f"Below-average {_join(weak)}")

    return "; ".join(clauses) + "."


def team_scouting_take(
    form: pd.Series,
    wins: int,
    losses: int,
    league_form: pd.DataFrame | None = None,
    recent: tuple[int, int] | None = None,
) -> str:
    """A one-line read of a team from its season-to-date form.

    *form* is one team's row from ``team_form_snapshot`` (form_net,
    form_ortg, form_drtg). When *league_form* (the full snapshot) is given,
    the offense and defense are ranked in-league; *recent* is an optional
    (wins, losses) over the last handful of games for a trend clause.
    """
    net = float(form.get("form_net", float("nan")))
    if pd.isna(net):
        return ""

    if net >= 6:
        tier = "a clear contender"
    elif net >= 2:
        tier = "a solid playoff-level team"
    elif net > -2:
        tier = "a middle-of-the-pack team"
    elif net > -6:
        tier = "a below-average team"
    else:
        tier = "among the league's weakest"
    parts = [f"{wins}-{losses}, {tier} at {net:+.1f} net rating"]

    if (
        league_form is not None
        and {"form_ortg", "form_drtg"} <= set(league_form.columns)
        and pd.notna(form.get("form_ortg"))
        and pd.notna(form.get("form_drtg"))
    ):
        n = len(league_form)
        off_rank = int((league_form["form_ortg"] > form["form_ortg"]).sum()) + 1
        def_rank = int((league_form["form_drtg"] < form["form_drtg"]).sum()) + 1
        rank_clause = f"the {_ordinal(off_rank)} offense and {_ordinal(def_rank)} defense"
        third = max(1, n // 3)
        if off_rank <= third and def_rank <= third:
            rank_clause += ", elite on both ends"
        elif off_rank <= third:
            rank_clause += ", carried by the offense"
        elif def_rank <= third:
            rank_clause += ", built on defense"
        parts.append(rank_clause)

    if recent is not None:
        rw, rl = recent
        games = rw + rl
        if games:
            if rw >= rl + 2:
                parts.append(f"trending up — {rw} of its last {games}")
            elif rl >= rw + 2:
                parts.append(f"cooling off — {rw} of its last {games}")

    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."
