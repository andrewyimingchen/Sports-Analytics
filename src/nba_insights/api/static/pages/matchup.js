// Matchup lab: game prediction, team comparison, simulation, player points, lineups.
import { $, api, escapeHTML, fmt } from "../core.js";
import { dataTable } from "../render.js";
import { currentMeta, loadMeta, loadTeamOptions } from "../meta.js";
import { initialPage, registerPage, showPage } from "../router.js";
import {
  driverWaterfallPlot,
  matchupRankPlot,
  mountChart,
} from "../visualizations.js";

let teamsLoaded = false;
let sharedMatchupRun = false;
async function loadTeams() {
  if (teamsLoaded) return;
  try {
    await loadMeta();
    const teams = await loadTeamOptions();
    const shared = new URLSearchParams(location.search);
    const shouldRunSharedMatchup=initialPage==="matchup"&&shared.has("home")&&shared.has("away")&&!sharedMatchupRun;
    if(shared.get("season")&&[...$("prediction-season").options].some(option=>option.value===shared.get("season"))){
      $("prediction-season").value=shared.get("season");
    }
    [["home",shared.get("home")||"LAL"],["away",shared.get("away")||"BOS"]].forEach(([id,pick]) => {
      $(id).innerHTML = teams.map(team => `<option value="${escapeHTML(team)}" ${team === pick ? "selected" : ""}>${escapeHTML(team)}</option>`).join("");
    });
    $("points-opponent").innerHTML = teams.map(team => `<option>${escapeHTML(team)}</option>`).join("");
    $("lineup-team").innerHTML = teams.map(team => `<option>${escapeHTML(team)}</option>`).join("");
    await loadLineupRoster();
    teamsLoaded = true;
    if(shouldRunSharedMatchup){
      sharedMatchupRun=true;
      queueMicrotask(()=>$("go").click());
    }
  } catch (error) { $("form-error").textContent = error.message; $("form-error").classList.remove("hidden"); }
}
$("prediction-season").addEventListener("change",event=>{const upcoming=event.target.selectedIndex>0;$("prediction-basis-note").textContent=upcoming?`${event.target.value} is a preseason projection using ${currentMeta().current_season} team form and rosters. It will move to season-to-date inputs once the new season begins.`:"Uses live season-to-date team form, availability assumptions, carried-over Elo, and home court.";});

const comparisonValue=(metric,value)=>{
  if(value==null)return "—";
  const percentage=["win_pct","off_efg","off_tov_pct","off_oreb_pct","off_ft_rate","def_efg","def_tov_pct","def_dreb_pct","def_ft_rate","three_rate"].includes(metric.key);
  return percentage?`${fmt(Number(value)*100,1)}%`:fmt(value,metric.key==="elo"?0:1);
};
function renderTeamComparison(result){
  const output=$("team-comparison-output"),away=result.away,home=result.home;
  const metricRows=(result.metrics||[]).map(metric=>`<div class="team-metric-row" role="row"><span role="cell">${escapeHTML(metric.category)}</span><b role="cell" class="${metric.leader==="first"?'leader':''}">${comparisonValue(metric,metric.first)}${metric.first_rank?` <small>#${escapeHTML(metric.first_rank)}</small>`:''}</b><span role="cell">${escapeHTML(metric.label)}</span><b role="cell" class="${metric.leader==="second"?'leader':''}">${comparisonValue(metric,metric.second)}${metric.second_rank?` <small>#${escapeHTML(metric.second_rank)}</small>`:''}</b></div>`).join("");
  const drivers=(result.drivers||[]).slice(0,8).map(driver=>`<div class="driver-row"><div><b>${escapeHTML(driver.label)}</b><small>Raw home–away difference: ${driver.raw_difference==null?'baseline':fmt(driver.raw_difference,2)}</small></div><span class="${driver.favors===home?'positive':driver.favors===away?'negative-text':''}">${driver.log_odds_contribution>=0?'+':''}${fmt(driver.log_odds_contribution,3)}<br>favors ${escapeHTML(driver.favors)}</span></div>`).join("");
  const rotation=team=>{const profile=result.teams?.[team]||{},players=(profile.rotation||[]).map(player=>`<div class="rotation-player"><span>${escapeHTML(player.PLAYER_NAME)}</span><span>${fmt(player.MIN)} MIN</span><span>${fmt(player.PTS)} PTS</span></div>`).join(""),lineup=profile.top_lineup;return `<article class="rotation-card"><h4>${escapeHTML(team)}</h4><div class="context-grid" style="grid-template-columns:repeat(2,1fr)"><div class="context-tile"><b>${profile.bench_points_per_game==null?'—':fmt(profile.bench_points_per_game)}</b><span>Bench PTS / game</span></div><div class="context-tile"><b>${profile.clutch?`${profile.clutch.net_rating>=0?'+':''}${fmt(profile.clutch.net_rating)}`:'—'}</b><span>Clutch net rating</span></div></div><div style="margin-top:12px">${players||'<p class="analytics-note">Rotation unavailable.</p>'}</div><p class="analytics-note">${lineup?`Top unit: ${escapeHTML(lineup.GROUP_NAME)} · ${fmt(lineup.MIN,0)} minutes · ${Number(lineup.NET_RATING)>=0?'+':''}${fmt(lineup.NET_RATING)} net.`:'Five-player lineup sample unavailable.'}</p></article>`;};
  const h2h=result.head_to_head||{};
  const metricTable=`<div class="metric-board" role="table" aria-label="${escapeHTML(away)} and ${escapeHTML(home)} exact matchup metrics"><div class="team-metric-row header" role="row"><span role="columnheader">Category</span><b role="columnheader">${escapeHTML(away)}</b><span role="columnheader">Metric</span><b role="columnheader">${escapeHTML(home)}</b></div>${metricRows}</div>`;
  const driverTable=drivers?dataTable("Model driver contributions",["Driver","Raw home–away difference","Log-odds contribution","Favors"],(result.drivers||[]).slice(0,8).map(driver=>[driver.label,driver.raw_difference==null?"baseline":fmt(driver.raw_difference,2),`${driver.log_odds_contribution>=0?"+":""}${fmt(driver.log_odds_contribution,3)}`,driver.favors])):"";
  output.innerHTML=`<div class="subhead"><div><div class="panel-kicker">${escapeHTML(result.season)} · data through ${escapeHTML(result.sample.as_of)}</div><h3>${escapeHTML(away)} at ${escapeHTML(home)} · full comparison</h3></div><div class="comparison-actions"><button class="btn" id="comparison-share">Copy share link</button><button class="btn" id="comparison-export">Export JSON</button></div></div><p class="analytics-note">${escapeHTML(result.sample.definition)} · ${escapeHTML(away)} ${escapeHTML(result.sample.games[away])} games · ${escapeHTML(home)} ${escapeHTML(result.sample.games[home])} games.</p><div class="viz-legend"><span><i class="away"></i>${escapeHTML(away)} · circle</span><span><i class="home"></i>${escapeHTML(home)} · square</span></div><div class="viz-grid" style="margin-top:14px"><div id="matchup-rank-chart"></div><div id="matchup-driver-chart"></div></div><div class="rotation-grid">${rotation(away)}${rotation(home)}</div><div class="context-grid"><div class="context-tile"><b>${escapeHTML(h2h.first_wins??0)}–${escapeHTML(h2h.second_wins??0)}</b><span>${escapeHTML(away)}–${escapeHTML(home)} head to head</span></div><div class="context-tile"><b>${h2h.first_average_margin==null?'—':`${Number(h2h.first_average_margin)>=0?'+':''}${fmt(h2h.first_average_margin)}`}</b><span>${escapeHTML(away)} average margin</span></div><div class="context-tile"><b>${fmt(Number(result.home_win_prob)*100,0)}%</b><span>${escapeHTML(home)} model probability</span></div><div class="context-tile"><b>${escapeHTML(result.basis_season)}</b><span>Model data basis</span></div></div><ul class="limitations">${(result.limitations||[]).map(item=>`<li>${escapeHTML(item)}</li>`).join("")}</ul>`;
  mountChart($("matchup-rank-chart"),{
    title:"Same-sample league ranks",
    takeaway:"Connected dots make the category-by-category advantage visible on one comparable rank scale; rank one is best.",
    description:`${result.sample.definition} · ${away} ${result.sample.games[away]} games · ${home} ${result.sample.games[home]} games.`,
    plotFactory:matchupRankPlot(result.metrics||[],away,home),
    tableHTML:metricTable,
    dataLabel:"View exact matchup values and ranks",
  });
  mountChart($("matchup-driver-chart"),{
    title:"Why the prediction moved",
    takeaway:`Steps to the right (square ends) move the forecast toward ${home}; steps to the left (round ends) move it toward ${away}.`,
    description:"Ordered local contributions accumulate from the baseline. They explain this prediction, not general team quality.",
    plotFactory:driverWaterfallPlot(result.drivers||[],away,home),
    tableHTML:driverTable,
    dataLabel:"View exact driver contributions",
  });
  $("comparison-share").addEventListener("click",async event=>{const url=new URL(result.share_url,location.origin).href;try{await navigator.clipboard.writeText(url);event.currentTarget.textContent="Link copied";}catch{prompt("Copy this matchup link",url);}});
  $("comparison-export").addEventListener("click",()=>{const blob=new Blob([JSON.stringify(result,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=result.export_filename;link.click();URL.revokeObjectURL(url);});
}
$("go").addEventListener("click", async () => {
  const home = $("home").value, away = $("away").value, button = $("go"), errorEl = $("form-error");
  errorEl.classList.add("hidden");
  if (home === away) { errorEl.textContent = "Choose two different teams."; errorEl.classList.remove("hidden"); return; }
  button.disabled = true; button.textContent = "Running model…";
  $("prediction").innerHTML = '<div class="court-lines"></div><div class="prediction-empty"><div class="loading">CALCULATING MATCHUP FEATURES…</div></div>';
  try {
    const season=$("prediction-season").value;
    const params = new URLSearchParams({home,away,season,home_missing_min:$("home-missing").value||"0",away_missing_min:$("away-missing").value||"0"});
    const [result,comparison] = await Promise.all([api(`/predict/game?${params}`),api(`/teams/compare?${params}`)]);
    const homePct = Math.round(result.home_win_prob * 100), awayPct = 100 - homePct;
    const poster = `/posters/game?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&season=${encodeURIComponent(season)}&format=png`;
    const basis=result.projection_mode==="preseason_carry_forward"?`${result.basis_season} carry-forward`:`${result.season} season to date`;
    $("prediction").innerHTML = `<div class="court-lines"></div><div class="prediction-result"><div style="width:100%"><div class="match-label">${escapeHTML(result.season)} home win probability</div><div class="team-row"><div class="team-name">${escapeHTML(away)}</div><div class="at-mark">@</div><div class="team-name">${escapeHTML(home)}</div></div><div class="probability"><b>${homePct}%</b><span>${escapeHTML(home)} projected win probability</span></div><div class="prob-track"><div class="prob-home" style="width:${homePct}%"></div><div class="prob-away"></div></div><div class="prob-legends"><span>${escapeHTML(home)} ${homePct}%</span><span>${escapeHTML(away)} ${awayPct}%</span></div><p class="analytics-note">Data basis: ${escapeHTML(basis)}</p><a class="btn btn-secondary" style="margin-top:22px" href="${poster}" target="_blank" rel="noopener">Download matchup poster ↗</a></div></div>`;
    renderTeamComparison(comparison);
  } catch (error) {
    $("prediction").innerHTML = `<div class="court-lines"></div><div class="prediction-empty"><div><h3>Model unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`;
    $("team-comparison-output").innerHTML = `<div class="empty-state" style="min-height:220px"><div><h3>Comparison unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`;
  } finally { button.disabled = false; button.textContent = "Run prediction →"; }
});

const histogramHTML = rows => {
  const max = Math.max(1,...(rows||[]).map(row=>Number(row.count)||0));
  return `<div class="histogram">${(rows||[]).map(row=>`<i style="height:${Math.max(2,Number(row.count)/max*100)}%" title="${fmt(row.mid)}: ${escapeHTML(row.count)} sims"></i>`).join("")}</div>`;
};

$("simulate-go").addEventListener("click", async () => {
  const home=$("home").value, away=$("away").value, output=$("simulation-output");
  output.innerHTML='<div class="loading" style="margin-top:18px">RUNNING 10,000 GAMES…</div>';
  try {
    const params=new URLSearchParams({home,away,season:$("prediction-season").value,n_sims:"10000",home_missing_min:$("home-missing").value||"0",away_missing_min:$("away-missing").value||"0"});
    const result=await api(`/predict/simulate?${params}`), summary=result.summary;
    const favorite=Number(summary.median_margin)>=0?home:away;
    output.innerHTML=`<div class="result-card"><strong>${escapeHTML(home)} ${escapeHTML(result.median_score.home)}–${escapeHTML(result.median_score.away)} ${escapeHTML(away)}</strong><p class="analytics-note">${escapeHTML(result.season)} · Median score · ${escapeHTML(home)} wins ${fmt(Number(summary.home_win_prob)*100,0)}% of simulations · outcome model ${fmt(Number(result.outcome_model_home_win_prob)*100,0)}%</p><div class="context-grid" style="grid-template-columns:1fr 1fr"><div class="context-tile"><b>${escapeHTML(favorite)} by ${fmt(Math.abs(summary.median_margin),0)}</b><span>Median margin</span></div><div class="context-tile"><b>${fmt(summary.median_total,0)}</b><span>Median total</span></div><div class="context-tile"><b>${fmt(Number(summary.overtime_prob)*100)}%</b><span>Overtime</span></div><div class="context-tile"><b>${summary.margin_p10>=0?"+":""}${fmt(summary.margin_p10,0)} to ${summary.margin_p90>=0?"+":""}${fmt(summary.margin_p90,0)}</b><span>80% margin range</span></div></div>${histogramHTML(result.margin_histogram)}<p class="analytics-note">Margin distribution: away wins on the left, home wins on the right. Data basis: ${escapeHTML(result.basis_season)}.</p></div>`;
  } catch(error) { output.innerHTML=`<p class="error">${escapeHTML(error.message)}</p>`; }
});

let pointsPick=null, pointsTimer;
$("points-player").addEventListener("input", event => {
  pointsPick=null; clearTimeout(pointsTimer); const q=event.target.value.trim(), results=$("points-player-results");
  if(q.length<3){results.classList.add("hidden");return;}
  pointsTimer=setTimeout(async()=>{try{const players=await api(`/players/search?q=${encodeURIComponent(q)}`);results.innerHTML=players.slice(0,8).map(player=>`<button data-id="${Number(player.id)}" data-name="${escapeHTML(player.full_name)}">${escapeHTML(player.full_name)}<span>SELECT</span></button>`).join("");results.classList.remove("hidden");}catch(error){results.innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}},220);
});
$("points-player-results").addEventListener("click",event=>{const button=event.target.closest("button");if(!button)return;pointsPick=Number(button.dataset.id);$("points-player").value=button.dataset.name;$("points-player-results").classList.add("hidden");});
$("points-go").addEventListener("click",async()=>{const output=$("points-output");if(!pointsPick){output.innerHTML='<p class="error">Choose a player from search results.</p>';return;}output.innerHTML='<div class="loading" style="margin-top:18px">PROJECTING NEXT GAME…</div>';try{const params=new URLSearchParams({opponent:$("points-opponent").value,home:$("points-venue").value});const result=await api(`/predict/player/${pointsPick}?${params}`);output.innerHTML=`<div class="result-card"><strong>${fmt(result.projected_points)} PTS</strong><p>${escapeHTML(result.player)} vs ${escapeHTML(result.opponent)}</p><p class="analytics-note">80% interval: ${result.interval_80?`${fmt(result.interval_80[0],0)}–${fmt(result.interval_80[1],0)}`:"unavailable"} · last 5: ${fmt(result.last_5)} · last 10: ${fmt(result.last_10)} · ${escapeHTML(result.games_in_sample)} games</p></div>`;}catch(error){output.innerHTML=`<p class="error">${escapeHTML(error.message)}</p>`;}});

const lineupLabels=["Guard 1","Guard 2","Wing 1","Wing 2","Big"];
const lineupSelects=()=>[...document.querySelectorAll(".lineup-player")];
function syncLineupChoices(){const selected=lineupSelects().map(select=>select.value).filter(Boolean);lineupSelects().forEach(select=>[...select.options].forEach(option=>{option.disabled=Boolean(option.value&&option.value!==select.value&&selected.includes(option.value));}));}
async function loadLineupRoster(){const team=$("lineup-team").value;if(!team)return;$("lineup-slots").innerHTML='<div class="loading">LOADING ROSTER…</div>';try{const result=await api(`/teams/${encodeURIComponent(team)}/profile`),roster=(result.roster||[]).filter(player=>player.PLAYER_ID!=null);$("lineup-slots").innerHTML=lineupLabels.map((label,index)=>`<div class="lineup-slot"><label for="lineup-player-${index}">${label}</label><div class="select-wrap"><select class="lineup-player" id="lineup-player-${index}"><option value="">Choose player</option>${roster.map((player,playerIndex)=>`<option value="${Number(player.PLAYER_ID)}" ${playerIndex===index?"selected":""}>${escapeHTML(player.PLAYER_NAME)}</option>`).join("")}</select></div></div>`).join("");syncLineupChoices();$("lineup-output").innerHTML="";}catch(error){$("lineup-slots").innerHTML='<p class="error">Roster unavailable.</p>';$("lineup-output").innerHTML=`<p class="error">${escapeHTML(error.message)}</p>`;}}
$("lineup-team").addEventListener("change",loadLineupRoster);
$("lineup-slots").addEventListener("change",event=>{if(event.target.matches(".lineup-player"))syncLineupChoices();});
$("lineup-go").addEventListener("click",async()=>{const ids=lineupSelects().map(select=>select.value).filter(Boolean),output=$("lineup-output");if(ids.length!==5||new Set(ids).size!==5){output.innerHTML='<p class="error">Choose five different players, one in each slot.</p>';return;}output.innerHTML='<div class="loading" style="margin-top:18px">ESTIMATING FIVE-MAN UNIT…</div>';try{const query=ids.map(id=>`player_ids=${encodeURIComponent(id)}`).join("&");const result=await api(`/predict/lineup?team=${encodeURIComponent($("lineup-team").value)}&${query}`);output.innerHTML=`<div class="result-card"><strong>${Number(result.estimated_net_rating)>=0?"+":""}${fmt(result.estimated_net_rating)} NET</strong><p>${result.players.map(escapeHTML).join(" · ")}</p><p class="analytics-note">${fmt(Number(result.win_probability_vs_average)*100,0)}% win probability vs average · ${fmt(result.minutes_together,0)} minutes together · ${escapeHTML(result.source.replaceAll("_"," "))}</p></div>`;}catch(error){output.innerHTML=`<p class="error">${escapeHTML(error.message)}</p>`;}});


export async function openMatchup(away,home){
  await loadTeams();
  showPage("matchup");
  $("away").value=away;
  $("home").value=home;
}

registerPage("matchup", loadTeams);
