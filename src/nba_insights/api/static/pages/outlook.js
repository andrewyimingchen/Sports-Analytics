// Season outlook: projected standings, odds, player projections, roster scenarios.
import { $, api, escapeHTML, fmt } from "../core.js";
import { dataTable } from "../render.js";
import { currentMeta, loadMeta, loadTeamOptions } from "../meta.js";
import { registerPage, registerRetry } from "../router.js";
import {
  mountChart,
  playerIntervalPlot,
  probabilityPlot,
  winIntervalPlot,
} from "../visualizations.js";

let forecastLoadedFor = null;
let scenarioRoster = [];
let scenarioChanges = [];
async function loadSeasonForecast(force=false){
  const season=$("outlook-season").value,output=$("season-forecast");
  if(!season||(!force&&forecastLoadedFor===season))return;
  output.innerHTML=`<div class="empty-state" style="min-height:260px"><div class="loading">SIMULATING ${escapeHTML(season)} SEASON…</div></div>`;
  try{
    const result=await api(`/predict/season?season=${encodeURIComponent(season)}&n_sims=5000`),playerForecast=result.roster_inputs?await api(`/predict/players?season=${encodeURIComponent(season)}&limit=40`):null,pct=value=>`${fmt(Number(value)*100,1)}%`;
    const table=conference=>`<section><div class="subhead"><h3>${conference}ern Conference</h3><span>PROJECTED ORDER</span></div><div class="forecast-table" role="table" aria-label="${conference}ern Conference forecast"><div class="forecast-row header" role="row"><span role="columnheader">Seed</span><span role="columnheader">Team</span><span role="columnheader">Wins P10 / 50 / 90</span><span role="columnheader">Roster Δ</span><span role="columnheader">Playoffs</span><span role="columnheader">NBA title</span><span role="columnheader">NBA Cup</span></div>${(result.conferences[conference]||[]).map(team=>`<div class="forecast-row" role="row" title="Key drivers: ${(team.KEY_DRIVERS||[]).map(escapeHTML).join(', ')||'current team form'}"><span role="cell">${fmt(team.PROJECTED_SEED,1)}</span><b role="cell">${escapeHTML(team.TEAM)}</b><span role="cell">${fmt(team.PESSIMISTIC_WINS??team.PROJECTED_WINS,0)} / ${fmt(team.MEDIAN_WINS??team.PROJECTED_WINS,0)} / ${fmt(team.OPTIMISTIC_WINS??team.PROJECTED_WINS,0)}</span><span role="cell" class="${Number(team.NET_ADJUSTMENT)>=0?'positive':'negative-text'}">${team.NET_ADJUSTMENT==null?'—':`${Number(team.NET_ADJUSTMENT)>=0?'+':''}${fmt(team.NET_ADJUSTMENT,1)}`}</span><span role="cell">${pct(team.PLAYOFF_PROB)}</span><span role="cell">${pct(team.CHAMP_PROB)}</span><span role="cell">${pct(team.CUP_PROB)}</span></div>`).join("")}</div></section>`;
    const cupGroups=Object.entries(result.nba_cup?.groups||{}).map(([group,teams])=>`<section><div class="subhead"><h3>${escapeHTML(group)}</h3><span>OFFICIAL DRAW</span></div><div class="forecast-table"><div class="cup-row header"><span>Rank</span><span>Team</span><span>Group</span><span>Wild card</span><span>Knockout</span><span>Final</span><span>Champion</span></div>${teams.map(team=>`<div class="cup-row"><span>${fmt(team.CUP_PROJECTED_GROUP_RANK,1)}</span><b>${escapeHTML(team.TEAM)}</b><span>${pct(team.CUP_GROUP_WIN_PROB)}</span><span>${pct(team.CUP_WILD_CARD_PROB)}</span><span>${pct(team.CUP_KNOCKOUT_PROB)}</span><span>${pct(team.CUP_FINAL_PROB)}</span><span>${pct(team.CUP_PROB)}</span></div>`).join("")}</div></section>`).join("");
    const allTeams=[...(result.conferences.East||[]),...(result.conferences.West||[])],movers=allTeams.filter(team=>team.NET_ADJUSTMENT!=null).sort((a,b)=>Math.abs(Number(b.NET_ADJUSTMENT))-Math.abs(Number(a.NET_ADJUSTMENT))).slice(0,8);
    const cupSection=cupGroups?`<section style="margin-top:28px"><div class="subhead"><div><div class="panel-kicker">Official 2026 NBA Cup</div><h3>Group and knockout forecast</h3></div><span>${result.nba_cup.schedule_complete?"FULL SCHEDULE LOADED":"GROUP SCHEDULE PENDING"}</span></div><div id="outlook-cup-chart"></div><p class="analytics-note">${escapeHTML(result.nba_cup.assumption)} <a href="${escapeHTML(result.nba_cup.source_url)}" target="_blank" rel="noopener">Official groups ↗</a> · source ${escapeHTML(result.nba_cup.source_date)}</p></section>`:"";
    const rosterSection=result.roster_inputs?`<section style="margin-top:28px"><div class="subhead"><div><div class="panel-kicker">${escapeHTML(result.roster_inputs.version)} · generated ${escapeHTML(result.roster_inputs.generated_on)}</div><h3>Roster adjustments driving the table</h3></div><a class="btn" href="/predict/season/roster-inputs?season=${encodeURIComponent(result.season)}" target="_blank" rel="noopener">Audit all inputs ↗</a></div><div class="leader-grid">${movers.map(team=>`<article class="leader-card" style="padding:18px"><div class="leader-title">${escapeHTML(team.TEAM)}<span class="${Number(team.NET_ADJUSTMENT)>=0?'positive':'negative-text'}">${Number(team.NET_ADJUSTMENT)>=0?'+':''}${fmt(team.NET_ADJUSTMENT,1)} NET</span></div><p class="analytics-note">${team.ADDITIONS?.length?`In: ${team.ADDITIONS.map(escapeHTML).join(', ')}. `:''}${team.DEPARTURES?.length?`Out: ${team.DEPARTURES.map(escapeHTML).join(', ')}. `:''}Returning minutes ${fmt(Number(team.RETURNING_MIN_SHARE)*100,0)}% · history coverage ${fmt(Number(team.ROSTER_COVERAGE)*100,0)}%.</p></article>`).join('')}</div><p class="analytics-note">${escapeHTML(result.roster_inputs.method)} ${escapeHTML(result.roster_inputs.limitations)}</p></section>`:'';
    const playerRows=(playerForecast?.players||[]).map(player=>`<div class="player-forecast-row" role="row"><b role="cell">${escapeHTML(player.PLAYER_NAME)}<small style="display:block;color:var(--muted-2)">${escapeHTML(player.TRAJECTORY)} · comps ${player.COMPARABLES.map(escapeHTML).join(', ')}</small></b><span role="cell">${escapeHTML(player.TEAM)}</span><span role="cell">${fmt(player.PROJECTED_MIN,1)}</span><span role="cell">${fmt(player.PTS_LOW,1)}–${fmt(player.PROJECTED_PTS,1)}–${fmt(player.PTS_HIGH,1)}</span><span role="cell">${fmt(player.PROJECTED_REB,1)}</span><span role="cell">${fmt(player.PROJECTED_AST,1)}</span><span role="cell">${fmt(Number(player.PROJECTED_FG_PCT)*100,1)}%</span><span role="cell">${pct(player.ALL_STAR_PROB)}</span><span role="cell">${pct(player.MVP_PROB)}</span></div>`).join('');
    const playerTable=playerForecast?`<div class="forecast-table" role="table" aria-label="Player forecast data"><div class="player-forecast-row header" role="row"><span role="columnheader">Player</span><span role="columnheader">Team</span><span role="columnheader">MIN</span><span role="columnheader">PTS low / mid / high</span><span role="columnheader">REB</span><span role="columnheader">AST</span><span role="columnheader">FG%</span><span role="columnheader">All-Star</span><span role="columnheader">MVP</span></div>${playerRows}</div>`:"";
    const playerSection=playerForecast?`<section style="margin-top:28px"><div class="subhead"><div><div class="panel-kicker">${escapeHTML(playerForecast.version)} · ${escapeHTML(playerForecast.count)} projected players</div><h3>Player projections and awards outlook</h3></div><a class="btn" href="/predict/players?season=${encodeURIComponent(result.season)}&limit=500" target="_blank" rel="noopener">Audit full API table ↗</a></div><div id="outlook-player-chart"></div><p class="analytics-note">${escapeHTML(playerForecast.assumptions)} ${escapeHTML(playerForecast.intervals)} Holdout: ${playerForecast.holdout?.metrics?.players||'—'} stable returners, PTS MAE ${fmt(playerForecast.holdout?.metrics?.pts_mae,2)}, interval coverage ${fmt(Number(playerForecast.holdout?.metrics?.pts_interval_coverage)*100,1)}%. ${escapeHTML(playerForecast.awards_method)}</p></section>`:'';
    $("outlook-context").innerHTML=`<span>Projection <b>${escapeHTML(result.season)}</b></span><span>Data basis <b>${escapeHTML(result.basis_season)}</b></span><span>Mode <b>${escapeHTML(result.projection_mode?.replaceAll("_"," ")||"season forecast")}</b></span>`;
    output.innerHTML=`<div class="subhead"><div><div class="panel-kicker">${escapeHTML(result.season)} league forecast</div><h3>East, West, playoffs and trophies</h3></div><span>${Number(result.n_sims).toLocaleString()} SIMULATIONS</span></div><div class="forecast-summary"><div class="context-tile"><b>${escapeHTML(result.favorites.championship.team)} ${pct(result.favorites.championship.probability)}</b><span>NBA title favorite</span></div><div class="context-tile"><b>${escapeHTML(result.favorites.nba_cup.team)} ${pct(result.favorites.nba_cup.probability)}</b><span>NBA Cup favorite</span></div><div class="context-tile"><b>${escapeHTML(result.basis_season)}</b><span>Data basis</span></div></div><div class="viz-grid"><div id="outlook-east-chart"></div><div id="outlook-west-chart"></div><div id="outlook-playoff-chart"></div><div id="outlook-title-chart"></div></div><p class="analytics-note">Win ranges show pessimistic / median / optimistic outcomes (10th / 50th / 90th percentiles). ${escapeHTML(result.methodology)}</p>${rosterSection}${playerSection}${cupSection}`;
    ["East","West"].forEach(conference=>mountChart($(`outlook-${conference.toLowerCase()}-chart`),{
      title:`${conference} projected wins`,
      takeaway:`The range shows season uncertainty; teams are ordered by median wins rather than a single deterministic total.`,
      description:`${Number(result.n_sims).toLocaleString()} simulations · ${result.basis_season} data basis.`,
      plotFactory:winIntervalPlot(result.conferences[conference]||[],conference),
      tableHTML:table(conference),
      dataLabel:`View exact ${conference} forecast`,
    }));
const probabilityTable=(key,label)=>dataTable(`${label} probability by team`,["Team","Conference",`${label} probability`],[...allTeams].sort((a,b)=>Number(b[key])-Number(a[key])).map(team=>[team.TEAM,team.CONFERENCE||(result.conferences.East?.includes(team)?"East":"West"),pct(team[key])]));
    mountChart($("outlook-playoff-chart"),{
      title:"Playoff probability",
      takeaway:"The 50% guide separates likely qualifiers from teams whose postseason case remains fragile.",
      description:`All teams · ${Number(result.n_sims).toLocaleString()} simulations.`,
      plotFactory:probabilityPlot(allTeams,"Playoff","PLAYOFF_PROB"),
      tableHTML:probabilityTable("PLAYOFF_PROB","Playoff"),
      dataLabel:"View every team's playoff probability",
    });
    mountChart($("outlook-title-chart"),{
      title:"Championship probability",
      takeaway:`${result.favorites.championship.team} leads the title field, but the full distribution shows how concentrated that edge is.`,
      description:`Model probability, not betting odds · ${result.basis_season} basis.`,
      plotFactory:probabilityPlot(allTeams,"NBA title","CHAMP_PROB","#ff5c35"),
      tableHTML:probabilityTable("CHAMP_PROB","Title"),
      dataLabel:"View every team's title probability",
    });
    if(playerForecast)mountChart($("outlook-player-chart"),{
      title:"Top projected scorers",
      takeaway:"Median scoring projections are shown with their low-to-high uncertainty intervals.",
      description:`Top 20 by projected points · ${playerForecast.assumptions}`,
      plotFactory:playerIntervalPlot(playerForecast.players||[]),
      tableHTML:playerTable,
      dataLabel:`View all ${playerForecast.count} player forecasts`,
    });
    if(cupGroups)mountChart($("outlook-cup-chart"),{
      title:"NBA Cup championship probability",
      takeaway:`${result.favorites.nba_cup.team} has the strongest modeled Cup path; direct labels show the size of the edge.`,
      description:`${result.nba_cup.assumption} Source ${result.nba_cup.source_date}.`,
      plotFactory:probabilityPlot(allTeams,"NBA Cup","CUP_PROB","#c7ff4a"),
      tableHTML:Object.entries(result.nba_cup?.groups||{}).map(([group,teams])=>dataTable(`${group} · official draw`,["Team","Rank","Group","Wild card","Knockout","Final","Champion"],teams.map(team=>[team.TEAM,fmt(team.CUP_PROJECTED_GROUP_RANK,1),pct(team.CUP_GROUP_WIN_PROB),pct(team.CUP_WILD_CARD_PROB),pct(team.CUP_KNOCKOUT_PROB),pct(team.CUP_FINAL_PROB),pct(team.CUP_PROB)]))).join(""),
      dataLabel:"View group and knockout probabilities",
    });
    forecastLoadedFor=season;
  }catch(error){output.innerHTML=`<div class="empty-state" style="min-height:260px"><div><h3>Season forecast unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="outlook">Retry projection</button></div></div>`;}
}

let outlookLoaded = false;
async function loadOutlook(){
  try{
    await loadMeta();
    if(!outlookLoaded){
      const teams=await loadTeamOptions();
      $("scenario-team").innerHTML=teams.map(team=>`<option>${escapeHTML(team)}</option>`).join("");
      $("scenario-destination").innerHTML='<option value="">Keep current team</option><option value="__REMOVE__">Remove from roster</option>'+teams.map(team=>`<option>${escapeHTML(team)}</option>`).join("");
      outlookLoaded=true;
    }
    await loadScenarioRoster(true);
    await loadSeasonForecast();
  }catch(error){
    $("season-forecast").innerHTML=`<div class="empty-state" style="min-height:260px"><div><h3>Season outlook unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`;
  }
}
$("outlook-season").addEventListener("change",()=>{loadScenarioRoster(true);loadSeasonForecast(true);});

function syncScenarioPlayers(){
  const team=$("scenario-team").value,players=scenarioRoster.filter(player=>player.TEAM===team);
  $("scenario-player").innerHTML=players.map(player=>`<option value="${escapeHTML(player.PLAYER_NAME)}">${escapeHTML(player.PLAYER_NAME)} · ${fmt(player.PROJECTED_MIN)} min</option>`).join("")||'<option value="">No roster inputs</option>';
  const selected=players[0];$("scenario-minutes").placeholder=selected?fmt(selected.PROJECTED_MIN):"Model default";
}
async function loadScenarioRoster(reset=false){
  const season=$("outlook-season").value;if(!season)return;
  if(reset){scenarioChanges=[];renderScenarioPending();$("scenario-output").innerHTML="";}
  if(currentMeta()&&season===currentMeta().current_season){scenarioRoster=[];syncScenarioPlayers();$("scenario-output").innerHTML='<p class="analytics-note">Scenario Lab uses the next-season roster forecast. Select the preseason projection above.</p>';return;}
  try{const result=await api(`/predict/season/roster-inputs?season=${encodeURIComponent(season)}`);scenarioRoster=result.players||[];syncScenarioPlayers();}
  catch(error){scenarioRoster=[];syncScenarioPlayers();$("scenario-output").innerHTML=`<p class="error">${escapeHTML(error.message)}</p>`;}
}
function renderScenarioPending(){
  const pending=$("scenario-pending");
  pending.innerHTML=scenarioChanges.length?scenarioChanges.map((change,index)=>`<div class="scenario-change"><span><b>${escapeHTML(change.player)}</b> · ${change.remove?'remove from roster':change.new_team?`to ${escapeHTML(change.new_team)}`:'same team'}${change.projected_minutes!=null?` · ${fmt(change.projected_minutes)} min/game`:''}${change.games_missed!=null?` · ${escapeHTML(change.games_missed)} games missed`:''}</span><button data-remove-scenario="${index}" aria-label="Remove change">Remove</button></div>`).join(""):'<p class="analytics-note">No changes yet. The published forecast remains the baseline above.</p>';
  $("scenario-run").disabled=!scenarioChanges.length;$("scenario-reset").disabled=!scenarioChanges.length;
}
$("scenario-team").addEventListener("change",syncScenarioPlayers);
$("scenario-player").addEventListener("change",()=>{const player=scenarioRoster.find(row=>row.PLAYER_NAME===$("scenario-player").value);$("scenario-minutes").placeholder=player?fmt(player.PROJECTED_MIN):"Model default";});
$("scenario-add").addEventListener("click",()=>{
  const player=$("scenario-player").value,destination=$("scenario-destination").value,minutes=$("scenario-minutes").value,missed=$("scenario-missed").value;
  if(!player){$("scenario-output").innerHTML='<p class="error">Choose a player.</p>';return;}
  if(scenarioChanges.some(change=>change.player===player)){$("scenario-output").innerHTML='<p class="error">Each player can appear only once. Remove the existing change first.</p>';return;}
  if(!destination&&minutes===""&&missed===""){$("scenario-output").innerHTML='<p class="error">Change minutes, games missed, or roster membership.</p>';return;}
  const change={player};if(destination==="__REMOVE__")change.remove=true;else if(destination)change.new_team=destination;if(minutes!=="")change.projected_minutes=Number(minutes);if(missed!=="")change.games_missed=Number(missed);
  scenarioChanges.push(change);$("scenario-minutes").value="";$("scenario-missed").value="";$("scenario-destination").value="";$("scenario-output").innerHTML="";renderScenarioPending();
});
$("scenario-pending").addEventListener("click",event=>{const button=event.target.closest("[data-remove-scenario]");if(button){scenarioChanges.splice(Number(button.dataset.removeScenario),1);renderScenarioPending();}});
$("scenario-reset").addEventListener("click",()=>{scenarioChanges=[];renderScenarioPending();$("scenario-output").innerHTML='<p class="analytics-note">Reset complete. The immutable published baseline is unchanged.</p>';});
$("scenario-run").addEventListener("click",async()=>{
  const output=$("scenario-output"),button=$("scenario-run");button.disabled=true;output.innerHTML='<div class="loading" style="margin-top:18px">RUNNING PAIRED BASELINE + SCENARIO SIMULATIONS…</div>';
  try{
    const result=await api("/predict/season/scenario",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({season:$("outlook-season").value,n_sims:2000,changes:scenarioChanges})});
    const labels={projected_wins:"Projected wins",projected_seed:"Average seed",playoff_probability:"Playoffs",championship_probability:"NBA title",cup_probability:"NBA Cup"},percentage=new Set(["playoff_probability","championship_probability","cup_probability"]);
    const cards=(result.outcomes||[]).map(team=>`<article class="scenario-outcome"><h4>${escapeHTML(team.team)}</h4><div class="scenario-delta-row header"><span>Metric</span><span>Before</span><span>After</span><span>Change</span></div>${Object.keys(labels).map(key=>{const scale=percentage.has(key)?100:1,suffix=percentage.has(key)?'%':'';return `<div class="scenario-delta-row"><span>${labels[key]}</span><span>${fmt(Number(team.before[key])*scale,percentage.has(key)?1:2)}${suffix}</span><span>${fmt(Number(team.after[key])*scale,percentage.has(key)?1:2)}${suffix}</span><b class="${Number(team.change[key])>=0?'positive':'negative-text'}">${Number(team.change[key])>=0?'+':''}${fmt(Number(team.change[key])*scale,percentage.has(key)?1:2)}${suffix}</b></div>`;}).join('')}<p class="analytics-note">Strength adjustment ${team.strength.before_net_adjustment>=0?'+':''}${fmt(team.strength.before_net_adjustment)} → ${team.strength.after_net_adjustment>=0?'+':''}${fmt(team.strength.after_net_adjustment)} · drivers: ${team.strength.causal_players.map(escapeHTML).join(', ')}</p></article>`).join('');
    const salary=(result.salary_validation||[]).map(row=>`<div class="scenario-change"><span><b>${escapeHTML(row.team)} · ${escapeHTML(row.status.toUpperCase())}</b><br>${escapeHTML(row.detail)} Incoming $${fmt(Number(row.incoming_salary)/1e6,1)}M · outgoing $${fmt(Number(row.outgoing_salary)/1e6,1)}M.</span></div>`).join('');
    output.innerHTML=`<div class="subhead" style="margin-top:22px"><div><div class="panel-kicker">${escapeHTML(result.scenario_id)} · ${Number(result.n_sims).toLocaleString()} paired simulations</div><h3>Before vs after</h3></div><span>BASELINE IMMUTABLE</span></div><div class="scenario-outcomes">${cards}</div><div class="subhead" style="margin-top:22px"><h3>Salary screen</h3><span>ADVISORY · NOT FULL CBA VALIDATION</span></div>${salary}<p class="analytics-note">${escapeHTML(result.methodology)} ${escapeHTML(result.salary_method)}</p>`;
  }catch(error){output.innerHTML=`<p class="error">${escapeHTML(error.message)}</p>`;}finally{button.disabled=false;}
});

registerPage("outlook", loadOutlook);
registerRetry("outlook", () => { forecastLoadedFor = null; loadSeasonForecast(true); });
