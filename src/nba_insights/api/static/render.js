// Shared HTML renderers. Pure functions: data in, markup string out.
import { escapeHTML } from "./core.js";

// Exact values behind every chart, as a real table for screen readers.
export function dataTable(caption, headers, rows) {
  return `<table class="viz-table"><caption>${escapeHTML(caption)}</caption><thead><tr>${headers.map(header => `<th scope="col">${escapeHTML(header)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map((cell,index) => index === 0 ? `<th scope="row">${escapeHTML(cell)}</th>` : `<td>${escapeHTML(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
