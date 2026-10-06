// League pulse: leaders, team form, landscape, next games.
import { $, api, escapeHTML, fmt } from "../core.js";
import { loadMeta } from "../meta.js";
import { registerPage, registerRetry } from "../router.js";
import { openPlayerProfile } from "./profile.js";
import { openTeamRoom } from "./teams.js";
import { openMatchup } from "./matchup.js";

let pulseLoaded = false;
let pulseData = null;
const leaderLabels = {points:"Points",assists:"Assists",rebounds:"Rebounds",threes:"Threes",net_rating:"Net rating",clutch_net:"Clutch net"};
const leaderStats = {points:"PTS",assists:"AST",rebounds:"REB",threes:"FG3M",net_rating:"NET_RATING",clutch_net:"CLUTCH_NET_RATING"};
async function loadPulse() {
  if (pulseLoaded) return;
  try {
    await loadMeta();
    pulseData = await api(`/league/pulse?season=${encodeURIComponent($("pulse-season").value)}`);
    pulseLoaded = true;
    const cards = Object.entries(pulseData.leaders).map(([key,rows]) => {
      const stat = leaderStats[key];
      return `<article class="leader-card"><div class="leader-title">${leaderLabels[key] || escapeHTML(key)}<span>TOP 5</span></div>${rows.map((row,index) => {
        const name=`${escapeHTML(row.PLAYER_NAME)}<small>${escapeHTML(row.TEAM_ABBREVIATION || "—")}</small>`;
        const player=row.PLAYER_ID!=null?`<button class="leader-name entity-link" data-player-id="${Number(row.PLAYER_ID)}" data-player-name="${escapeHTML(row.PLAYER_NAME)}">${name}</button>`:`<span class="leader-name">${name}</span>`;
        return `<div class="leader-row"><span class="leader-rank">0${index+1}</span>${player}<b class="leader-value">${stat.includes("RATING") && Number(row[stat]) > 0 ? "+" : ""}${fmt(row[stat])}</b></div>`;
      }).join("")}</article>`;
    }).join("");
    const teams = pulseData.team_form || [];
    const maxNet = Math.max(1, ...teams.map(team => Math.abs(Number(team.form_net) || 0)));
    const formRows = teams.map(team => {
      const net = Number(team.form_net) || 0, width = Math.max(3, Math.abs(net) / maxNet * 100);
      return `<div class="team-form-row"><button class="entity-link" data-team="${escapeHTML(team.team)}"><b>${escapeHTML(team.team)}</b></button><div class="net-bar"><i class="${net < 0 ? "negative" : ""}" style="width:${width}%"></i></div><span>${net >= 0 ? "+" : ""}${fmt(net)}</span><span>${fmt((Number(team.form_win_pct)||0)*100,0)}%</span><span>${team.elo==null?"—":fmt(team.elo,0)}</span></div>`;
    }).join("");
    const landscapeTeams=teams.filter(team=>team.form_ortg!=null&&team.form_drtg!=null),minO=Math.min(...landscapeTeams.map(team=>Number(team.form_ortg))),maxO=Math.max(...landscapeTeams.map(team=>Number(team.form_ortg))),minD=Math.min(...landscapeTeams.map(team=>Number(team.form_drtg))),maxD=Math.max(...landscapeTeams.map(team=>Number(team.form_drtg)));
    const landscape=landscapeTeams.length?`<section class="form-board"><div class="form-board-head"><h3>League landscape</h3><span>OFFENSE → · DEFENSE BETTER ↑</span></div><svg class="shot-court" style="min-height:420px" viewBox="0 0 700 400" role="img" aria-label="Team offense versus defense"><line x1="350" y1="20" x2="350" y2="375" stroke="#343c46"/><line x1="25" y1="200" x2="675" y2="200" stroke="#343c46"/>${landscapeTeams.map(team=>{const x=40+(Number(team.form_ortg)-minO)/(maxO-minO||1)*620,y=30+(Number(team.form_drtg)-minD)/(maxD-minD||1)*340;return `<g><circle cx="${x}" cy="${y}" r="11" fill="#ff5c35"/><text x="${x}" y="${y-15}" text-anchor="middle" fill="#f4f1ea" font-size="10">${escapeHTML(team.team)}</text></g>`;}).join("")}</svg></section>`:"";
    const slate=(pulseData.next_slate||[]).length?`<section class="form-board"><div class="form-board-head"><h3>Next games</h3><span>OPEN A GAME TO COMPARE THE TEAMS</span></div><div class="leader-grid">${pulseData.next_slate.map(game=>`<button class="leader-card slate-card" data-away="${escapeHTML(game.away)}" data-home="${escapeHTML(game.home)}"><b class="leader-value">${escapeHTML(game.away)} @ ${escapeHTML(game.home)}</b><p>${escapeHTML(game.home)} ${fmt(Number(game.home_win_prob)*100,0)}% · ${new Date(game.tipoff).toLocaleString()}</p></button>`).join("")}</div></section>`:"";
    const cutoff=teams.map(team=>team.last_game_date).filter(Boolean).sort().at(-1);
    const cutoffLabel=cutoff?new Date(cutoff).toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"}):"date unavailable";
    $("pulse-context").innerHTML=`<span><b>${escapeHTML(pulseData.season)}</b> season</span><span><b>${escapeHTML(pulseData.minimum_games)}</b> games minimum</span><span>Team form through <b>${escapeHTML(cutoffLabel)}</b></span>`;
    $("pulse-content").innerHTML = `${slate}<div class="leader-grid">${cards}</div><section class="form-board"><div class="form-board-head"><h3>Team form index</h3><span>NET · WIN% · ELO</span></div><div class="team-form-list">${formRows}</div></section>${landscape}`;
  } catch (error) { $("pulse-content").innerHTML = `<div class="panel empty-state"><div><h3>League pulse unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="pulse">Retry league data</button></div></div>`; }
}
$("pulse-season").addEventListener("change",()=>{pulseLoaded=false;$("pulse-content").innerHTML='<div class="panel empty-state"><div class="loading">LOADING HISTORICAL PULSE…</div></div>';loadPulse();});

$("pulse-content").addEventListener("click",event=>{
  const player=event.target.closest("[data-player-id]");
  if(player){openPlayerProfile(Number(player.dataset.playerId),player.dataset.playerName);return;}
  const team=event.target.closest("[data-team]");
  if(team){openTeamRoom(team.dataset.team);return;}
  const game=event.target.closest("[data-away][data-home]");
  if(game)openMatchup(game.dataset.away,game.dataset.home);
});

/** Team abbreviations from the loaded pulse, if any. */
export const pulseTeams = () => pulseData?.team_form?.map(row => row.team);

registerPage("pulse", loadPulse);
registerRetry("pulse", () => { pulseLoaded = false; loadPulse(); });
