// Team Room: identity, efficiency, four factors, roster, lineups, money.
import { $, api, escapeHTML, fmt, money } from "../core.js";
import { dataTable } from "../render.js";
import { loadTeamOptions } from "../meta.js";
import { registerPage, registerRetry, showPage } from "../router.js";
import { openPlayerProfile } from "./profile.js";
import { pulseTeams } from "./pulse.js";
import {
  fourFactorBulletPlot,
  mountChart,
  onOffSwingPlot,
  teamQuadrantPlot,
} from "../visualizations.js";

let teamPickerLoaded = false;
async function loadTeamPicker() {
  if (teamPickerLoaded) return;
  try {
    const teams = pulseTeams() || await loadTeamOptions();
    $("team-pick").innerHTML = '<option value="">Select a team</option>' + teams.map(team => `<option value="${escapeHTML(team)}">${escapeHTML(team)}</option>`).join("");
    teamPickerLoaded = true;
  } catch (error) { $("roster-panel").innerHTML = `<div class="error">${escapeHTML(error.message)}</div>`; }
}
$("team-pick").addEventListener("change", async event => {
  const team = event.target.value;
  if (!team) return;
  $("roster-panel").innerHTML = '<div class="empty-state" style="min-height:330px"><div class="loading">OPENING TEAM ROOM…</div></div>';
  try {
    const result = await api(`/teams/${encodeURIComponent(team)}/profile`), form = result.form;
    const metrics = [[`${fmt((Number(form.form_win_pct)||0)*100,0)}%`,"Win rate"],[`${Number(form.form_net)>=0?"+":""}${fmt(form.form_net)}`,"Net rating"],[fmt(form.form_ortg),"Off rating"],[fmt(form.form_drtg),"Def rating"]];
    $("team-identity").innerHTML = `<div class="team-code">${escapeHTML(team)}</div>${metrics.map(([value,label]) => `<div class="team-metric"><b>${value}</b><span>${label}</span></div>`).join("")}`;
    const columns = [["MIN","MIN"],["PTS","PTS"],["REB","REB"],["AST","AST"],["NET_RATING","NET"],["DPM","DPM"]];
    const head = `<div class="roster-head" role="row"><span role="columnheader">Player</span>${columns.map(([,label]) => `<span role="columnheader">${label}</span>`).join("")}</div>`;
    const rows = result.roster.map(player => `<div class="roster-row" role="row"><span role="cell"><button class="entity-link" data-player-id="${Number(player.PLAYER_ID)}" data-player-name="${escapeHTML(player.PLAYER_NAME)}"><strong>${escapeHTML(player.PLAYER_NAME)}</strong></button></span>${columns.map(([key]) => `<span role="cell">${player[key] == null ? "—" : `${key === "NET_RATING" && Number(player[key])>0 ? "+" : ""}${fmt(player[key])}`}</span>`).join("")}</div>`).join("");
    const factorOrder = ["off_efg","off_tov_pct","off_oreb_pct","off_ft_rate","def_efg","def_tov_pct","def_dreb_pct","def_ft_rate"];
    const factors = factorOrder.filter(key => result.four_factors?.[key] != null).map(key => `<div class="context-tile"><b>${fmt(Number(result.four_factors[key])*100)}%</b><span>${escapeHTML(result.factor_labels?.[key] || key)} · #${escapeHTML(result.four_factors[`${key}_rank`])}</span></div>`).join("");
    const recent = (result.recent_games || []).map(game => `<div class="team-data-row"><b>${escapeHTML(game.MATCHUP)}</b><span>${escapeHTML(game.GAME_DATE)}</span><span>${escapeHTML(game.WL)}</span><span>${fmt(game.PTS,0)} PTS</span><span>${Number(game.PLUS_MINUS)>=0?"+":""}${fmt(game.PLUS_MINUS,0)}</span><span></span></div>`).join("");
    const lineups = (result.lineups || []).map(lineup => `<div class="team-data-row"><b>${escapeHTML(lineup.GROUP_NAME)}</b><span>${fmt(lineup.MIN,0)} MIN</span><span>${fmt(lineup.GP,0)} GP</span><span>${Number(lineup.NET_RATING)>=0?"+":""}${fmt(lineup.NET_RATING)} NET</span><span>${fmt(lineup.OFF_RATING)} ORTG</span><span>${fmt(lineup.DEF_RATING)} DRTG</span></div>`).join("");
    const impact = (result.on_off || []).map(player => `<div class="team-data-row"><b>${escapeHTML(player.PLAYER_NAME)}</b><span>${fmt(player.MIN_ON,0)} MIN</span><span>${Number(player.NET_ON)>=0?"+":""}${fmt(player.NET_ON)} ON</span><span>${Number(player.NET_OFF)>=0?"+":""}${fmt(player.NET_OFF)} OFF</span><span class="${Number(player.NET_DIFF)>=0?"positive":"negative-text"}">${Number(player.NET_DIFF)>=0?"+":""}${fmt(player.NET_DIFF)} SWING</span><span></span></div>`).join("");
    const standings = ["East","West"].map(conference => {
      const conferenceRows = (result.standings || []).filter(row => row.Conference === conference).sort((a,b)=>Number(a.PlayoffRank)-Number(b.PlayoffRank));
      return `<div><div class="subhead"><h3>${conference}</h3><span>STANDINGS</span></div>${conferenceRows.map(row => `<div class="team-data-row" style="grid-template-columns:30px 1fr 45px 45px 60px 55px"><span>${escapeHTML(row.PlayoffRank)}</span><b>${escapeHTML(row.TeamCity)} ${escapeHTML(row.TeamName)}</b><span>${escapeHTML(row.WINS)}W</span><span>${escapeHTML(row.LOSSES)}L</span><span>${escapeHTML(row.L10)}</span><span>${escapeHTML(row.strCurrentStreak)}</span></div>`).join("")}</div>`;
    }).join("");
    const finances = result.finances ? `<section class="team-section"><div class="subhead"><h3>Payroll & contract book</h3><span>LOCAL-ONLY · ${money(result.finances.payroll)}</span></div><div class="split-table" tabindex="0" role="region" aria-label="Payroll and contract book"><div class="split-row header"><span>Player</span>${result.finances.seasons.map(year=>`<span>${escapeHTML(year)}</span>`).join("")}</div>${result.finances.contracts.map(player=>`<div class="split-row"><b>${escapeHTML(player.PLAYER_NAME)}</b>${result.finances.seasons.map(year=>`<span>${money(player[year])}</span>`).join("")}</div>`).join("")}</div><p class="analytics-note">Current and future commitments from the weekly local salary cache.</p></section>` : "";
    $("roster-panel").innerHTML = `<div class="team-sections">${result.scouting_take?`<div class="scouting-card">${escapeHTML(result.scouting_take)}</div>`:""}<div class="viz-grid"><div id="team-quadrant-chart"></div><div id="team-factor-chart"></div></div><section><div class="subhead"><h3>Roster</h3><span>${result.record.wins}-${result.record.losses} · ${escapeHTML(result.season)}</span></div><div role="table" aria-label="${escapeHTML(team)} roster statistics">${head}${rows}</div></section><section class="team-section"><div class="subhead"><h3>Recent games</h3><span>LAST 10</span></div>${recent||'<p class="analytics-note">Recent games unavailable.</p>'}</section><section class="team-section"><div class="subhead"><h3>Five-man lineups</h3><span>MOST USED</span></div>${lineups||'<p class="analytics-note">Lineup data unavailable.</p>'}</section><section class="team-section"><div class="subhead"><h3>On / off impact</h3><span>100+ MINUTES</span></div>${impact?'<div id="team-onoff-chart"></div>':'<p class="analytics-note">On/off data unavailable.</p>'}</section>${finances}<section class="team-section"><div class="subhead"><h3>Conference standings</h3><span>SEASON TO DATE</span></div><div class="standings-grid">${standings}</div></section></div>`;
    mountTeamVisuals(team,result,factors,impact);
  } catch (error) { $("roster-panel").innerHTML = `<div class="empty-state" style="min-height:330px"><div><h3>Team unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="team">Retry team</button></div></div>`; }
});
function mountTeamVisuals(team, result, factorTiles, impactRows) {
  const league = result.league_form || [];
  const me = league.find(row => row.team === team);
  if (me && league.length > 2) {
    const ortgRank = 1 + league.filter(row => Number(row.form_ortg) > Number(me.form_ortg)).length;
    const drtgRank = 1 + league.filter(row => Number(row.form_drtg) < Number(me.form_drtg)).length;
    mountChart($("team-quadrant-chart"),{
      title:"Where they win",
      takeaway:`${team} ranks #${ortgRank} in offense and #${drtgRank} in defense of ${league.length} teams; up and to the right is better on both ends.`,
      description:`${result.season} · season-to-date form ratings, points per 100 possessions. Grey lines mark league averages.`,
      plotFactory:teamQuadrantPlot(league,team),
      tableHTML:dataTable("League offensive and defensive ratings",["Team","ORTG","DRTG","NET"],[...league].sort((a,b)=>Number(b.form_net)-Number(a.form_net)).map(row=>[row.team,fmt(row.form_ortg),fmt(row.form_drtg),row.form_net==null?"—":`${Number(row.form_net)>=0?"+":""}${fmt(row.form_net)}`])),
      dataLabel:"View all team ratings",
    });
  } else {
    $("team-quadrant-chart").innerHTML = "";
  }
  if (factorTiles) {
    const ranks = Object.keys(result.factor_labels || {}).map(key => [key, Number(result.four_factors?.[`${key}_rank`])]).filter(([,rank]) => Number.isFinite(rank));
    const best = ranks.reduce((top, entry) => entry[1] < top[1] ? entry : top, ranks[0]);
    const worst = ranks.reduce((low, entry) => entry[1] > low[1] ? entry : low, ranks[0]);
    mountChart($("team-factor-chart"),{
      title:"Four factors",
      takeaway:`Best: ${result.factor_labels[best[0]]} (${best[0].startsWith("off")?"offense":"defense"}, #${best[1]}). Weakest: ${result.factor_labels[worst[0]]} (${worst[0].startsWith("off")?"offense":"defense"}, #${worst[1]}).`,
      description:"League rank, 1 is best. Turnover and free-throw rates are ranked in the direction that helps the team. The white tick marks the league median.",
      plotFactory:fourFactorBulletPlot(result.four_factors,result.factor_labels,Math.max(league.length,...ranks.map(([,rank])=>rank))),
      tableHTML:dataTable("Four factors",["Factor","Value","League rank"],Object.keys(result.factor_labels||{}).filter(key=>result.four_factors?.[key]!=null).map(key=>[`${key.startsWith("off")?"Offense":"Defense"} ${result.factor_labels[key]}`,`${fmt(Number(result.four_factors[key])*100)}%`,`#${result.four_factors[`${key}_rank`]}`])),
      dataLabel:"View exact factor values",
    });
  } else {
    $("team-factor-chart").innerHTML = '<div class="data-figure"><div class="figure-heading"><h4>Four factors</h4><p>Four-factor data is unavailable for this team.</p></div></div>';
  }
  if (impactRows && $("team-onoff-chart")) {
    mountChart($("team-onoff-chart"),{
      title:"Who moves the needle",
      takeaway:"Net rating swing between minutes with each player on and off the floor. It reflects lineups and opponents as well as the player.",
      description:`${result.season} · players with 100+ minutes on the floor · points per 100 possessions.`,
      plotFactory:onOffSwingPlot(result.on_off||[]),
      tableHTML:dataTable("On/off net rating by player",["Player","Minutes on","Net on","Net off","Swing"],(result.on_off||[]).map(player=>[player.PLAYER_NAME,fmt(player.MIN_ON,0),`${Number(player.NET_ON)>=0?"+":""}${fmt(player.NET_ON)}`,`${Number(player.NET_OFF)>=0?"+":""}${fmt(player.NET_OFF)}`,`${Number(player.NET_DIFF)>=0?"+":""}${fmt(player.NET_DIFF)}`])),
      dataLabel:"View exact on/off splits",
    });
  }
}
$("roster-panel").addEventListener("click",event=>{
  const player=event.target.closest("[data-player-id]");
  if(player)openPlayerProfile(Number(player.dataset.playerId),player.dataset.playerName);
});


export async function openTeamRoom(team){
  await loadTeamPicker();
  showPage("teams");
  $("team-pick").value=team;
  $("team-pick").dispatchEvent(new Event("change"));
}

registerPage("teams", loadTeamPicker);
registerRetry("team", () => $("team-pick").dispatchEvent(new Event("change")));
