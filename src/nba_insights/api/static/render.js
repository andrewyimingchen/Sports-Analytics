// Shared HTML renderers. Pure functions: data in, markup string out.
import { escapeHTML } from "./core.js";

// Exact values behind every chart, as a real table for screen readers.
export function dataTable(caption, headers, rows) {
  return `<table class="viz-table"><caption>${escapeHTML(caption)}</caption><thead><tr>${headers.map(header => `<th scope="col">${escapeHTML(header)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map((cell,index) => index === 0 ? `<th scope="row">${escapeHTML(cell)}</th>` : `<td>${escapeHTML(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

// Readable names for the optional sections the API can omit (`degraded`).
const SECTION_LABELS = {
  next_slate: "Next games", lineups: "Lineups", on_off: "On/off impact",
  salaries: "Salary context", finances: "Contract book", scouting_take: "Scouting take",
  four_factors: "Four factors", standings: "Standings", clutch: "Clutch context",
  draft: "Draft pedigree", history: "Salary history", shot_quality: "Shot quality",
  league_game_finder: "Cached box score", box_score: "Box score",
};
const REASON_TEXT = {
  upstream_unavailable: "stats.nba.com did not respond; try again later",
  data_unavailable: "not available for this sample yet",
  artifact_unavailable: "the model is not trained on this server",
};

export function sectionLabel(section) {
  const [base] = String(section).split(":");  // e.g. "shot_quality:203999"
  return SECTION_LABELS[base] || base.replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
}

// One accessible notice for a response's `degraded` list, grouped by reason;
// "" when nothing was omitted. Repeated per-player sections collapse to one.
export function degradedNotice(degraded) {
  if (!Array.isArray(degraded) || !degraded.length) return "";
  const byReason = new Map();
  for (const item of degraded) {
    const labels = byReason.get(item.reason) || new Set();
    labels.add(sectionLabel(item.section));
    byReason.set(item.reason, labels);
  }
  const parts = [...byReason].map(([reason, labels]) =>
    `${[...labels].join(", ")}: ${REASON_TEXT[reason] || "unavailable right now"}`);
  return `<p class="degraded-note" role="status"><b>Partial data</b> ${escapeHTML(parts.join(". "))}.</p>`;
}

// Says when a view shows a different season than the one asked for, e.g. a
// player's context from last season before their first game this season.
export function seasonNotice(shown, expected, why) {
  if (!shown || !expected || shown === expected) return "";
  return `<p class="degraded-note" role="status"><b>Showing ${escapeHTML(shown)}</b> ${escapeHTML(why)}</p>`;
}
