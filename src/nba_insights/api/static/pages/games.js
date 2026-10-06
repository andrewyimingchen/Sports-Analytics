// Game Center: schedule, scores, box scores, and game stories.
import { $, api, escapeHTML, fmt } from "../core.js";
import { dataTable } from "../render.js";
import { loadMeta } from "../meta.js";
import { registerPage, registerRetry } from "../router.js";
import {
  advancedBoxDumbbellPlot,
  gameFlowPlot,
  mountChart,
} from "../visualizations.js";

let gameData = null;
function renderGames(team = "") {
  const games = (gameData?.games || []).filter(game => !team || game.HOME === team || game.AWAY === team);
  const upcoming = games.filter(game => ["Scheduled","Live"].includes(game.STATUS)).slice(0,20);
  const finals = games.filter(game => game.STATUS === "Final").reverse().slice(0,40);
  const section = (title, rows) => rows.length ? `<section class="game-section"><div class="game-section-title">${title} · ${rows.length}</div>${rows.map(game => `<button type="button" class="game-row" data-game-id="${escapeHTML(game.GAME_ID)}"><span>${escapeHTML(game.GAME_DATE)}</span><b>${escapeHTML(game.AWAY)} @ ${escapeHTML(game.HOME)}</b><span>${game.STATUS === "Final" ? `${escapeHTML(game.AWAY_PTS)}–${escapeHTML(game.HOME_PTS)}` : escapeHTML(game.STATUS_TEXT || game.STATUS)}</span><span>${escapeHTML(game.WINNER || "—")}</span><span>${escapeHTML(game.TOP_SCORER || "View details →")}</span></button>`).join("")}</section>` : "";
  $("games-output").innerHTML = section("Upcoming", upcoming) + section("Final scores", finals) || '<div class="panel empty-state"><div><h3>No games found</h3><p>Try a different team filter.</p></div></div>';
}
async function loadGames() {
  if (gameData) return;
  try {
    await loadMeta();
    gameData = await api(`/games?season=${encodeURIComponent($("games-season").value)}`);
    const teams = [...new Set(gameData.games.flatMap(game => [game.HOME, game.AWAY]))].filter(Boolean).sort();
    $("games-team").innerHTML = '<option value="">All teams</option>' + teams.map(team => `<option>${escapeHTML(team)}</option>`).join("");
    renderGames();
  } catch (error) { $("games-output").innerHTML = `<div class="panel empty-state"><div><h3>Game Center unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="games">Retry schedule</button></div></div>`; }
}
$("games-team").addEventListener("change", event => renderGames(event.target.value));
$("games-season").addEventListener("change",()=>{gameData=null;$("box-score-output").innerHTML="";$("games-output").innerHTML='<div class="panel empty-state"><div class="loading">LOADING SEASON…</div></div>';loadGames();});

function shotChartSVG(story) {
  const shots=(story.shots||[]).filter(shot=>shot.XLEGACY!=null&&shot.YLEGACY!=null);
  if(!story.shot_locations_available||!shots.length)return '';
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const marks=shots.map(shot=>{const cx=clamp(350+Number(shot.XLEGACY)*1.12,32,668),cy=clamp(535-Number(shot.YLEGACY),28,535),color=shot.MADE?'#ff5c35':'#6f7681';return `<circle cx="${cx}" cy="${cy}" r="6" fill="${color}" opacity=".9"><title>${escapeHTML(shot.PLAYER||'Unknown')} · ${escapeHTML(shot.SUBTYPE||'shot')} · ${shot.MADE?'made':'missed'}</title></circle>`;}).join('');
  return `<svg class="shot-court" viewBox="0 0 700 560" role="img" aria-label="Game shot chart"><rect x="25" y="20" width="650" height="520" fill="none" stroke="#343c46" stroke-width="2"/><path d="M 145 20 V 210 H 555 V 20 M 245 210 A 105 105 0 0 0 455 210" fill="none" stroke="#343c46" stroke-width="2"/><circle cx="350" cy="65" r="8" fill="none" stroke="#343c46" stroke-width="2"/><path d="M 62 20 V 135 A 330 330 0 0 0 638 135 V 20" fill="none" stroke="#343c46" stroke-width="2"/>${marks}</svg><div class="shot-key"><span><i style="background:#ff5c35"></i>Made</span><span><i style="background:#6f7681"></i>Missed</span></div>`;
}

function renderGameStory(story) {
  if(!story.available)return `<section class="panel panel-pad" style="margin-top:12px"><div class="subhead"><h3>Game story unavailable</h3><span>CACHED DATA</span></div><p class="analytics-note">${escapeHTML(story.reason||'No cached play-by-play is available for this game.')}</p></section>`;
  const turns=(story.turning_points||[]).map(point=>`<div class="game-story-row"><span>Q${escapeHTML(point.PERIOD)} ${escapeHTML(point.CLOCK)}</span><b>${escapeHTML(story.away)} ${escapeHTML(point.AWAY_SCORE)}–${escapeHTML(point.HOME_SCORE)} ${escapeHTML(story.home)}</b><span>${fmt(Number(point.HOME_WIN_PROB)*100,0)}% home win</span><span>±${fmt(Number(point.SWING)*100,0)} pts</span></div>`).join('');
  const advanced=(story.advanced||[]).map(team=>`<div class="advanced-row"><span><b>${escapeHTML(team.TEAM)}</b></span><span>${escapeHTML(team.PTS)}</span><span>${fmt(Number(team.EFG_PCT)*100,1)}%</span><span>${fmt(Number(team.TS_PCT)*100,1)}%</span><span>${fmt(Number(team.TOV_RATE)*100,1)}%</span><span>${fmt(Number(team.FT_RATE)*100,1)}%</span><span>${fmt(team.AST_TOV,2)}</span><span>${escapeHTML(team.OREB)}</span><span>${escapeHTML(team.REB)}</span></div>`).join('');
  const lineups=(story.lineups||[]).map(row=>`<div class="lineup-row"><b>${escapeHTML(row.TEAM)} · ${row.PLAYERS.map(escapeHTML).join(' · ')}</b><span>${fmt(row.MIN,1)} MIN · ${Number(row.PLUS_MINUS)>=0?'+':''}${fmt(row.PLUS_MINUS,1)} · ${Number(row.NET_RATING)>=0?'+':''}${fmt(row.NET_RATING,1)} NET · ${escapeHTML(row.STINTS)} STINTS</span></div>`).join('');
  const shotSummary=(story.shot_summary||[]).map(row=>`<div class="zone-row"><b>${escapeHTML(row.TEAM||'—')} · ${escapeHTML(row.SHOT_TYPE||'Unknown shot')}</b><span>${escapeHTML(row.FGM)}</span><span>${escapeHTML(row.FGA)}</span><span>${fmt(Number(row.FG_PCT)*100,1)}%</span></div>`).join('');
  const feed=(story.feed||[]).map(row=>`<div class="game-story-row"><span>Q${escapeHTML(row.PERIOD)} ${escapeHTML(row.CLOCK)}</span><b>${escapeHTML(row.PLAYER||row.TEAM||'Game')}</b><span>${escapeHTML(row.EVENT)}</span><span>${escapeHTML(row.SCORE||'')}</span></div>`).join('');
  const chart=shotChartSVG(story);
  story.advancedTable=`<div class="split-table" tabindex="0" role="region" aria-label="Advanced team box"><div class="advanced-row header"><span>Team</span><span>PTS</span><span>eFG%</span><span>TS%</span><span>TOV%</span><span>FT rate</span><span>AST/TO</span><span>OREB</span><span>REB</span></div>${advanced}</div>`;
  return `<div class="game-story-grid"><div class="viz-grid game-story-viz"><div id="game-flow-chart"></div><div id="game-advanced-chart"></div></div><section class="panel game-story-card"><div class="subhead"><h3>Turning points</h3><span>LARGEST PROBABILITY SWINGS</span></div><div class="game-story-list">${turns||'<p class="analytics-note">No score changes were cached.</p>'}</div></section><section class="panel game-story-card"><div class="subhead"><h3>Game context</h3><span>RUNS · CLUTCH</span></div><div class="context-grid"><div class="context-tile"><b>${escapeHTML(story.biggest_runs?.[story.away]??'—')}</b><span>${escapeHTML(story.away)} biggest run</span></div><div class="context-tile"><b>${escapeHTML(story.biggest_runs?.[story.home]??'—')}</b><span>${escapeHTML(story.home)} biggest run</span></div><div class="context-tile"><b>${escapeHTML(story.lead_changes)}</b><span>Lead changes</span></div><div class="context-tile"><b>${escapeHTML(story.clutch_points?.[story.away]??0)}–${escapeHTML(story.clutch_points?.[story.home]??0)}</b><span>Clutch pts · away–home</span></div></div></section><section class="panel game-story-card"><div class="subhead"><h3>Shot profile</h3><span>${chart?'LOCATION CACHE':'SUMMARY ONLY'}</span></div>${chart||'<p class="analytics-note">Shot coordinates are not present in this older cache. Shot-type totals remain available below.</p>'}<div style="margin-top:14px">${shotSummary||'<p class="analytics-note">Shot events are unavailable.</p>'}</div></section><section class="panel game-story-card"><div class="subhead"><h3>Top lineups</h3><span>ON-COURT STINTS</span></div>${lineups||'<p class="analytics-note">Rotation data is not cached for this game, so lineup stints cannot be reconstructed.</p>'}</section><section class="panel game-story-card wide"><div class="subhead"><h3>Latest events</h3><span>PLAY-BY-PLAY FEED</span></div><div class="game-story-list">${feed||'<p class="analytics-note">Detailed events are unavailable.</p>'}</div></section></div>`;
}

function mountGameStory(story){
  const timeline=story.timeline||[],away=story.away,home=story.home;
  if(timeline.length){
    const last=timeline.at(-1),swing=(story.turning_points||[]).reduce((top,point)=>!top||Number(point.SWING)>Number(top.SWING)?point:top,null);
    mountChart($("game-flow-chart"),{
      title:"Game flow",
      takeaway:`${home} win probability finished at ${fmt(Number(last.HOME_WIN_PROB)*100,0)}%${swing?`; the biggest swing came in Q${swing.PERIOD} at ${swing.CLOCK}`:""}. ${story.lead_changes??0} lead changes.`,
      description:story.win_probability_method||"Home win probability after each scoring play.",
      plotFactory:gameFlowPlot(timeline,away,home),
      tableHTML:dataTable("Scoring timeline",["Time","Score","Home win"],timeline.map(point=>[`Q${point.PERIOD??"—"} ${point.CLOCK??""}`,`${away} ${point.AWAY_SCORE??"—"}–${point.HOME_SCORE??"—"} ${home}`,`${fmt(Number(point.HOME_WIN_PROB)*100,0)}%`])),
      dataLabel:"View every scoring update",
    });
  }else $("game-flow-chart").innerHTML='<div class="data-figure"><div class="figure-heading"><h4>Game flow</h4><p>Timeline data is unavailable.</p></div></div>';
  const rows=story.advanced||[],awayRow=rows.find(row=>row.TEAM===away),homeRow=rows.find(row=>row.TEAM===home);
  if(awayRow&&homeRow){
    const efgGap=(Number(homeRow.EFG_PCT)-Number(awayRow.EFG_PCT))*100;
    mountChart($("game-advanced-chart"),{
      title:"How the game was won",
      takeaway:`${efgGap>=0?home:away} shot better by ${fmt(Math.abs(efgGap),1)} eFG points. The longer the connector, the bigger that edge.`,
      description:"Team efficiency from this game's box score. Lower turnover rate is better; the other rows are better when higher.",
      plotFactory:advancedBoxDumbbellPlot(rows,away,home),
      tableHTML:dataTable("Advanced team box",["Team","PTS","eFG%","TS%","TOV%","FT rate","AST/TO","OREB","REB"],rows.map(team=>[team.TEAM,String(team.PTS??"—"),`${fmt(Number(team.EFG_PCT)*100,1)}%`,`${fmt(Number(team.TS_PCT)*100,1)}%`,`${fmt(Number(team.TOV_RATE)*100,1)}%`,`${fmt(Number(team.FT_RATE)*100,1)}%`,fmt(team.AST_TOV,2),String(team.OREB??"—"),String(team.REB??"—")])),
      dataLabel:"View full advanced box",
    });
  }else $("game-advanced-chart").innerHTML=`<div class="data-figure"><div class="figure-heading"><h4>Advanced team box</h4><p>Advanced team rows are unavailable for this game.</p></div>${story.advancedTable||""}</div>`;
}

$("games-output").addEventListener("click",async event=>{
  const row=event.target.closest("[data-game-id]");if(!row)return;
  const game=(gameData?.games||[]).find(item=>String(item.GAME_ID)===row.dataset.gameId),output=$("box-score-output");if(!game)return;
  const score=game.STATUS==="Final"?`${game.AWAY_PTS}–${game.HOME_PTS}`:(game.STATUS_TEXT||game.STATUS);
  const summary=`<section class="panel panel-pad" style="margin-top:20px"><div class="subhead"><h3>${escapeHTML(game.AWAY)} @ ${escapeHTML(game.HOME)}</h3><span>${escapeHTML(game.GAME_DATE)} · ${escapeHTML(game.STATUS)}</span></div><div class="context-grid"><div class="context-tile"><b>${escapeHTML(score)}</b><span>Score / tip</span></div><div class="context-tile"><b>${escapeHTML(game.WINNER||"—")}</b><span>Winner</span></div><div class="context-tile"><b>${escapeHTML(game.TOP_SCORER||"—")}</b><span>Top scorer</span></div><div class="context-tile"><b>${escapeHTML(game.GAME_ID)}</b><span>Game ID</span></div></div></section>`;
  output.innerHTML=summary+(game.STATUS==="Final"?'<div class="panel empty-state" style="min-height:180px"><div class="loading">LOADING FULL BOX SCORE…</div></div>':'<div class="panel panel-pad"><p class="analytics-note">The player box score becomes available after the game is final.</p></div>');
  output.scrollIntoView({behavior:"smooth",block:"start"});
  if(game.STATUS!=="Final")return;
  const season=encodeURIComponent(gameData.season),gameId=encodeURIComponent(game.GAME_ID);
  const [boxResult,storyResult]=await Promise.allSettled([api(`/games/${gameId}/box-score?season=${season}`),api(`/games/${gameId}/story?season=${season}`)]);
  let box;
  if(boxResult.status==="fulfilled"){
    const result=boxResult.value;
    box=`<section class="team-sections panel" style="margin-top:12px"><div class="subhead"><h3>Full box score</h3><span>${escapeHTML(result.source.replaceAll("_"," "))} · GAME ${escapeHTML(result.game_id)}</span></div>${Object.entries(result.teams).map(([team,players])=>`<div class="team-section"><div class="subhead"><h3>${escapeHTML(team)}</h3><span>PLAYER TOTALS</span></div><div class="split-table" tabindex="0" role="region" aria-label="${escapeHTML(team)} player box score"><div class="split-row header"><span>Player</span><span>MIN</span><span>PTS</span><span>REB</span><span>AST</span><span>STL</span><span>BLK</span><span>TO</span><span>FG</span></div>${players.map(player=>`<div class="split-row"><b>${escapeHTML(player.PLAYER)}</b><span>${fmt(player.MIN)}</span><span>${escapeHTML(player.PTS)}</span><span>${escapeHTML(player.REB)}</span><span>${escapeHTML(player.AST)}</span><span>${escapeHTML(player.STL)}</span><span>${escapeHTML(player.BLK)}</span><span>${escapeHTML(player.TO)}</span><span>${escapeHTML(player.FG)}</span></div>`).join("")}</div></div>`).join("")}</section>`;
  }else{box=`<section class="panel panel-pad" style="margin-top:12px"><h3>Player box score unavailable</h3><p class="error">${escapeHTML(boxResult.reason.message)}</p><p class="analytics-note">The score and game summary above remain available. NBA box-score data may not yet be cached or the upstream endpoint may be temporarily unavailable.</p></section>`;}
  const story=storyResult.status==="fulfilled"?renderGameStory(storyResult.value):`<section class="panel panel-pad" style="margin-top:12px"><h3>Game story unavailable</h3><p class="error">${escapeHTML(storyResult.reason.message)}</p><p class="analytics-note">Timeline analysis requires cached play-by-play data.</p></section>`;
  output.innerHTML=summary+story+box;
  if(storyResult.status==="fulfilled"&&storyResult.value.available)mountGameStory(storyResult.value);
});

registerPage("games", loadGames);
registerRetry("games", () => { gameData = null; loadGames(); });
