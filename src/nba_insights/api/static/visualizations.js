const Plot = globalThis.Plot;
const ORANGE = "#ff5c35";
const BLUE = "#7ab8ff";
const LIME = "#c7ff4a";
const RED = "#ff6b6b";
const MUTED = "#77808c";
const PAPER = "#f2f0e9";

const finite = (value) => value !== null && value !== undefined && value !== ""
  && Number.isFinite(Number(value));
const number = (value) => Number(value);
const average = (rows, key) => {
  const values = rows.map((row) => number(row[key])).filter(Number.isFinite);
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
};
const chartWidth = (target, maximum = 960) => Math.max(
  300,
  Math.min(maximum, Math.floor(target.getBoundingClientRect().width || maximum)),
);

function plotUnavailable(target, tableHTML) {
  target.innerHTML = `<div class="viz-fallback"><p>Visual view unavailable. The exact data remains available below.</p>${tableHTML || ""}</div>`;
}

export function mountChart(target, {
  title,
  takeaway,
  description,
  plotFactory,
  tableHTML = "",
  dataLabel = "View exact data",
}) {
  if (!target) return;
  if (!Plot) {
    plotUnavailable(target, tableHTML);
    return;
  }
  const figure = document.createElement("figure");
  figure.className = "data-figure";

  const heading = document.createElement("div");
  heading.className = "figure-heading";
  const titleElement = document.createElement("h4");
  titleElement.textContent = title;
  const takeawayElement = document.createElement("p");
  takeawayElement.textContent = takeaway;
  heading.append(titleElement, takeawayElement);

  const plotHost = document.createElement("div");
  plotHost.className = "plot-host";
  const rendered = plotFactory(chartWidth(target));
  rendered.classList?.add("possession-plot");
  plotHost.append(rendered);
  figure.append(heading, plotHost);

  if (description) {
    const caption = document.createElement("figcaption");
    caption.textContent = description;
    figure.append(caption);
  }
  if (tableHTML) {
    const details = document.createElement("details");
    details.className = "viz-data";
    const summary = document.createElement("summary");
    summary.textContent = dataLabel;
    const table = document.createElement("div");
    table.className = "viz-data-scroll";
    table.innerHTML = tableHTML;
    details.append(summary, table);
    figure.append(details);
  }
  target.replaceChildren(figure);
}

export function exploreScatterPlot(rows, xKey, yKey, labels) {
  const data = rows.filter((row) => finite(row[xKey]) && finite(row[yKey]));
  const xMean = average(data, xKey);
  const yMean = average(data, yKey);
  const labeled = [...data]
    .sort((first, second) => number(second[yKey]) - number(first[yKey]))
    .slice(0, 8);
  return (width) => Plot.plot({
    width,
    height: width < 520 ? 390 : 470,
    marginTop: 20,
    marginRight: 30,
    marginBottom: 52,
    marginLeft: 58,
    grid: true,
    style: { background: "transparent", color: PAPER, fontSize: "11px" },
    ariaLabel: `${labels.y} by ${labels.x} player scatterplot`,
    ariaDescription: `Players above and right of the dashed league-average lines are stronger on both selected measures. ${data.length} qualified players are shown.`,
    x: { label: labels.x, nice: true },
    y: { label: labels.y, nice: true },
    marks: [
      Plot.ruleX([xMean], { stroke: MUTED, strokeDasharray: "5,5" }),
      Plot.ruleY([yMean], { stroke: MUTED, strokeDasharray: "5,5" }),
      Plot.dot(data, {
        x: xKey,
        y: yKey,
        fill: ORANGE,
        fillOpacity: 0.76,
        stroke: "#0d1115",
        strokeWidth: 1,
        r: width < 520 ? 4.5 : 6,
        ariaLabel: (row) => `${row.PLAYER_NAME}, ${labels.x} ${row[xKey]}, ${labels.y} ${row[yKey]}`,
      }),
      Plot.text(labeled.slice(0, width < 520 ? 5 : 8), {
        x: xKey,
        y: yKey,
        text: "PLAYER_NAME",
        dy: -10,
        fontSize: width < 520 ? 8 : 10,
        fill: PAPER,
      }),
      Plot.tip(data, Plot.pointer({
        x: xKey,
        y: yKey,
        title: (row) => `${row.PLAYER_NAME}\n${row.TEAM_ABBREVIATION} · ${labels.x} ${Number(row[xKey]).toFixed(1)} · ${labels.y} ${Number(row[yKey]).toFixed(1)}`,
      })),
    ],
  });
}

export function winIntervalPlot(rows, conference) {
  const data = rows
    .filter((row) => finite(row.PROJECTED_WINS))
    .map((row) => ({
      ...row,
      low: number(row.PESSIMISTIC_WINS ?? row.PROJECTED_WINS),
      median: number(row.MEDIAN_WINS ?? row.PROJECTED_WINS),
      high: number(row.OPTIMISTIC_WINS ?? row.PROJECTED_WINS),
    }))
    .sort((first, second) => second.median - first.median);
  return (width) => Plot.plot({
    width,
    height: Math.max(340, data.length * 27 + 62),
    marginLeft: 48,
    marginRight: 38,
    marginBottom: 42,
    style: { background: "transparent", color: PAPER, fontSize: "10px" },
    ariaLabel: `${conference} projected wins interval plot`,
    ariaDescription: "Each horizontal line is the 10th-to-90th percentile win range. The orange dot is the median projection.",
    x: { label: "Projected wins · P10 — median — P90", grid: true, nice: true },
    y: { label: null, domain: data.map((row) => row.TEAM) },
    marks: [
      Plot.ruleY(data, { y: "TEAM", x1: "low", x2: "high", stroke: MUTED, strokeWidth: 5 }),
      Plot.dot(data, { x: "median", y: "TEAM", fill: ORANGE, stroke: "#0d1115", r: 5 }),
      Plot.tip(data, Plot.pointer({
        x: "median",
        y: "TEAM",
        title: (row) => `${row.TEAM}: ${row.low.toFixed(0)} / ${row.median.toFixed(0)} / ${row.high.toFixed(0)} wins`,
      })),
    ],
  });
}

export function probabilityPlot(rows, label, key, color = BLUE, limit = 15) {
  const data = rows
    .filter((row) => finite(row[key]))
    .map((row) => ({ ...row, probability: number(row[key]) * 100 }))
    .sort((first, second) => second.probability - first.probability)
    .slice(0, limit);
  return (width) => Plot.plot({
    width,
    height: Math.max(310, data.length * 25 + 58),
    marginLeft: 48,
    marginRight: 48,
    marginBottom: 40,
    style: { background: "transparent", color: PAPER, fontSize: "10px" },
    ariaLabel: `${label} probability dot plot`,
    ariaDescription: `The ${data.length} strongest teams are ordered from highest to lowest ${label.toLowerCase()} probability.`,
    x: { label: `${label} probability`, domain: [0, 100], tickFormat: (value) => `${value}%`, grid: true },
    y: { label: null, domain: data.map((row) => row.TEAM) },
    marks: [
      Plot.ruleX([50], { stroke: MUTED, strokeDasharray: "5,5" }),
      Plot.dot(data, { x: "probability", y: "TEAM", fill: color, r: 5 }),
      Plot.text(data, {
        x: "probability",
        y: "TEAM",
        text: (row) => `${row.probability.toFixed(0)}%`,
        dx: 9,
        textAnchor: "start",
        fill: PAPER,
        fontSize: 9,
      }),
    ],
  });
}

export function playerIntervalPlot(rows) {
  const data = rows
    .filter((row) => finite(row.PROJECTED_PTS))
    .map((row) => ({
      ...row,
      low: number(row.PTS_LOW ?? row.PROJECTED_PTS),
      median: number(row.PROJECTED_PTS),
      high: number(row.PTS_HIGH ?? row.PROJECTED_PTS),
    }))
    .sort((first, second) => second.median - first.median)
    .slice(0, 20);
  return (width) => Plot.plot({
    width,
    height: data.length * 25 + 70,
    marginLeft: width < 520 ? 102 : 145,
    marginRight: 40,
    marginBottom: 42,
    style: { background: "transparent", color: PAPER, fontSize: width < 520 ? "9px" : "10px" },
    ariaLabel: "Top projected player points interval plot",
    ariaDescription: "The twenty highest median scoring projections are shown with their low-to-high forecast intervals.",
    x: { label: "Projected points per game · low — median — high", grid: true },
    y: { label: null, domain: data.map((row) => row.PLAYER_NAME) },
    marks: [
      Plot.ruleY(data, { y: "PLAYER_NAME", x1: "low", x2: "high", stroke: MUTED, strokeWidth: 5 }),
      Plot.dot(data, { x: "median", y: "PLAYER_NAME", fill: LIME, stroke: "#0d1115", r: 5 }),
    ],
  });
}

export function matchupRankPlot(metrics, away, home) {
  const data = metrics
    .filter((metric) => finite(metric.first_rank) && finite(metric.second_rank))
    .map((metric) => ({
      label: metric.label,
      awayRank: number(metric.first_rank),
      homeRank: number(metric.second_rank),
    }));
  return (width) => Plot.plot({
    width,
    height: Math.max(330, data.length * 31 + 72),
    marginLeft: width < 520 ? 118 : 170,
    marginRight: 28,
    marginBottom: 46,
    style: { background: "transparent", color: PAPER, fontSize: "10px" },
    ariaLabel: `${away} and ${home} league rank comparison`,
    ariaDescription: "Connected dots compare both teams on a common league-rank scale. Rank one is best.",
    x: { label: "League rank · better →", domain: [30, 1], grid: true },
    y: { label: null, domain: data.map((row) => row.label) },
    marks: [
      Plot.link(data, { x1: "awayRank", x2: "homeRank", y1: "label", y2: "label", stroke: MUTED, strokeWidth: 3 }),
      Plot.dot(data, { x: "awayRank", y: "label", fill: BLUE, r: 6 }),
      Plot.dot(data, { x: "homeRank", y: "label", fill: ORANGE, r: 6 }),
      Plot.tip(data.flatMap((row) => [
        { team: away, rank: row.awayRank, label: row.label },
        { team: home, rank: row.homeRank, label: row.label },
      ]), Plot.pointer({
        x: "rank",
        y: "label",
        title: (row) => `${row.team} · ${row.label}: #${row.rank}`,
      })),
    ],
  });
}

export function driverWaterfallPlot(drivers, away, home) {
  let running = 0;
  const data = drivers.slice(0, 8).map((driver) => {
    const start = running;
    running += number(driver.log_odds_contribution) || 0;
    return {
      ...driver,
      start,
      end: running,
      direction: number(driver.log_odds_contribution) >= 0 ? home : away,
    };
  });
  return (width) => Plot.plot({
    width,
    height: Math.max(300, data.length * 37 + 70),
    marginLeft: width < 520 ? 118 : 175,
    marginRight: 34,
    marginBottom: 46,
    style: { background: "transparent", color: PAPER, fontSize: "10px" },
    ariaLabel: "Cumulative matchup model driver waterfall",
    ariaDescription: `Orange steps move the prediction toward ${home}; blue steps move it toward ${away}.`,
    x: { label: "Cumulative log-odds contribution", grid: true },
    y: { label: null, domain: data.map((row) => row.label) },
    color: { domain: [away, home], range: [BLUE, ORANGE], legend: true },
    marks: [
      Plot.ruleX([0], { stroke: PAPER, strokeOpacity: 0.55 }),
      Plot.barX(data, { x1: "start", x2: "end", y: "label", fill: "direction", inset: 5 }),
      Plot.dot(data, { x: "end", y: "label", fill: "direction", r: 4 }),
      Plot.tip(data, Plot.pointer({
        x: "end",
        y: "label",
        title: (row) => `${row.label}: ${number(row.log_odds_contribution) >= 0 ? "+" : ""}${number(row.log_odds_contribution).toFixed(3)} · favors ${row.direction}`,
      })),
    ],
  });
}

// Categorical series slots for multi-entity charts. Validated with the
// dataviz palette checker against the panel surface (#15191f) on all pairs:
// lightness band, chroma, CVD ΔE >= 8.6, normal-vision ΔE >= 16.2, contrast.
// Colour follows entity order (pick order), never rank.
export const SERIES = ["#e8572d", "#3d8fe8", "#1baf7a", "#c84f9b"];
const GRID = "#2a3039";
const HOME = SERIES[0];
const AWAY = SERIES[1];
const darkStyle = (width, size = 10) => ({
  background: "transparent",
  color: PAPER,
  fontSize: `${width < 520 ? size - 1 : size}px`,
});
const signed = (value, digits = 1) => `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
// Narrow charts truncate long category labels; tooltips keep the full text.
const clip = (width, wide = 24, narrow = 14) => (value) => {
  const limit = width < 520 ? narrow : wide;
  const text = String(value);
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
};
const seasonStart = (seasonId) => Number.parseInt(String(seasonId).slice(0, 4), 10);
const seasonTick = (year) => `${String(year).slice(2)}-${String((year + 1) % 100).padStart(2, "0")}`;

export function careerTrendPlot(seasons) {
  const stats = [["PTS", "Points"], ["REB", "Rebounds"], ["AST", "Assists"]];
  const bySeason = new Map(seasons.map((row) => [row.SEASON_ID, row]));
  const data = [...bySeason.values()].flatMap((row) => stats
    .filter(([key]) => finite(row[key]))
    .map(([key, label]) => ({
      season: row.SEASON_ID, year: seasonStart(row.SEASON_ID), stat: label, value: number(row[key]),
    })))
    .filter((row) => Number.isFinite(row.year))
    .sort((first, second) => first.year - second.year);
  const single = new Set(data.map((row) => row.year)).size < 2;
  return (width) => Plot.plot({
    width,
    height: width < 520 ? 250 : 290,
    marginTop: 16,
    marginRight: width < 520 ? 66 : 80,
    marginBottom: 40,
    marginLeft: 40,
    style: darkStyle(width),
    ariaLabel: "Career per-game points, rebounds, and assists by season",
    ariaDescription: `${new Set(data.map((row) => row.season)).size} seasons. All three measures are per game on one axis.`,
    x: { label: "Season", tickFormat: seasonTick, ticks: width < 520 ? 4 : 8, nice: false },
    y: { label: "Per game", grid: true, nice: true, zero: true },
    color: { domain: stats.map(([, label]) => label), range: SERIES.slice(0, 3), legend: true },
    marks: [
      Plot.ruleY([0], { stroke: GRID }),
      single ? null : Plot.lineY(data, { x: "year", y: "value", stroke: "stat", strokeWidth: 2 }),
      Plot.dot(data, { x: "year", y: "value", fill: "stat", r: single ? 6 : 3, stroke: "#15191f", strokeWidth: 2 }),
      Plot.text(data, Plot.selectLast({
        x: "year", y: "value", z: "stat", text: (row) => `${row.stat} ${row.value.toFixed(1)}`,
        dx: 8, textAnchor: "start", fill: PAPER, fontSize: 9,
      })),
      Plot.tip(data, Plot.pointer({
        x: "year", y: "value",
        title: (row) => `${row.season}\n${row.stat}: ${row.value.toFixed(1)} per game`,
      })),
    ],
  });
}

const METRIC_LABELS = {
  PTS: "Scoring", AST: "Playmaking", REB: "Rebounding", STL: "Steals", BLK: "Blocks",
  FG_PCT: "FG%", FG3_PCT: "3P%", FT_PCT: "FT%", NET_RATING: "Net rating", DPM: "DARKO DPM",
  TOV: "Turnovers", MIN: "Minutes", FG3M: "Threes made", TS_PCT: "True shooting",
  USG_PCT: "Usage", PIE: "PIE", PLUS_MINUS: "Plus-minus",
};
export const metricLabel = (key) => METRIC_LABELS[key] || String(key).replaceAll("_", " ");

export function percentileDotPlot(percentiles, peerLabel = "league") {
  const data = Object.entries(percentiles || {})
    .filter(([, value]) => finite(value))
    .map(([key, value]) => ({ key, label: metricLabel(key), value: Math.max(0, Math.min(100, number(value))) }))
    .sort((first, second) => second.value - first.value);
  return (width) => Plot.plot({
    width,
    height: data.length * 28 + 56,
    marginLeft: width < 520 ? 92 : 112,
    marginRight: 36,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: `Percentile rank versus ${peerLabel} peers`,
    ariaDescription: `${data.length} metrics on a common 0 to 100 percentile scale. The vertical rule marks the ${peerLabel} median.`,
    x: { label: `Percentile vs ${peerLabel} · better →`, domain: [0, 100], ticks: [0, 25, 50, 75, 100], grid: true },
    y: { label: null, domain: data.map((row) => row.label), tickFormat: clip(width, 20, 13) },
    marks: [
      Plot.ruleY(data, { y: "label", x1: 0, x2: 100, stroke: GRID, strokeWidth: 1 }),
      Plot.ruleX([50], { stroke: MUTED, strokeWidth: 1.5 }),
      Plot.ruleY(data, { y: "label", x1: 50, x2: "value", stroke: ORANGE, strokeOpacity: 0.45, strokeWidth: 2 }),
      Plot.dot(data, { x: "value", y: "label", fill: ORANGE, r: 5, stroke: "#15191f", strokeWidth: 2 }),
      // Plot's dx is a constant, so near-100 labels go in a separate left-anchored mark.
      Plot.text(data.filter((row) => row.value <= 88), {
        x: "value", y: "label", text: (row) => `${Math.round(row.value)}`, dx: 10, textAnchor: "start", fill: PAPER, fontSize: 9,
      }),
      Plot.text(data.filter((row) => row.value > 88), {
        x: "value", y: "label", text: (row) => `${Math.round(row.value)}`, dx: -10, textAnchor: "end", fill: PAPER, fontSize: 9,
      }),
      Plot.tip(data, Plot.pointerY({
        x: "value", y: "label",
        title: (row) => `${row.label}: ${Math.round(row.value)}th percentile vs ${peerLabel}`,
      })),
    ],
  });
}

export function compareDumbbellPlot(names, percentiles, metrics) {
  const rows = metrics.map(([key, label]) => {
    const points = names
      .filter((name) => finite(percentiles?.[name]?.[key]))
      .map((name) => ({ name, label, value: number(percentiles[name][key]) }));
    const values = points.map((point) => point.value);
    return { label, points, low: Math.min(...values), high: Math.max(...values) };
  }).filter((row) => row.points.length >= 2);
  const dots = rows.flatMap((row) => row.points);
  return (width) => Plot.plot({
    width,
    height: rows.length * 34 + 70,
    marginLeft: width < 520 ? 96 : 120,
    marginRight: 24,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: `League percentile comparison for ${names.join(", ")}`,
    ariaDescription: "Each row places every player on the same 0 to 100 league-percentile scale. The grey bar spans the gap between the lowest and highest player.",
    x: { label: "League percentile · better →", domain: [0, 100], ticks: [0, 25, 50, 75, 100], grid: true },
    y: { label: null, domain: rows.map((row) => row.label), tickFormat: clip(width, 20, 13) },
    color: { domain: names, range: SERIES.slice(0, names.length), legend: true },
    marks: [
      Plot.ruleX([50], { stroke: MUTED, strokeWidth: 1.5 }),
      Plot.ruleY(rows, { y: "label", x1: "low", x2: "high", stroke: MUTED, strokeOpacity: 0.55, strokeWidth: 4 }),
      Plot.dot(dots, { x: "value", y: "label", fill: "name", r: 6, stroke: "#15191f", strokeWidth: 2 }),
      Plot.tip(dots, Plot.pointer({
        x: "value", y: "label",
        title: (row) => `${row.name}\n${row.label}: ${Math.round(row.value)}th percentile`,
      })),
    ],
  });
}

export function compareCareerPlot(names, careerSeasons, key = "PTS", label = "Points per game") {
  const data = names.flatMap((name) => {
    const bySeason = new Map((careerSeasons?.[name] || []).map((row) => [row.SEASON_ID, row]));
    return [...bySeason.values()]
      .filter((row) => finite(row[key]))
      .map((row) => ({ name, season: row.SEASON_ID, year: seasonStart(row.SEASON_ID), value: number(row[key]) }))
      .filter((row) => Number.isFinite(row.year))
      .sort((first, second) => first.year - second.year);
  });
  return (width) => Plot.plot({
    width,
    height: width < 520 ? 260 : 300,
    marginTop: 16,
    marginRight: width < 520 ? 24 : 36,
    marginBottom: 40,
    marginLeft: 40,
    style: darkStyle(width),
    ariaLabel: `${label} by season for ${names.join(", ")}`,
    ariaDescription: "One line per player across their career seasons on a shared per-game axis.",
    x: { label: "Season", tickFormat: seasonTick, ticks: width < 520 ? 4 : 8 },
    y: { label, grid: true, zero: true, nice: true },
    color: { domain: names, range: SERIES.slice(0, names.length), legend: true },
    marks: [
      Plot.ruleY([0], { stroke: GRID }),
      Plot.lineY(data, { x: "year", y: "value", stroke: "name", strokeWidth: 2 }),
      Plot.dot(data, { x: "year", y: "value", fill: "name", r: 3, stroke: "#15191f", strokeWidth: 1.5 }),
      Plot.tip(data, Plot.pointer({
        x: "year", y: "value",
        title: (row) => `${row.name} · ${row.season}\n${row.value.toFixed(1)} ${label.toLowerCase()}`,
      })),
    ],
  });
}

// Small multiples share the split order but give each measure its own x-scale,
// avoiding one cramped dual-unit axis.
export function splitSmallMultiples(rows, metrics) {
  const order = rows.map((row) => String(row.Split));
  return (width) => {
    const grid = document.createElement("div");
    grid.className = "small-multiples";
    const columns = width < 520 ? 1 : width < 760 ? 2 : 3;
    const panelWidth = Math.max(260, Math.floor((width - (columns - 1) * 14) / columns));
    metrics.forEach(([key, label, percent]) => {
      const data = rows
        .filter((row) => finite(row[key]))
        .map((row) => ({ split: String(row.Split), value: number(row[key]) * (percent ? 100 : 1), gp: row.GP }));
      if (!data.length) return;
      const values = data.map((row) => row.value);
      const signedMetric = values.some((value) => value < 0);
      const panel = document.createElement("div");
      panel.className = "small-multiple";
      const title = document.createElement("h5");
      title.textContent = label;
      panel.append(title, Plot.plot({
        width: panelWidth,
        height: order.length * 22 + 44,
        marginLeft: 78,
        marginRight: 34,
        marginBottom: 30,
        style: darkStyle(panelWidth, 9),
        ariaLabel: `${label} by split`,
        x: { label: null, grid: true, nice: true, zero: true, ticks: 4 },
        y: { label: null, domain: order },
        marks: [
          signedMetric ? Plot.ruleX([0], { stroke: MUTED }) : null,
          Plot.ruleY(data, { y: "split", x1: 0, x2: "value", stroke: ORANGE, strokeOpacity: 0.45, strokeWidth: 2 }),
          Plot.dot(data, { x: "value", y: "split", fill: ORANGE, r: 4.5, stroke: "#15191f", strokeWidth: 1.5 }),
          Plot.text(data, {
            x: "value", y: "split", text: (row) => (percent ? `${row.value.toFixed(1)}%` : signedMetric ? signed(row.value) : row.value.toFixed(1)),
            dx: 9, textAnchor: "start", fill: MUTED, fontSize: 8,
          }),
          Plot.tip(data, Plot.pointerY({
            x: "value", y: "split",
            title: (row) => `${row.split} · ${label}: ${percent ? `${row.value.toFixed(1)}%` : row.value.toFixed(1)} · ${row.gp ?? "—"} games`,
          })),
        ],
      }));
      grid.append(panel);
    });
    return grid;
  };
}

export function teamQuadrantPlot(leagueForm, team) {
  const data = leagueForm
    .filter((row) => finite(row.form_ortg) && finite(row.form_drtg))
    .map((row) => ({ ...row, ortg: number(row.form_ortg), drtg: number(row.form_drtg), selected: row.team === team }));
  const ortgMean = average(data, "ortg");
  const drtgMean = average(data, "drtg");
  const others = data.filter((row) => !row.selected);
  const selected = data.filter((row) => row.selected);
  return (width) => Plot.plot({
    width,
    height: width < 520 ? 330 : 400,
    marginTop: 24,
    marginRight: 24,
    marginBottom: 46,
    marginLeft: 52,
    style: darkStyle(width),
    ariaLabel: `${team} offense and defense versus the league`,
    ariaDescription: `Offensive rating runs left to right; defensive rating is flipped so better defense is higher. Solid grey lines mark league averages across ${data.length} teams.`,
    x: { label: "Offensive rating · better →", nice: true, grid: true },
    y: { label: "↑ Defensive rating · better", reverse: true, nice: true, grid: true },
    marks: [
      Plot.ruleX([ortgMean], { stroke: MUTED }),
      Plot.ruleY([drtgMean], { stroke: MUTED }),
      Plot.text(["Good offense · good defense"], { frameAnchor: "top-right", dy: -14, fill: MUTED, fontSize: 9 }),
      Plot.dot(others, { x: "ortg", y: "drtg", fill: MUTED, fillOpacity: 0.7, r: 5 }),
      Plot.text(others, { x: "ortg", y: "drtg", text: "team", dy: -10, fill: MUTED, fontSize: 8 }),
      Plot.dot(selected, { x: "ortg", y: "drtg", fill: ORANGE, r: 9, stroke: "#15191f", strokeWidth: 2 }),
      Plot.text(selected, { x: "ortg", y: "drtg", text: "team", dy: -16, fill: PAPER, fontSize: 12, fontWeight: 700 }),
      Plot.tip(data, Plot.pointer({
        x: "ortg", y: "drtg",
        title: (row) => `${row.team}\nORTG ${row.ortg.toFixed(1)} · DRTG ${row.drtg.toFixed(1)}${finite(row.form_net) ? ` · NET ${signed(number(row.form_net))}` : ""}`,
      })),
    ],
  });
}

export function fourFactorBulletPlot(factors, labels, teamCount = 30) {
  const keys = ["off_efg", "off_tov_pct", "off_oreb_pct", "off_ft_rate", "def_efg", "def_tov_pct", "def_dreb_pct", "def_ft_rate"];
  // One shared y-scale (facets would repeat every factor in both panels), so
  // the side lives in the row label and offense rows come first.
  const data = keys
    .filter((key) => finite(factors?.[key]) && finite(factors?.[`${key}_rank`]))
    .map((key) => ({
      side: key.startsWith("off") ? "Offense" : "Defense",
      label: `${key.startsWith("off") ? "OFF" : "DEF"} · ${labels?.[key] || key}`,
      value: number(factors[key]) * 100,
      rank: number(factors[`${key}_rank`]),
    }));
  const median = (teamCount + 1) / 2;
  return (width) => Plot.plot({
    width,
    height: data.length * 32 + 56,
    marginLeft: width < 520 ? 104 : 120,
    marginRight: 96,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: "Four factors league rank bullet chart",
    ariaDescription: `Bars grow from last place toward first. The white tick marks the league median rank of ${median}.`,
    x: { label: "League rank · better →", domain: [teamCount, 1], ticks: [teamCount, 20, 10, 1], grid: true },
    y: { label: null, domain: data.map((row) => row.label) },
    marks: [
      Plot.ruleY(data, { y: "label", x1: teamCount, x2: 1, stroke: GRID, strokeWidth: 8 }),
      Plot.ruleY(data, { y: "label", x1: teamCount, x2: "rank", stroke: ORANGE, strokeWidth: 8 }),
      Plot.tickX(data, { y: "label", x: median, stroke: PAPER, strokeOpacity: 0.7, strokeWidth: 2 }),
      Plot.text(data, {
        y: "label", x: 1, text: (row) => `#${row.rank} · ${row.value.toFixed(1)}%`,
        dx: 8, textAnchor: "start", fill: PAPER, fontSize: 9,
      }),
      Plot.tip(data, Plot.pointerY({
        y: "label", x: "rank",
        title: (row) => `${row.side} ${row.label.slice(6)}: ${row.value.toFixed(1)}% · rank ${row.rank} of ${teamCount}`,
      })),
    ],
  });
}

export function onOffSwingPlot(rows) {
  const data = rows
    .filter((row) => finite(row.NET_DIFF))
    .map((row) => ({ ...row, swing: number(row.NET_DIFF), sign: number(row.NET_DIFF) >= 0 ? "Team better with player" : "Team better without player" }))
    .sort((first, second) => second.swing - first.swing);
  return (width) => Plot.plot({
    width,
    height: data.length * 25 + 82,
    marginLeft: width < 520 ? 104 : 140,
    marginRight: 44,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: "On/off net rating swing by player",
    ariaDescription: "Bars to the right mean the team's net rating is better with the player on the floor; bars to the left mean worse.",
    x: { label: "On/off net rating swing (points per 100)", grid: true, nice: true },
    y: { label: null, domain: data.map((row) => row.PLAYER_NAME), tickFormat: clip(width) },
    color: { domain: ["Team better with player", "Team better without player"], range: [LIME, RED], legend: true },
    marks: [
      Plot.barX(data, { y: "PLAYER_NAME", x: "swing", fill: "sign", insetTop: 5, insetBottom: 5, rx: 2 }),
      Plot.ruleX([0], { stroke: PAPER, strokeOpacity: 0.55 }),
      Plot.text(data.filter((row) => row.swing >= 0), {
        y: "PLAYER_NAME", x: "swing", text: (row) => signed(row.swing), dx: 6, textAnchor: "start", fill: PAPER, fontSize: 9,
      }),
      // Negative values sit just right of zero so they never collide with the name axis.
      Plot.text(data.filter((row) => row.swing < 0), {
        y: "PLAYER_NAME", x: 0, text: (row) => signed(row.swing), dx: 6, textAnchor: "start", fill: PAPER, fontSize: 9,
      }),
      Plot.tip(data, Plot.pointerY({
        y: "PLAYER_NAME", x: "swing",
        title: (row) => `${row.PLAYER_NAME}: ${signed(row.swing)} swing · ${number(row.MIN_ON).toFixed(0)} minutes on`,
      })),
    ],
  });
}

export function leaderboardPlot(records, { key, label, nameKey, percent = false, limit = 15 }) {
  const scale = percent ? 100 : 1;
  const data = records
    .filter((row) => finite(row[key]))
    .map((row) => ({ name: row[nameKey], team: row.TEAM_ABBREVIATION, value: number(row[key]) * scale }))
    .sort((first, second) => second.value - first.value)
    .slice(0, limit);
  const format = (value) => (percent ? `${value.toFixed(1)}%` : Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(2));
  return (width) => Plot.plot({
    width,
    height: data.length * 25 + 60,
    marginLeft: width < 520 ? 110 : 150,
    marginRight: 52,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: `${label} leaderboard`,
    ariaDescription: `The ${data.length} highest ${label} values in the filtered sample, ordered from highest.`,
    x: { label, grid: true, nice: true, zero: true },
    y: { label: null, domain: data.map((row) => row.name), tickFormat: clip(width) },
    marks: [
      Plot.barX(data, { y: "name", x: "value", fill: ORANGE, insetTop: 5, insetBottom: 5, rx: 2 }),
      Plot.ruleX([0], { stroke: GRID }),
      Plot.text(data, { y: "name", x: "value", text: (row) => format(row.value), dx: 6, textAnchor: "start", fill: PAPER, fontSize: 9 }),
      Plot.tip(data, Plot.pointerY({
        y: "name", x: "value", title: (row) => `${row.name}${row.team ? ` · ${row.team}` : ""}\n${label}: ${format(row.value)}`,
      })),
    ],
  });
}

// Labels for points in the right third anchor to their end so they stay inside the frame.
function edgeAwareLabels(points, xs, options) {
  const low = Math.min(...xs);
  const high = Math.max(...xs);
  const cut = low + (high - low) * 0.66;
  return [
    Plot.text(points.filter((row) => row[options.x] <= cut), { ...options, textAnchor: "middle" }),
    Plot.text(points.filter((row) => row[options.x] > cut), { ...options, textAnchor: "end", dx: -4 }),
  ];
}

export function metricScatterPlot(records, { xKey, yKey, xLabel, yLabel, nameKey, xPercent = false, yPercent = false }) {
  const data = records
    .filter((row) => finite(row[xKey]) && finite(row[yKey]))
    .map((row) => ({ name: row[nameKey], x: number(row[xKey]) * (xPercent ? 100 : 1), y: number(row[yKey]) * (yPercent ? 100 : 1) }));
  const xMean = average(data, "x");
  const yMean = average(data, "y");
  const labeled = [...data].sort((first, second) => second.y - first.y);
  return (width) => Plot.plot({
    width,
    height: width < 520 ? 340 : 420,
    marginTop: 20,
    marginRight: 30,
    marginBottom: 48,
    marginLeft: 58,
    grid: true,
    style: darkStyle(width),
    ariaLabel: `${yLabel} by ${xLabel} scatterplot`,
    ariaDescription: `${data.length} rows. Solid grey lines mark the sample average on each measure.`,
    x: { label: xLabel, nice: true },
    y: { label: yLabel, nice: true },
    marks: [
      Plot.ruleX([xMean], { stroke: MUTED }),
      Plot.ruleY([yMean], { stroke: MUTED }),
      Plot.dot(data, { x: "x", y: "y", fill: ORANGE, fillOpacity: 0.76, stroke: "#15191f", strokeWidth: 1, r: width < 520 ? 4.5 : 5.5 }),
      ...edgeAwareLabels(labeled.slice(0, width < 520 ? 3 : 6), data.map((row) => row.x), { x: "x", y: "y", text: "name", dy: -10, fill: PAPER, fontSize: width < 520 ? 8 : 9 }),
      Plot.tip(data, Plot.pointer({
        x: "x", y: "y", title: (row) => `${row.name}\n${xLabel} ${row.x.toFixed(2)} · ${yLabel} ${row.y.toFixed(2)}`,
      })),
    ],
  });
}

export function advancedBoxDumbbellPlot(advanced, away, home) {
  const metrics = [["EFG_PCT", "eFG%"], ["TS_PCT", "TS%"], ["TOV_RATE", "TOV% (lower better)"], ["FT_RATE", "FT rate"]];
  const byTeam = Object.fromEntries((advanced || []).map((row) => [row.TEAM, row]));
  const rows = metrics
    .filter(([key]) => finite(byTeam[away]?.[key]) && finite(byTeam[home]?.[key]))
    .map(([key, label]) => ({ label, awayValue: number(byTeam[away][key]) * 100, homeValue: number(byTeam[home][key]) * 100 }));
  const dots = rows.flatMap((row) => [
    { team: away, label: row.label, value: row.awayValue },
    { team: home, label: row.label, value: row.homeValue },
  ]);
  return (width) => Plot.plot({
    width,
    height: rows.length * 40 + 82,
    marginLeft: width < 520 ? 112 : 132,
    marginRight: 28,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: `${away} and ${home} advanced box comparison`,
    ariaDescription: "Each row connects the two teams on the same percentage scale. Turnover rate is better when lower.",
    x: { label: "Percent", grid: true, nice: true, zero: true },
    y: { label: null, domain: rows.map((row) => row.label) },
    color: { domain: [away, home], range: [AWAY, HOME], legend: true },
    marks: [
      Plot.link(rows, { y1: "label", y2: "label", x1: "awayValue", x2: "homeValue", stroke: MUTED, strokeWidth: 3 }),
      Plot.dot(dots, { x: "value", y: "label", fill: "team", r: 6.5, stroke: "#15191f", strokeWidth: 2 }),
      Plot.tip(dots, Plot.pointer({ x: "value", y: "label", title: (row) => `${row.team} · ${row.label}: ${row.value.toFixed(1)}%` })),
    ],
  });
}

export function gameFlowPlot(timeline, away, home) {
  const data = (timeline || [])
    .filter((point) => finite(point.ELAPSED) && finite(point.HOME_WIN_PROB))
    .map((point) => ({ ...point, minute: number(point.ELAPSED) / 60, probability: number(point.HOME_WIN_PROB) * 100 }));
  const end = Math.max(48, ...data.map((point) => point.minute));
  const periods = [12, 24, 36, ...Array.from({ length: Math.max(0, Math.ceil((end - 48) / 5)) }, (_, index) => 48 + index * 5)];
  return (width) => Plot.plot({
    width,
    height: width < 520 ? 240 : 280,
    marginTop: 18,
    marginRight: 54,
    marginBottom: 40,
    marginLeft: 44,
    style: darkStyle(width),
    ariaLabel: `${home} win probability through the game`,
    ariaDescription: `Above 50% favours ${home}; below favours ${away}. Vertical rules mark period breaks.`,
    x: { label: "Game minute", domain: [0, end], ticks: [0, 12, 24, 36, 48].filter((tick) => tick <= end) },
    y: { label: `${home} win probability`, domain: [0, 100], ticks: [0, 25, 50, 75, 100], tickFormat: (value) => `${value}%`, grid: true },
    marks: [
      Plot.ruleX(periods.filter((minute) => minute < end), { stroke: GRID }),
      Plot.ruleY([50], { stroke: MUTED }),
      Plot.text([`${home} favoured`], { frameAnchor: "top-left", dx: 6, dy: 4, fill: MUTED, fontSize: 9 }),
      Plot.text([`${away} favoured`], { frameAnchor: "bottom-left", dx: 6, dy: -4, fill: MUTED, fontSize: 9 }),
      Plot.lineY(data, { x: "minute", y: "probability", stroke: HOME, strokeWidth: 2, curve: "step-after" }),
      Plot.dot(data.slice(-1), { x: "minute", y: "probability", fill: HOME, r: 5, stroke: "#15191f", strokeWidth: 2 }),
      Plot.text(data.slice(-1), { x: "minute", y: "probability", text: (point) => `${point.probability.toFixed(0)}%`, dx: 9, textAnchor: "start", fill: PAPER, fontSize: 10 }),
      Plot.ruleX(data, Plot.pointerX({ x: "minute", stroke: MUTED })),
      Plot.tip(data, Plot.pointerX({
        x: "minute", y: "probability",
        title: (point) => `Q${point.PERIOD ?? "—"} ${point.CLOCK ?? ""}\n${away} ${point.AWAY_SCORE ?? "—"} – ${point.HOME_SCORE ?? "—"} ${home}\n${home} win ${point.probability.toFixed(0)}%`,
      })),
    ],
  });
}

export function calibrationPlot(rows) {
  const data = (rows || [])
    .filter((row) => finite(row.mean_probability) && finite(row.observed_rate))
    .map((row) => ({ ...row, forecast: number(row.mean_probability) * 100, observed: number(row.observed_rate) * 100, count: number(row.count) || 0 }));
  return (width) => Plot.plot({
    width,
    height: Math.min(420, Math.max(300, width * 0.7)),
    marginTop: 16,
    marginRight: 20,
    marginBottom: 46,
    marginLeft: 52,
    style: darkStyle(width),
    ariaLabel: "Playoff probability calibration curve",
    ariaDescription: "Points on the diagonal mean forecasts matched observed playoff rates. Dot area is the number of team-seasons in the bin.",
    x: { label: "Mean forecast probability", domain: [0, 100], tickFormat: (value) => `${value}%`, grid: true },
    y: { label: "Observed playoff rate", domain: [0, 100], tickFormat: (value) => `${value}%`, grid: true },
    r: { range: [4, 13] },
    marks: [
      Plot.line([[0, 0], [100, 100]], { stroke: MUTED, strokeWidth: 1.5 }),
      Plot.text(["Perfect calibration"], { x: 70, y: 76, rotate: 0, fill: MUTED, fontSize: 9, textAnchor: "end" }),
      Plot.link(data, { x1: "forecast", y1: "forecast", x2: "forecast", y2: "observed", stroke: ORANGE, strokeOpacity: 0.45, strokeWidth: 2 }),
      Plot.lineY(data, { x: "forecast", y: "observed", stroke: ORANGE, strokeWidth: 2 }),
      Plot.dot(data, { x: "forecast", y: "observed", r: "count", fill: ORANGE, stroke: "#15191f", strokeWidth: 2 }),
      Plot.tip(data, Plot.pointer({
        x: "forecast", y: "observed",
        title: (row) => `Forecast bin ${(number(row.lower) * 100).toFixed(0)}–${(number(row.upper) * 100).toFixed(0)}%\nMean forecast ${row.forecast.toFixed(0)}% · observed ${row.observed.toFixed(0)}% · ${row.count} team-seasons`,
      })),
    ],
  });
}

export function journeyPlot(journey) {
  const data = (journey || []).filter((row) => finite(row.accuracy)).map((row, index) => ({ ...row, step: index, accuracy: number(row.accuracy) }));
  const best = Math.max(...data.map((row) => row.accuracy));
  return (width) => Plot.plot({
    width,
    height: data.length * 30 + 56,
    marginLeft: width < 520 ? 130 : 190,
    marginRight: 44,
    marginBottom: 40,
    style: darkStyle(width),
    ariaLabel: "Outcome model accuracy by modeling stage",
    ariaDescription: "Holdout accuracy for each modeling stage in the order it was tried. The axis is zoomed to the observed range, not zero-based.",
    x: { label: "Holdout accuracy (%) · zoomed", nice: true, grid: true },
    y: { label: null, domain: data.map((row) => row.stage), tickFormat: clip(width, 30, 18) },
    marks: [
      Plot.line(data, { x: "accuracy", y: "stage", stroke: MUTED, strokeWidth: 1.5 }),
      Plot.dot(data, { x: "accuracy", y: "stage", fill: (row) => (row.accuracy === best ? ORANGE : MUTED), r: 5.5, stroke: "#15191f", strokeWidth: 2 }),
      Plot.text(data, { x: "accuracy", y: "stage", text: (row) => `${row.accuracy.toFixed(1)}%`, dx: 10, textAnchor: "start", fill: PAPER, fontSize: 9 }),
    ],
  });
}
