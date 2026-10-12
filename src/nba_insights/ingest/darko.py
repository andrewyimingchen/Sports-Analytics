"""DARKO daily player projections from darko.app.

DARKO (Kostya Medvedovsky & Andrew Patton) publishes daily plus-minus
projections (DPM) for every active player, free to browse and export.
The site serves its leaderboard as SvelteKit route data — a flat
"devalue" array where objects hold indices into the same array instead
of values. :func:`fetch_darko` downloads that payload; :func:`decode_darko`
is the pure flattening step, kept separate so tests stay offline.

No formal data license is published; this project displays the numbers
with attribution for personal/educational use (see README, data & legal).
"""

from __future__ import annotations

import pandas as pd

DARKO_URL = "https://www.darko.app/__data.json"

# devalue encodes special values as negative indices
_SPECIALS = {
    -1: None,  # undefined
    -2: None,  # hole
    -3: float("nan"),
    -4: float("inf"),
    -5: float("-inf"),
    -6: -0.0,
}

# source field -> column name (stats.nba.com casing, PLAYER_ID join key)
_COLUMNS = {
    "nba_id": "PLAYER_ID",
    "player_name": "PLAYER_NAME",
    "tm_id": "TEAM_ID",
    "dpm": "DPM",
    "o_dpm": "O_DPM",
    "d_dpm": "D_DPM",
    "box_dpm": "BOX_DPM",
    "on_off_dpm": "ON_OFF_DPM",
}


def decode_darko(payload: dict) -> pd.DataFrame:
    """Flatten the SvelteKit payload to one row per player.

    Finds the route node whose root object has a "players" key and
    resolves its field indices. Two layouts are understood: a list of
    per-player objects (field -> value index), and the columnar layout the
    site switched to in October 2026 (``{"keys": [...], "values": [...]}``,
    one index list per field). Raises ValueError when no node carries
    player data or the layout is unrecognized (the site changed shape), so
    the cache serves a stale copy instead of pinning garbage.
    """
    for node in payload.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "data":
            continue
        data = node["data"]
        root = data[0]
        if not isinstance(root, dict) or "players" not in root:
            continue
        try:
            players = data[root["players"]]
            if isinstance(players, dict) and {"keys", "values"} <= set(players):
                rows = _columnar_rows(data, players)
            else:
                rows = [
                    {
                        out: _resolve(data, fields[src])
                        for src, out in _COLUMNS.items()
                        if src in fields
                    }
                    for fields in (data[i] for i in players)
                ]
        except (TypeError, KeyError, IndexError) as error:
            # the index graph no longer has the shape this decoder expects
            raise ValueError("DARKO player rows have an unexpected shape") from error
        df = pd.DataFrame(rows)
        if "PLAYER_ID" not in df.columns or "DPM" not in df.columns:
            raise ValueError("DARKO payload rows lack nba_id/dpm fields")
        return df
    raise ValueError("no player data found in DARKO payload")


def _columnar_rows(data: list, players: dict) -> list[dict]:
    """Rows from the columnar layout: one value-index list per field name."""
    names = [data[index] for index in data[players["keys"]]]
    columns = data[players["values"]]
    if len(names) != len(columns):
        raise ValueError("DARKO columnar keys and values differ in length")
    wanted = {
        _COLUMNS[name]: [_resolve(data, index) for index in data[column]]
        for name, column in zip(names, columns, strict=True)
        if name in _COLUMNS
    }
    lengths = {len(values) for values in wanted.values()}
    if len(lengths) > 1:
        raise ValueError("DARKO columnar fields have different lengths")
    count = lengths.pop() if lengths else 0
    return [{column: values[row] for column, values in wanted.items()} for row in range(count)]


def _resolve(data: list, idx: int):
    if idx < 0:
        return _SPECIALS.get(idx)
    return data[idx]


def fetch_darko() -> pd.DataFrame:
    """Download today's DARKO projections (network)."""
    import requests

    r = requests.get(DARKO_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return decode_darko(r.json())
