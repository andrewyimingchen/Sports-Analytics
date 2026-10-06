// Unit tests for the PWA's pure rendering helpers (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { deepValue, escapeHTML, fmt, money } from "../../src/nba_insights/api/static/core.js";
import { dataTable } from "../../src/nba_insights/api/static/render.js";
import {
  SERIES,
  SHAPES,
  clip,
  metricLabel,
  seasonTick,
} from "../../src/nba_insights/api/static/visualizations.js";

test("escapeHTML neutralises markup and quotes", () => {
  assert.equal(escapeHTML(`<a href="x" title='y'>&</a>`),
    "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;");
  assert.equal(escapeHTML(null), "");
  assert.equal(escapeHTML(0), "0");
});

test("fmt and money format numbers and mark missing values", () => {
  assert.equal(fmt(27.66), "27.7");
  assert.equal(fmt("12", 0), "12");
  assert.equal(fmt(undefined), "—");
  assert.equal(fmt(null), "—"); // JSON null is missing, not zero
  assert.equal(fmt(""), "—");
  assert.equal(fmt(0), "0.0");
  assert.equal(fmt("n/a"), "—");
  assert.equal(money(59_000_000), "$59.0M");
  assert.equal(money(null), "—");
});

test("deepValue unwraps only fulfilled results", () => {
  assert.equal(deepValue({ status: "fulfilled", value: 3 }), 3);
  assert.equal(deepValue({ status: "rejected", reason: new Error("x") }), null);
});

test("dataTable builds a captioned table with scoped headers", () => {
  const html = dataTable("Career", ["Season", "PTS"], [["2025-26", "27.7"], ["2024-25", "29.6"]]);
  assert.match(html, /^<table class="viz-table"><caption>Career<\/caption>/);
  assert.equal((html.match(/<th scope="col">/g) || []).length, 2);
  // the first cell of each row heads that row
  assert.equal((html.match(/<th scope="row">/g) || []).length, 2);
  assert.match(html, /<td>27\.7<\/td>/);
});

test("dataTable escapes every caption, header, and cell", () => {
  const html = dataTable("<b>x</b>", ["<i>"], [["<script>alert(1)</script>", "a&b"]]);
  assert.doesNotMatch(html, /<script>|<b>|<i>/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /a&amp;b/);
});

test("series palette and shapes cover four entities without repeats", () => {
  assert.equal(SERIES.length, 4);
  assert.equal(new Set(SERIES).size, 4);
  assert.deepEqual(SHAPES, ["circle", "square", "triangle", "diamond"]);
});

test("metricLabel names known stats and humanises the rest", () => {
  assert.equal(metricLabel("PTS"), "Scoring");
  assert.equal(metricLabel("DPM"), "DARKO DPM");
  assert.equal(metricLabel("DRIVE_PTS"), "DRIVE PTS");
});

test("seasonTick abbreviates season start years across centuries", () => {
  assert.equal(seasonTick(2025), "25-26");
  assert.equal(seasonTick(1999), "99-00");
  assert.equal(seasonTick(2009), "09-10");
});

test("clip truncates long labels on narrow charts only", () => {
  const name = "Shai Gilgeous-Alexander";
  assert.equal(clip(400)(name), "Shai Gilgeous…");
  assert.equal(clip(400)(name).length, 14);
  assert.equal(clip(900)(name), name);
  assert.equal(clip(400)("Jokic"), "Jokic");
});
