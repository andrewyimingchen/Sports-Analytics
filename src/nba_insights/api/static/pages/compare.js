// Compare: two to four players on shared scales.
import { $, api, escapeHTML, fmt } from "../core.js";
import { dataTable } from "../render.js";
import {
  compareCareerPlot,
  compareDumbbellPlot,
  mountChart,
} from "../visualizations.js";

const comparePicks = {a:null,b:null,c:null,d:null};
function setupCompareSearch(key) {
  const input = $(`compare-${key}`), results = $(`compare-${key}-results`);
  let timer;
  input.addEventListener("input", () => {
    comparePicks[key] = null;
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 3) { results.classList.add("hidden"); return; }
    timer = setTimeout(async () => {
      try {
        const players = await api(`/players/search?q=${encodeURIComponent(q)}`);
        results.innerHTML = players.slice(0,8).map(player => `<button data-name="${escapeHTML(player.full_name)}">${escapeHTML(player.full_name)}<span>${player.is_active ? "ACTIVE" : "HISTORICAL"}</span></button>`).join("") || '<div class="search-hint">No matches.</div>';
        results.classList.remove("hidden");
      } catch (error) { results.innerHTML = `<div class="error">${escapeHTML(error.message)}</div>`; results.classList.remove("hidden"); }
    }, 220);
  });
  results.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    comparePicks[key] = button.dataset.name; input.value = button.dataset.name; results.classList.add("hidden");
  });
}
setupCompareSearch("a"); setupCompareSearch("b"); setupCompareSearch("c"); setupCompareSearch("d");
const compareProfileMetrics = [
  ["PTS","Scoring"], ["AST","Playmaking"], ["REB","Rebounding"],
  ["STL","Steals"], ["BLK","Rim protection"], ["FG_PCT","FG efficiency"],
  ["DPM","Overall impact"]
];
function compareProfileMetricsFor(names, percentiles) {
  const eligible = names.filter(name => compareProfileMetrics.filter(([stat]) =>
    Number.isFinite(Number(percentiles?.[name]?.[stat]))).length >= 3);
  const metrics = compareProfileMetrics.filter(([stat]) => eligible.length >= 2 && eligible.every(name =>
    Number.isFinite(Number(percentiles[name][stat]))));
  return { eligible, metrics: metrics.length >= 3 ? metrics : [] };
}
function mountCompareVisuals(names, result) {
  const { eligible, metrics } = compareProfileMetricsFor(names, result.percentiles);
  if (metrics.length) {
    const leads = Object.fromEntries(eligible.map(name => [name, 0]));
    metrics.forEach(([stat]) => {
      const best = Math.max(...eligible.map(name => Number(result.percentiles[name][stat])));
      eligible.forEach(name => { if (Number(result.percentiles[name][stat]) === best) leads[name]++; });
    });
    const leader = eligible.reduce((best, name) => leads[name] > leads[best] ? name : best);
    const excluded = names.filter(name => !eligible.includes(name));
    mountChart($("compare-skill-chart"),{
      title:"At-a-glance skill profile",
      takeaway:`${leader} leads ${leads[leader]} of ${metrics.length} skills. Long grey bars mark the biggest gaps between players.`,
      description:`LEAGUE PERCENTILE · HIGHER IS BETTER · ${result.season} qualified players.${excluded.length ? ` No qualifying percentile sample for ${excluded.join(", ")}.` : ""}`,
      plotFactory:compareDumbbellPlot(eligible,result.percentiles,metrics),
      tableHTML:dataTable("League percentiles by player",["Skill",...eligible],metrics.map(([stat,label]) => [label,...eligible.map(name => `${Math.round(result.percentiles[name][stat])}th`)])),
      dataLabel:"View exact percentiles",
    });
  } else {
    $("compare-skill-chart").innerHTML = '<div class="data-figure"><div class="figure-heading"><h4>At-a-glance skill profile</h4><p>The percentile view needs at least two active players with a qualifying current-season sample. Exact career and season values remain below.</p></div></div>';
  }
  const withCareer = names.filter(name => (result.career_seasons?.[name] || []).length);
  if (withCareer.length >= 2) mountChart($("compare-career-chart"),{
    title:"Scoring careers",
    takeaway:"Lines show how each scoring arc rose, peaked, or held; hover any season for the exact value.",
    description:"Points per game by season start year · one line per player.",
    plotFactory:compareCareerPlot(withCareer,result.career_seasons),
    tableHTML:dataTable("Points per game by season",["Season",...withCareer],[...new Set(withCareer.flatMap(name=>result.career_seasons[name].map(row=>row.SEASON_ID)))].sort().reverse().map(season=>[season,...withCareer.map(name=>{const row=result.career_seasons[name].find(item=>item.SEASON_ID===season);return row?fmt(row.PTS):"—";})])),
    dataLabel:"View every season",
  });
}
$("compare-go").addEventListener("click", async () => {
  const names = Object.values(comparePicks).filter(Boolean);
  if (names.length < 2 || new Set(names).size !== names.length) {
    $("compare-output").innerHTML = '<div class="error">Choose two to four different players from the search results.</div>'; return;
  }
  $("compare-output").innerHTML = '<div class="empty-state" style="min-height:280px"><div class="loading">BUILDING HEAD-TO-HEAD…</div></div>';
  try {
    const query = names.map(name => `names=${encodeURIComponent(name)}`).join("&");
    const result = await api(`/compare?${query}`), stats = result.stats;
    const rows = [...new Set(names.flatMap(name => Object.keys(stats[name] || {})))];
    const lowerBetter = new Set(["TOV"]);
    const body = rows.map(stat => {
      const values = names.map(name => Number(stats[name]?.[stat]));
      const valid = values.filter(Number.isFinite), best = valid.length ? (lowerBetter.has(stat) ? Math.min(...valid) : Math.max(...valid)) : null;
      return `<div class="compare-table-row"><label>${escapeHTML(stat.replaceAll("_"," "))}</label>${values.map(value => `<span class="${value === best ? "winner" : ""}">${Number.isFinite(value) ? fmt(value, stat === "GP" ? 0 : 1) : "—"}</span>`).join("")}</div>`;
    }).join("");
    const grid=`var(--compare-label,120px) repeat(${names.length},minmax(0,1fr))`;
    const careerStats=[...new Set(names.flatMap(name=>Object.keys(result.career?.[name]||{})))];
    const careerRows=careerStats.map(stat=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${escapeHTML(stat.replaceAll("_"," "))}</label>${names.map(name=>`<span>${result.career?.[name]?.[stat]==null?"—":fmt(result.career[name][stat],stat==="GP"?0:2)}</span>`).join("")}</div>`).join("");
    const pctStats=[...new Set(names.flatMap(name=>Object.keys(result.percentiles?.[name]||{})))];
    const pctRows=pctStats.map(stat=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${escapeHTML(stat.replaceAll("_"," "))}</label>${names.map(name=>`<span>${result.percentiles?.[name]?.[stat]==null?"—":fmt(result.percentiles[name][stat],0)+"th"}</span>`).join("")}</div>`).join("");
    const qualityRows=[["XEFG","Shot diet (xeFG%)"],["EFG","Actual eFG%"],["MAKING","Shot making"]].map(([stat,label])=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${label}</label>${names.map(name=>`<span>${result.shot_quality?.[name]?.[stat]==null?"—":`${Number(result.shot_quality[name][stat])>=0&&stat==="MAKING"?"+":""}${fmt(Number(result.shot_quality[name][stat])*100,1)}`}</span>`).join("")}</div>`).join("");
    const seasonRows=[...new Set(names.flatMap(name=>(result.career_seasons?.[name]||[]).map(row=>row.SEASON_ID)))].sort().reverse().map(season=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${escapeHTML(season)}</label>${names.map(name=>{const row=(result.career_seasons?.[name]||[]).find(item=>item.SEASON_ID===season);return `<span>${row?fmt(row.PTS):"—"}</span>`;}).join("")}</div>`).join("");
    const currentRows=body?body.replaceAll('class="compare-table-row"',`class="compare-table-row" style="grid-template-columns:${grid}"`):'<p class="analytics-note">Current-season stats require every selected player to be active.</p>';
    const posterLink=result.poster_png?`<a class="btn btn-primary" style="margin-top:24px" href="${escapeHTML(result.poster_png)}" target="_blank" rel="noopener">Download comparison poster ↗</a>`:"";
    $("compare-output").innerHTML = `<div class="compare-head" style="grid-template-columns:${grid}"><div class="panel-kicker">${escapeHTML(result.season)}</div>${names.map(name=>`<div>${escapeHTML(name)}</div>`).join("")}</div><div class="viz-grid compare-viz-grid"><div id="compare-skill-chart"></div><div id="compare-career-chart"></div></div><div class="subhead" style="margin-top:22px"><h3>Current season</h3><span>PER GAME</span></div>${currentRows}<div class="subhead" style="margin-top:28px"><h3>Career averages</h3><span>VOLUME-WEIGHTED</span></div>${careerRows}<div class="subhead" style="margin-top:28px"><h3>Season by season</h3><span>POINTS PER GAME</span></div>${seasonRows}<div class="subhead" style="margin-top:28px"><h3>League percentiles</h3><span>CURRENT SEASON</span></div>${pctRows||'<p class="analytics-note">Requires every player active this season.</p>'}<div class="subhead" style="margin-top:28px"><h3>Shot quality</h3><span>EXPECTED VS ACTUAL</span></div>${qualityRows}${posterLink}`;
    mountCompareVisuals(names,result);
  } catch (error) { $("compare-output").innerHTML = `<div class="empty-state" style="min-height:280px"><div><h3>Comparison unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`; }
});
