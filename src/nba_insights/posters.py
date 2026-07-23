"""Social-ready posters: comparison duels and game predictions.

Each poster exists twice — a self-contained HTML page (no external
assets) and a PIL-drawn PNG, since social sharing is image-first. Both
use a fixed dark look at social aspect ratios (compare 1:1, prediction
16:9) rather than the viewer's theme. Pure rendering: data in, markup or
bytes out, so tests stay offline.
"""

from __future__ import annotations

from html import escape
from io import BytesIO

import pandas as pd

# dark poster palette (matches the app's dark chart palette)
_SURFACE = (26, 26, 25)
_INK = (255, 255, 255)
_INK2 = (195, 194, 183)
_MUTED = (137, 135, 129)
_GRID = (44, 44, 42)
_SERIES = [(57, 135, 229), (25, 158, 112), (201, 133, 0), (230, 103, 103)]

_LABELS = {
    "FG_PCT": "FG%",
    "FG3_PCT": "3P%",
    "FT_PCT": "FT%",
    "NET_RATING": "NET RTG",
    "CLUTCH_NET_RATING": "CLUTCH NET",
    "DPM": "DARKO DPM",
}
_SIGNED = {"NET_RATING", "CLUTCH_NET_RATING", "DPM"}
_LOWER_BETTER = {"TOV"}
_NEUTRAL = {"GP", "MIN"}  # availability context, not a duel to win

_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _fmt(stat: str, value) -> str:
    if pd.isna(value):
        return "—"
    if stat.endswith("_PCT"):
        return f"{value * 100:.1f}%"
    if stat == "GP":
        return f"{value:.0f}"
    if stat in _SIGNED:
        return f"{value:+.1f}"
    return f"{value:.1f}"


def _winner(stat: str, values: pd.Series) -> str | None:
    """Column name of the best value in a stat row, None when unclear."""
    present = values.dropna()
    if stat in _NEUTRAL or len(present) < 2:
        return None
    return present.idxmin() if stat in _LOWER_BETTER else present.idxmax()


def _rgb(color: tuple[int, int, int]) -> str:
    return f"rgb({color[0]},{color[1]},{color[2]})"


# -- HTML -----------------------------------------------------------------

_POSTER_CSS = f"""
body {{ margin: 0; display: grid; place-items: center; min-height: 100vh;
       background: #0e0e0d;
       font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
.poster {{ background: {_rgb(_SURFACE)}; color: {_rgb(_INK)};
          border-radius: 20px; padding: 4.5%; box-sizing: border-box;
          display: flex; flex-direction: column; }}
.square {{ width: min(680px, 94vw); aspect-ratio: 1 / 1; }}
.wide {{ width: min(900px, 94vw); aspect-ratio: 16 / 9; }}
.brand {{ color: {_rgb(_MUTED)}; font-size: .8rem; letter-spacing: .12em;
         text-transform: uppercase; }}
.foot {{ margin-top: auto; color: {_rgb(_MUTED)}; font-size: .7rem; }}
.names {{ display: grid; gap: 12px; margin: 18px 0 10px; }}
.names .n {{ font-weight: 750; font-size: 1.35rem; line-height: 1.15; }}
table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
td, th {{ padding: .42em 0; border-bottom: 1px solid {_rgb(_GRID)};
         text-align: right; font-variant-numeric: tabular-nums; }}
td.label {{ text-align: left; color: {_rgb(_INK2)}; font-size: .8rem;
           letter-spacing: .04em; }}
td.win {{ font-weight: 750; }}
.matchup {{ display: flex; align-items: baseline; gap: 22px; margin: 26px 0 8px; }}
.matchup .team {{ font-size: 3.2rem; font-weight: 800; }}
.matchup .at {{ color: {_rgb(_MUTED)}; font-size: 1.2rem; }}
.bigprob {{ font-size: 4.6rem; font-weight: 800; margin: 8px 0 2px; }}
.bigprob .who {{ font-size: 1.2rem; font-weight: 600; color: {_rgb(_INK2)};
                margin-left: 12px; }}
.bar {{ display: flex; height: 22px; border-radius: 11px; overflow: hidden;
       margin: 18px 0 6px; }}
.ends {{ display: flex; justify-content: space-between;
        color: {_rgb(_INK2)}; font-size: .9rem; }}
"""


def _page(title: str, klass: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — POSSESSION LAB</title><style>{_POSTER_CSS}</style></head>
<body><div class="poster {klass}">
{body}
<div class="foot">POSSESSION LAB · data: stats.nba.com · DPM: darko.app</div>
</div></body></html>"""


def compare_poster_html(table: pd.DataFrame, season: str) -> str:
    """1:1 duel poster from a `comparison_table` frame (stats × players)."""
    names = list(table.columns)
    name_cells = "".join(
        f'<div class="n" style="color:{_rgb(_SERIES[i % len(_SERIES)])}">{escape(n)}</div>'
        for i, n in enumerate(names)
    )
    rows = []
    for stat in table.index:
        best = _winner(stat, table.loc[stat])
        cells = "".join(
            f'<td class="win" style="color:{_rgb(_SERIES[names.index(n) % len(_SERIES)])}">'
            f"{_fmt(stat, v)}</td>"
            if n == best
            else f"<td>{_fmt(stat, v)}</td>"
            for n, v in table.loc[stat].items()
        )
        rows.append(f'<tr><td class="label">{escape(_LABELS.get(stat, stat))}</td>{cells}</tr>')
    body = f"""<div class="brand">POSSESSION LAB · {escape(season)}</div>
<div class="names" style="grid-template-columns: repeat({len(names)}, 1fr)">{name_cells}</div>
<table><tbody>{"".join(rows)}</tbody></table>"""
    return _page(" vs ".join(names), "square", body)


def prediction_poster_html(home: str, away: str, prob: float, season: str) -> str:
    """16:9 game-prediction poster; *prob* is the home team's win chance."""
    home_c, away_c = _rgb(_SERIES[0]), _rgb(_SERIES[1])
    fav, fav_prob, fav_c = (home, prob, home_c) if prob >= 0.5 else (away, 1 - prob, away_c)
    body = f"""<div class="brand">POSSESSION LAB · game prediction · {escape(season)}</div>
<div class="matchup"><span class="team" style="color:{home_c}">{escape(home)}</span>
<span class="at">vs</span>
<span class="team" style="color:{away_c}">{escape(away)}</span></div>
<div class="bigprob" style="color:{fav_c}">{fav_prob:.0%}<span class="who">{escape(fav)} win
probability</span></div>
<div class="bar"><div style="width:{prob:.1%};background:{home_c}"></div>
<div style="flex:1;background:{away_c}"></div></div>
<div class="ends"><span>{escape(home)} (home) {prob:.0%}</span>
<span>{escape(away)} {1 - prob:.0%}</span></div>"""
    return _page(f"{home} vs {away}", "wide", body)


# -- PNG ------------------------------------------------------------------


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"{_FONT_DIR}/{name}", size)
    except OSError:  # no DejaVu on this host: Pillow's scalable builtin
        return ImageFont.load_default(size=size)


def _fit(draw, text: str, font, max_w: int) -> str:
    """Ellipsize *text* so it draws within *max_w* pixels."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _png(img) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def compare_poster_png(table: pd.DataFrame, season: str) -> bytes:
    """1080×1080 PNG of the duel poster (same content as the HTML)."""
    from PIL import Image, ImageDraw

    side, pad = 1080, 84
    img = Image.new("RGB", (side, side), _SURFACE)
    draw = ImageDraw.Draw(img)
    names = list(table.columns)
    label_w = 240
    col_w = (side - 2 * pad - label_w) // len(names)
    col_x = [pad + label_w + col_w * i for i in range(len(names))]

    draw.text((pad, pad), f"POSSESSION LAB · {season}", font=_font(26), fill=_MUTED)

    name_size = {2: 44, 3: 36}.get(len(names), 30)
    name_font = _font(name_size, bold=True)
    for i, name in enumerate(names):
        draw.text(
            (col_x[i] + col_w - 16, 150),
            _fit(draw, name, name_font, col_w - 20),
            font=name_font,
            fill=_SERIES[i % len(_SERIES)],
            anchor="rs",
        )

    top, bottom = 200, side - pad - 40
    row_h = min(64, (bottom - top) // max(len(table.index), 1))
    label_font, value_font = _font(24), _font(30)
    win_font = _font(30, bold=True)
    for r, stat in enumerate(table.index):
        y = top + row_h * (r + 1)
        best = _winner(stat, table.loc[stat])
        draw.line([(pad, y + 12), (side - pad, y + 12)], fill=_GRID, width=1)
        draw.text((pad, y), _LABELS.get(stat, stat), font=label_font, fill=_INK2, anchor="ls")
        for i, name in enumerate(names):
            value = _fmt(stat, table.loc[stat, name])
            if name == best:
                fill, font = _SERIES[i % len(_SERIES)], win_font
            else:
                fill, font = _INK, value_font
            draw.text((col_x[i] + col_w - 16, y), value, font=font, fill=fill, anchor="rs")

    draw.text(
        (pad, side - pad + 30),
        "POSSESSION LAB · data: stats.nba.com · DPM: darko.app",
        font=_font(22),
        fill=_MUTED,
    )
    return _png(img)


def prediction_poster_png(home: str, away: str, prob: float, season: str) -> bytes:
    """1200×675 PNG of the game-prediction poster."""
    from PIL import Image, ImageDraw

    w, h, pad = 1200, 675, 84
    img = Image.new("RGB", (w, h), _SURFACE)
    draw = ImageDraw.Draw(img)
    home_c, away_c = _SERIES[0], _SERIES[1]

    draw.text(
        (pad, pad), f"POSSESSION LAB · GAME PREDICTION · {season}", font=_font(26), fill=_MUTED
    )

    team_font = _font(84, bold=True)
    x = pad
    draw.text((x, 220), home, font=team_font, fill=home_c, anchor="ls")
    x += draw.textlength(home, font=team_font) + 34
    draw.text((x, 220), "vs", font=_font(36), fill=_MUTED, anchor="ls")
    x += draw.textlength("vs", font=_font(36)) + 34
    draw.text((x, 220), away, font=team_font, fill=away_c, anchor="ls")

    fav, fav_prob, fav_c = (home, prob, home_c) if prob >= 0.5 else (away, 1 - prob, away_c)
    prob_font = _font(150, bold=True)
    draw.text((pad, 400), f"{fav_prob:.0%}", font=prob_font, fill=fav_c, anchor="ls")
    x = pad + draw.textlength(f"{fav_prob:.0%}", font=prob_font) + 26
    draw.text((x, 400), f"{fav} win probability", font=_font(32), fill=_INK2, anchor="ls")

    bar_y, bar_h, bar_w = 460, 30, w - 2 * pad
    split = pad + int(bar_w * prob)
    draw.rounded_rectangle([(pad, bar_y), (w - pad, bar_y + bar_h)], radius=15, fill=away_c)
    draw.rounded_rectangle([(pad, bar_y), (split, bar_y + bar_h)], radius=15, fill=home_c)
    ends_font = _font(28)
    draw.text((pad, bar_y + bar_h + 44), f"{home} (home) {prob:.0%}", font=ends_font, fill=_INK2)
    draw.text(
        (w - pad, bar_y + bar_h + 44),
        f"{away} {1 - prob:.0%}",
        font=ends_font,
        fill=_INK2,
        anchor="ra",
    )

    draw.text(
        (pad, h - pad + 30),
        "POSSESSION LAB · data: stats.nba.com",
        font=_font(22),
        fill=_MUTED,
    )
    return _png(img)
