// Player search and profile: career, percentiles, shots, splits, impact.
import { $, api, deepValue, escapeHTML, fmt, money } from "../core.js";
import { dataTable } from "../render.js";
import { registerDeepLink, showPage } from "../router.js";
import {
  careerTrendPlot,
  metricLabel,
  mountChart,
  percentileDotPlot,
  splitSmallMultiples,
} from "../visualizations.js";

let debounce;
$("search").addEventListener("input", event => {
  clearTimeout(debounce);
  const q = event.target.value.trim();
  $("search-hint").classList.toggle("hidden", q.length >= 3);
  if (q.length < 3) { $("results").innerHTML = ""; return; }
  $("results").innerHTML = '<div class="loading">SEARCHING THE DATABASE…</div>';
  debounce = setTimeout(async () => {
    try {
      const players = await api(`/players/search?q=${encodeURIComponent(q)}`);
      $("results").innerHTML = players.slice(0, 10).map(player =>
        `<button data-id="${Number(player.id)}" data-name="${escapeHTML(player.full_name)}">${escapeHTML(player.full_name)}<span>${player.is_active ? "ACTIVE" : "HISTORICAL"} →</span></button>`
      ).join("") || '<div class="search-hint">No matching players found.</div>';
    } catch (error) { $("results").innerHTML = `<div class="error">${escapeHTML(error.message)}</div>`; }
  }, 250);
});
$("search-hint").addEventListener("click",event=>{
  const example=event.target.closest("[data-search-example]");
  if(!example)return;
  $("search").value=example.dataset.searchExample;
  $("search").dispatchEvent(new Event("input"));
  $("search").focus();
});
$("results").addEventListener("click", event => {
  const button = event.target.closest("button");
  if (button) loadProfile(Number(button.dataset.id), button.dataset.name);
});
$("profile").addEventListener("click",event=>{
  const player=event.target.closest("[data-player-id]");
  if(player)openPlayerProfile(Number(player.dataset.playerId),player.dataset.playerName);
});

async function loadProfile(id, name) {
  const profile = $("profile");
  profile.innerHTML = `<div class="empty-state"><div class="loading">ASSEMBLING ${escapeHTML(name.toUpperCase())}…</div></div>`;
  try {
    const seasons = await api(`/players/${id}/career`);
    // keep the address bar a shareable link to this profile
    history.replaceState(null, "", `#players/${id}`);
    const latest = seasons.at(-1);
    let percentileData = null;
    try { percentileData = await api(`/players/${id}/percentiles`); } catch { /* percentiles are optional context */ }
    const [gamesResult, similarResult] = await Promise.allSettled([
      api(`/players/${id}/games?limit=10`), api(`/players/${id}/similar?limit=6`)
    ]);
    const recentGames = gamesResult.status === "fulfilled" ? gamesResult.value.games : [];
    const similar = similarResult.status === "fulfilled" ? similarResult.value.similar : [];
    const stats = [
      ["PTS", fmt(latest.PTS)], ["AST", fmt(latest.AST)], ["REB", fmt(latest.REB)],
      ["GP", fmt(latest.GP, 0)], ["FG%", latest.FG_PCT == null ? "—" : fmt(latest.FG_PCT * 100) + "%"],
      ["3P%", latest.FG3_PCT == null ? "—" : fmt(latest.FG3_PCT * 100) + "%"]
    ];
    const pctEntries = percentileData ? Object.entries(percentileData.percentiles).filter(([,value]) => Number.isFinite(Number(value))) : [];
    const initials = name.split(/\s+/).map(part => part[0]).join("").slice(0,2);
    profile.innerHTML = `
      <div class="profile-hero">
        <img class="player-photo" src="/players/${id}/headshot" alt="${escapeHTML(name)}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'player-fallback',textContent:'${escapeHTML(initials)}'}))">
        <div class="profile-identity"><div class="season">${escapeHTML(latest.SEASON_ID)} / Latest season</div><h2>${escapeHTML(name)}</h2><p>${fmt(latest.GP,0)} games logged · Per-game production</p></div>
      </div>
      <div class="profile-body">
        <div class="stat-grid">${stats.map(([label,value]) => `<div class="stat"><b>${value}</b><span>${label}${["PTS","AST","REB"].includes(label) ? " / game" : ""}</span></div>`).join("")}</div>
        <div class="profile-lower">
          <div id="profile-trend-chart"></div>
          <div id="profile-pct-chart">${pctEntries.length ? "" : '<div class="subhead"><h3>League standing</h3><span>NOT AVAILABLE</span></div><p class="search-hint">Current-season percentiles are available for active players with a qualifying sample.</p>'}</div>
        </div>
        <div class="insight-stack">
          <div><div class="subhead"><h3>Recent form</h3><span>LAST ${recentGames.length} GAMES</span></div>
            ${recentGames.length ? `<div class="game-strip">${recentGames.map(game => `<div class="game-chip ${game.WL === "W" ? "win" : "loss"}"><div class="game-date">${escapeHTML(game.DATE)}</div><b>${escapeHTML(game.PTS)} PTS</b><span>${escapeHTML(game.MATCHUP)} · ${escapeHTML(game.WL)}</span></div>`).join("")}</div>` : '<p class="search-hint">Recent game data is unavailable for this season.</p>'}
          </div>
          <div><div class="subhead"><h3>Similar players</h3><span>STYLE MATCH</span></div>
            ${similar.length ? `<div class="comp-list">${similar.map(player => `<div class="comp-item"><button class="entity-link" data-player-id="${Number(player.PLAYER_ID)}" data-player-name="${escapeHTML(player.PLAYER_NAME)}"><b>${escapeHTML(player.PLAYER_NAME)}</b><small>${escapeHTML(player.TEAM_ABBREVIATION)} · ${fmt(player.PTS)} PTS</small></button><span class="comp-score">${fmt(player.SIMILARITY,0)}%</span></div>`).join("")}</div>` : '<p class="search-hint">Statistical comps require an active-season sample.</p>'}
          </div>
        </div>
        <div class="profile-controls">
          <label>Analysis season<select id="profile-season">${seasons.slice().reverse().map(season => `<option value="${escapeHTML(season.SEASON_ID)}" ${season.SEASON_ID === latest.SEASON_ID ? "selected" : ""}>${escapeHTML(season.SEASON_ID)}</option>`).join("")}</select></label>
          <label>Shot sample<select id="profile-season-type"><option>Regular Season</option><option>Playoffs</option></select></label>
        </div>
        <div id="profile-deep" class="deep-stack"><div class="loading">LOADING DEEP ANALYTICS…</div></div>
      </div>`;
    const careerSeasons = new Set(seasons.map(season => season.SEASON_ID)).size;
    mountChart($("profile-trend-chart"),{
      title:"Career arc",
      takeaway:careerSeasons > 1 ? `${name}'s per-game production across ${careerSeasons} seasons; the latest values are labelled at the right edge.` : `${name} has one season on record, so there is no trend yet.`,
      description:`Per-game averages by season · ${careerSeasons} season${careerSeasons===1?"":"s"} on record.`,
      plotFactory:careerTrendPlot(seasons),
      tableHTML:dataTable(`${name} career per-game averages`,["Season","GP","PTS","REB","AST"],seasons.slice().reverse().map(season=>[season.SEASON_ID,fmt(season.GP,0),fmt(season.PTS),fmt(season.REB),fmt(season.AST)])),
      dataLabel:"View every season",
    });
    if(pctEntries.length){
      const top=pctEntries.reduce((best,entry)=>Number(entry[1])>Number(best[1])?entry:best);
      mountChart($("profile-pct-chart"),{
        title:"League standing",
        takeaway:`Strongest relative skill: ${metricLabel(top[0])} at the ${Math.round(top[1])}th percentile. Dots right of the median rule beat most of the league.`,
        description:`${percentileData.season} · percentile rank among qualified players · higher is better for every row.`,
        plotFactory:percentileDotPlot(Object.fromEntries(pctEntries),"league"),
        tableHTML:dataTable(`${name} league percentiles`,["Metric","Percentile"],pctEntries.map(([key,value])=>[metricLabel(key),`${Math.round(value)}th`])),
        dataLabel:"View exact percentiles",
      });
    }
    const refreshDeep = () => loadProfileDeep(id, name, $("profile-season").value, $("profile-season-type").value);
    $("profile-season").addEventListener("change", refreshDeep);
    $("profile-season-type").addEventListener("change", refreshDeep);
    await refreshDeep();
  } catch (error) { profile.innerHTML = `<div class="empty-state"><div><h3>Profile unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`; }
}

// Exact values behind every chart, as a real table for screen readers.

function shotCourt(data, mode = "hex") {
  if (!data?.attempts?.length) return '<div class="empty-state" style="min-height:360px"><p>No shots in this sample.</p></div>';
  const zoneDiff = new Map((data.zones || []).map(zone => [
    [zone.SHOT_ZONE_BASIC,zone.SHOT_ZONE_AREA,zone.SHOT_ZONE_RANGE].join("|"), Number(zone.DIFF)
  ]));
  let marks = "";
  if (mode === "hex") {
    const max = Math.max(1,...data.hexes.map(hex => Number(hex.FGA) || 0));
    marks = data.hexes.map(hex => {
      const diff = Number(hex.DIFF) || 0, color = diff > .02 ? "#c9f65b" : diff < -.02 ? "#ff6b6b" : "#6f7884";
      const radius = 5 + 13 * Math.sqrt((Number(hex.FGA)||0) / max);
      return `<circle cx="${Number(hex.X)}" cy="${Number(hex.Y)}" r="${radius}" fill="${color}" fill-opacity=".72"><title>${escapeHTML(hex.FGA)} shots · ${fmt(Number(hex.PCT)*100)}% · ${diff>=0?"+":""}${fmt(diff*100)} vs league</title></circle>`;
    }).join("");
  } else {
    marks = data.attempts.map(shot => {
      const key = [shot.SHOT_ZONE_BASIC,shot.SHOT_ZONE_AREA,shot.SHOT_ZONE_RANGE].join("|");
      const diff = zoneDiff.get(key) || 0;
      const color = mode === "zone" ? (diff > .02 ? "#c9f65b" : diff < -.02 ? "#ff6b6b" : "#6f7884") : (Number(shot.SHOT_MADE_FLAG) ? "#c9f65b" : "#6f7884");
      return `<circle cx="${Number(shot.LOC_X)}" cy="${Number(shot.LOC_Y)}" r="4" fill="${color}" fill-opacity=".76"><title>${escapeHTML(shot.SHOT_ZONE_BASIC)} · ${Number(shot.SHOT_MADE_FLAG)?"made":"missed"}</title></circle>`;
    }).join("");
  }
  return `<svg class="shot-court" viewBox="-250 -55 500 405" role="img" aria-label="Player shot chart">
    <g fill="none" stroke="#343c46" stroke-width="2"><rect x="-250" y="-47" width="500" height="395"/><circle cx="0" cy="0" r="7.5"/><line x1="-30" y1="-7" x2="30" y2="-7"/><rect x="-80" y="-47" width="160" height="190"/><path d="M-220 92 L-220 -47 M220 92 L220 -47 M-220 92 A237.5 237.5 0 0 0 220 92"/><path d="M-60 143 A60 60 0 0 0 60 143"/></g>${marks}</svg>`;
}

const splitLabels = {home_away:"Home / away",month:"Month",rest:"Rest",opponent:"Opponent"};
const splitMetrics = [["PTS","Points"],["REB","Rebounds"],["AST","Assists"],["FG_PCT","FG%",true],["FG3M","Threes made"],["PLUS_MINUS","Plus-minus"]];
function mountSplits(splits, mode, season) {
  const rows = splits?.splits?.[mode] || [];
  const target = $("split-viz");
  if (!rows.length) { target.innerHTML = '<p class="analytics-note">No games in this split for the selected season.</p>'; return; }
  const sample = rows.reduce((sum,row) => sum + (Number(row.GP) || 0), 0);
  mountChart(target,{
    title:`Splits by ${splitLabels[mode].toLowerCase()}`,
    takeaway:"Each panel uses its own scale, so compare splits within a panel, not across panels.",
    description:`${season} · per-game averages · ${sample} games across ${rows.length} splits. Small splits are noisy; check games played in the table.`,
    plotFactory:splitSmallMultiples(rows,splitMetrics),
    tableHTML:dataTable(`Splits by ${splitLabels[mode].toLowerCase()}`,["Split","GP","MIN","PTS","REB","AST","3PM","FG%","+/-"],rows.map(row=>[row.Split,fmt(row.GP,0),fmt(row.MIN),fmt(row.PTS),fmt(row.REB),fmt(row.AST),fmt(row.FG3M),row.FG_PCT==null?"—":`${fmt(Number(row.FG_PCT)*100)}%`,row.PLUS_MINUS==null?"—":`${Number(row.PLUS_MINUS)>=0?"+":""}${fmt(row.PLUS_MINUS)}`])),
    dataLabel:"View exact split table",
  });
}

async function loadProfileDeep(id, name, season, seasonType) {
  const target = $("profile-deep");
  target.innerHTML = '<div class="loading">REFRESHING DEEP ANALYTICS…</div>';
  const encodedSeason = encodeURIComponent(season), encodedType = encodeURIComponent(seasonType);
  const [insightsResult, shotsResult, splitsResult, onOffResult, contractResult] = await Promise.allSettled([
    api(`/players/${id}/insights?season=${encodedSeason}`),
    api(`/players/${id}/shots?season=${encodedSeason}&season_type=${encodedType}`),
    api(`/players/${id}/splits?season=${encodedSeason}`),
    api(`/players/${id}/on-off`),
    api(`/players/${id}/contract`),
  ]);
  const insights = deepValue(insightsResult), shots = deepValue(shotsResult), splits = deepValue(splitsResult);
  const onOff = deepValue(onOffResult)?.on_off, contract = deepValue(contractResult);
  const ratings = insights?.ratings || {}, positionPercentiles = Object.fromEntries(Object.entries(insights?.position_percentiles || {}).filter(([,value]) => Number.isFinite(Number(value))));
  const quality = shots?.quality || {}, breakdown = shots?.breakdown || [];
  target.innerHTML = `
    <section class="deep-panel"><div class="subhead"><h3>Scouting context</h3><span>${escapeHTML(insights?.season || season)} · ${escapeHTML(insights?.position_group || "League")}</span></div>
      ${insights?.scouting_take ? `<div class="scouting-card">${escapeHTML(insights.scouting_take)}</div>` : '<p class="analytics-note">Scouting context is unavailable for this sample.</p>'}
      <div class="context-grid">
        <div class="context-tile"><b>${ratings.NET_RATING == null ? "—" : `${Number(ratings.NET_RATING)>=0?"+":""}${fmt(ratings.NET_RATING)}`}</b><span>Net rating</span></div>
        <div class="context-tile"><b>${ratings.CLUTCH_NET_RATING == null ? "—" : `${Number(ratings.CLUTCH_NET_RATING)>=0?"+":""}${fmt(ratings.CLUTCH_NET_RATING)}`}</b><span>Clutch net</span></div>
        <div class="context-tile"><b>${ratings.DPM == null ? "—" : `${Number(ratings.DPM)>=0?"+":""}${fmt(ratings.DPM)}`}</b><span>DARKO DPM</span></div>
        <div class="context-tile"><b>${escapeHTML(insights?.draft || "Undrafted")}</b><span>Draft pedigree</span></div>
      </div>${Object.keys(positionPercentiles).length ? '<div id="position-pct-chart" style="margin-top:20px"></div>' : ""}
    </section>
    <section class="deep-panel"><div class="subhead"><h3>On / off impact</h3><span>${escapeHTML(onOff ? "CURRENT TEAM" : "UNAVAILABLE")}</span></div>
      ${onOff ? `<div class="context-grid"><div class="context-tile"><b>${fmt(onOff.NET_ON)}</b><span>Team net · on</span></div><div class="context-tile"><b>${fmt(onOff.NET_OFF)}</b><span>Team net · off</span></div><div class="context-tile"><b>${Number(onOff.NET_DIFF)>=0?"+":""}${fmt(onOff.NET_DIFF)}</b><span>On/off swing</span></div><div class="context-tile"><b>${fmt(onOff.MIN_ON,0)}</b><span>Minutes on</span></div></div>` : '<p class="analytics-note">On/off data is available for active players with a current team row.</p>'}
    </section>
    <section class="deep-panel"><div class="subhead"><h3>Shot intelligence</h3><span>${escapeHTML(seasonType)} · ${shots?.attempts?.length || 0} attempts</span></div>
      <div class="profile-controls"><label>Chart view<select id="shot-mode"><option value="hex">Hot zones</option><option value="zone">Zone vs league</option><option value="raw">Makes / misses</option></select></label></div>
      <div class="shot-layout"><div><div id="shot-viz">${shotCourt(shots,"hex")}</div><div class="shot-key"><span><i style="background:#c9f65b"></i>Above / made</span><span><i style="background:#ff6b6b"></i>Below league</span><span><i style="background:#6f7884"></i>Neutral / missed</span></div></div>
      <div><div class="context-grid" style="grid-template-columns:1fr 1fr"><div class="context-tile"><b>${quality.XEFG==null?"—":fmt(Number(quality.XEFG)*100)+"%"}</b><span>Expected eFG%</span></div><div class="context-tile"><b>${quality.EFG==null?"—":fmt(Number(quality.EFG)*100)+"%"}</b><span>Actual eFG%</span></div><div class="context-tile"><b>${quality.MAKING==null?"—":`${Number(quality.MAKING)>=0?"+":""}${fmt(Number(quality.MAKING)*100)}`}</b><span>Shot making</span></div><div class="context-tile"><b>${quality.LEAGUE_EFG==null?"—":fmt(Number(quality.LEAGUE_EFG)*100)+"%"}</b><span>League eFG%</span></div></div>
      <div style="margin-top:14px">${breakdown.map(zone => `<div class="zone-row"><b>${escapeHTML(zone.ZONE)}</b><span>${fmt(Number(zone.SHARE)*100)}%</span><span>${fmt(Number(zone.FG_PCT)*100)}%</span><span class="${Number(zone.DIFF)>=0?"positive":"negative-text"}">${zone.DIFF==null?"—":`${Number(zone.DIFF)>=0?"+":""}${fmt(Number(zone.DIFF)*100)}`}</span></div>`).join("")}</div></div></div>
      <p class="analytics-note">Hot-zone size is shot volume; color is accuracy versus the league expectation for those locations.</p>
    </section>
    <section class="deep-panel"><div class="subhead"><h3>Situational splits</h3><span>${escapeHTML(season)}</span></div>
      <div class="profile-controls"><label>Split by<select id="split-mode"><option value="home_away">Home / away</option><option value="month">Month</option><option value="rest">Rest</option><option value="opponent">Opponent</option></select></label></div><div id="split-viz"></div>
    </section>
    <section class="deep-panel"><div class="subhead"><h3>Contract & salary</h3><span>LOCAL-ONLY DATA</span></div>
      ${contract ? `<div class="context-grid"><div class="context-tile"><b>${money(Object.values(contract.salaries)[0])}</b><span>Current salary</span></div><div class="context-tile"><b>${money(Object.values(contract.salaries).reduce((sum,value)=>sum+Number(value),0))}</b><span>Committed total</span></div><div class="context-tile"><b>${money(contract.guaranteed)}</b><span>Guaranteed</span></div></div><div style="margin-top:13px">${Object.entries(contract.salaries).map(([year,value]) => `<div class="contract-row"><b>${escapeHTML(year)}</b><span>${money(value)}</span><span></span><span></span></div>`).join("")}</div><p class="analytics-note">Scraped weekly for personal use and served only to the local machine.</p>` : '<p class="analytics-note">No listed contract, or this request is not coming from the local machine.</p>'}
    </section>`;
  $("shot-mode")?.addEventListener("change", event => { $("shot-viz").innerHTML = shotCourt(shots,event.target.value); });
  mountSplits(splits,"home_away",season);
  $("split-mode")?.addEventListener("change", event => mountSplits(splits,event.target.value,season));
  if (Object.keys(positionPercentiles).length) {
    const group = insights.position_group || "position";
    const entries = Object.entries(positionPercentiles);
    const above = entries.filter(([,value]) => Number(value) >= 50).length;
    mountChart($("position-pct-chart"),{
      title:`Versus ${group} peers`,
      takeaway:`${above} of ${entries.length} measures sit at or above the ${group.toLowerCase()} median (the vertical rule).`,
      description:`${insights.season || season} · percentile rank against inferred ${group} peers · higher is better on every row.`,
      plotFactory:percentileDotPlot(positionPercentiles,group.toLowerCase()),
      tableHTML:dataTable(`${name} position percentiles`,["Metric","Percentile"],entries.map(([key,value])=>[metricLabel(key),`${Math.round(value)}th`])),
      dataLabel:"View exact position percentiles",
    });
  }
}


export async function openPlayerProfile(id,name){
  showPage("players");
  $("search").value=name;
  $("search-hint").classList.add("hidden");
  $("results").innerHTML="";
  await loadProfile(id,name);
}

export { loadProfile };

// #players/<id> opens that profile; the name comes from the offline player table.
registerDeepLink("players", async param => {
  const id = Number(param);
  if (!Number.isInteger(id) || id <= 0) return;
  try {
    const player = await api(`/players/${id}`);
    await openPlayerProfile(id, player.full_name);
  } catch (error) {
    $("profile").innerHTML = `<div class="empty-state"><div><h3>Player not found</h3><p class="error">${escapeHTML(error.message)}</p><p>Search by name instead.</p></div></div>`;
  }
});
