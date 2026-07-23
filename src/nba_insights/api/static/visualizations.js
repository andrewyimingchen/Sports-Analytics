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
