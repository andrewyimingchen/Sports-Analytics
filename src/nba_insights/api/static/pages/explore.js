// Explore: filterable league table with a two-measure scatter.
import { $, api, escapeHTML, fmt } from "../core.js";
import { loadMeta } from "../meta.js";
import { registerPage, registerRetry, showPage } from "../router.js";
import { loadProfile } from "./profile.js";
import {
  exploreScatterPlot,
  mountChart,
} from "../visualizations.js";

let exploreLoaded = false;
let exploreData = null;
async function loadExplore() {
  if (!exploreLoaded) {
    try {
      await loadMeta();
      const teams = await api("/teams");
      $("explore-team").innerHTML = '<option value="">All teams</option>' + teams.map(team => `<option>${escapeHTML(team)}</option>`).join("");
    } catch { /* the team filter falls back to All teams */ }
  }
  exploreLoaded = true;
  const params = new URLSearchParams({
    season: $("explore-season").value,
    rate: $("explore-rate").value,
    q: $("explore-query").value.trim(),
    sort: $("explore-sort").value,
    order: "desc",
    min_gp: "10",
  });
  if ($("explore-team").value) params.append("teams", $("explore-team").value);
  $("explore-output").innerHTML = '<div class="empty-state" style="min-height:390px"><div class="loading">FILTERING PLAYER POOL…</div></div>';
  try {
    const result = await api(`/league/explore?${params}`);
    exploreData = result;
    const columns = [["TEAM_ABBREVIATION","TM"],["GP","GP"],["MIN","MIN"],["PTS","PTS"],["REB","REB"],["AST","AST"],["STL","STL"],["BLK","BLK"],["FG3M","3PM"],["NET_RATING","NET"],["DPM","DPM"]];
    const header = `<div class="explore-row header" role="row"><span role="columnheader">Player · ${result.count} results</span>${columns.map(([,label]) => `<span role="columnheader">${label}</span>`).join("")}</div>`;
    const rows = result.players.map(player => `<div class="explore-row" role="row"><span role="cell"><button class="explore-player-link" data-player-id="${Number(player.PLAYER_ID)}" data-player-name="${escapeHTML(player.PLAYER_NAME)}" aria-label="Open ${escapeHTML(player.PLAYER_NAME)} profile">${escapeHTML(player.PLAYER_NAME)}</button></span>${columns.map(([key]) => `<span role="cell">${player[key] == null ? "—" : key === "TEAM_ABBREVIATION" ? escapeHTML(player[key]) : `${["NET_RATING","DPM"].includes(key) && Number(player[key]) > 0 ? "+" : ""}${fmt(player[key], key === "GP" ? 0 : 1)}`}</span>`).join("")}</div>`).join("");
    const labels={MIN:"Minutes",PTS:"Points",REB:"Rebounds",AST:"Assists",STL:"Steals",BLK:"Blocks",FG3M:"Threes made",NET_RATING:"Net rating",DPM:"DARKO DPM"};
    const available=Object.keys(labels).filter(key=>result.players.some(player=>Number.isFinite(Number(player[key]))));
    const yDefault=available.includes($("explore-sort").value)?$("explore-sort").value:(available.includes("PTS")?"PTS":available[0]);
    const xDefault=["DPM","NET_RATING","MIN","AST"].find(key=>available.includes(key)&&key!==yDefault)||available.find(key=>key!==yDefault);
    const options=selected=>available.map(key=>`<option value="${key}" ${key===selected?"selected":""}>${escapeHTML(labels[key])}</option>`).join("");
    const tableHTML=`<div role="table" aria-label="League player statistics">${header}${rows}</div><button class="explore-run" style="margin:16px" id="explore-download">Download CSV ↓</button>`;
    const output=$("explore-output");
    output.className="visual-output";
    output.removeAttribute("role");
    output.removeAttribute("aria-label");
    output.innerHTML=`<div class="viz-control-row"><div class="control"><label for="explore-x">Horizontal measure</label><div class="select-wrap"><select id="explore-x">${options(xDefault)}</select></div></div><div class="control"><label for="explore-y">Vertical measure</label><div class="select-wrap"><select id="explore-y">${options(yDefault)}</select></div></div><div class="viz-legend"><span><i></i>Player</span><span>Dashed lines · league average</span></div></div><div id="explore-chart"></div>`;
    const renderExploreChart=()=>{
      const xKey=$("explore-x").value,yKey=$("explore-y").value;
      mountChart($("explore-chart"),{
        title:`${labels[yKey]} by ${labels[xKey]}`,
        takeaway:`Find players who combine strong ${labels[xKey].toLowerCase()} and ${labels[yKey].toLowerCase()}; the upper-right quadrant is above average on both.`,
        description:`${result.season} · ${result.rate.replaceAll("_"," ")} · minimum 10 games · ${result.count} qualified players. Labels identify the eight highest ${labels[yKey].toLowerCase()} values.`,
        plotFactory:exploreScatterPlot(result.players,xKey,yKey,{x:labels[xKey],y:labels[yKey]}),
        tableHTML,
        dataLabel:`View all ${result.count} players and download CSV`,
      });
    };
    $("explore-x").addEventListener("change",renderExploreChart);
    $("explore-y").addEventListener("change",renderExploreChart);
    renderExploreChart();
  } catch (error) { $("explore-output").innerHTML = `<div class="empty-state" style="min-height:390px"><div><h3>League table unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="explore">Retry league table</button></div></div>`; }
}
$("explore-go").addEventListener("click", loadExplore);
$("explore-output").addEventListener("click", event => {
  if(event.target.closest("#explore-download")){downloadExplore();return;}
  const link = event.target.closest(".explore-player-link");
  if (!link) return;
  const playerId = Number(link.dataset.playerId), playerName = link.dataset.playerName;
  if (!Number.isFinite(playerId) || !playerName) return;
  $("search").value = playerName;
  $("results").innerHTML = "";
  showPage("players");
  loadProfile(playerId, playerName);
});
function downloadExplore(){if(!exploreData?.players?.length)return;const columns=Object.keys(exploreData.players[0]),quote=value=>`"${String(value??"").replaceAll('"','""')}"`,csv=[columns.join(","),...exploreData.players.map(row=>columns.map(column=>quote(row[column])).join(","))].join("\n"),link=document.createElement("a");link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));link.download=`nba_${exploreData.season}_${exploreData.rate}.csv`;link.click();URL.revokeObjectURL(link.href);}

registerPage("explore", loadExplore);
registerRetry("explore", loadExplore);
