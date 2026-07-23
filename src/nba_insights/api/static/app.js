import { $, api, deepValue, escapeHTML, fmt, money } from "./core.js";
import {
  driverWaterfallPlot,
  exploreScatterPlot,
  matchupRankPlot,
  mountChart,
  playerIntervalPlot,
  probabilityPlot,
  winIntervalPlot,
} from "./visualizations.js";
function updateConnectionStatus(){
  if(!navigator.onLine){
    $("app-status").innerHTML='<i class="live-dot offline"></i> Offline · showing saved data when available';
  }else if(metaData){
    $("app-status").innerHTML=`<i class="live-dot"></i> ${escapeHTML(metaData.current_season)} data available`;
  }
}
window.addEventListener("online",updateConnectionStatus);
window.addEventListener("offline",updateConnectionStatus);

function showPage(page, updateHash = true) {
  const primaryPage = ["pulse", "players", "games", "matchup"].includes(page) ? page : "more";
  document.querySelectorAll(".page").forEach(el => el.classList.toggle("active", el.id === `page-${page}`));
  document.querySelectorAll(".desktop-nav [data-page], .mobile-nav [data-page]").forEach(el => {
    const active = el.dataset.page === primaryPage;
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  if (updateHash) history.replaceState(null, "", page === "pulse" ? location.pathname : `#${page}`);
  if (page === "pulse") loadPulse();
  if (page === "explore") loadExplore();
  if (page === "teams") loadTeamPicker();
  if (page === "games") loadGames();
  if (page === "tracking") loadTracking();
  if (page === "matchup") loadTeams();
  if (page === "outlook") loadOutlook();
  if (page === "ask") loadMeta();
  if (page === "methodology") loadMethodology();
  window.scrollTo({ top: 0, behavior: "smooth" });
  if(updateHash){
    const heading=document.querySelector(`#page-${page} h1`);
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
  }
}
document.querySelectorAll("[data-page]").forEach(el => el.addEventListener("click", () => showPage(el.dataset.page)));
const initialPage = ["pulse", "players", "explore", "compare", "teams", "games", "tracking", "matchup", "outlook", "ask", "methodology", "more"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "pulse";
queueMicrotask(() => showPage(initialPage, false));
queueMicrotask(updateConnectionStatus);

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
    const latest = seasons.at(-1);
    let percentileData = null;
    try { percentileData = await api(`/players/${id}/percentiles`); } catch {}
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
    const pctEntries = percentileData ? Object.entries(percentileData.percentiles).slice(0, 8) : [];
    const initials = name.split(/\s+/).map(part => part[0]).join("").slice(0,2);
    profile.innerHTML = `
      <div class="profile-hero">
        <img class="player-photo" src="/players/${id}/headshot" alt="${escapeHTML(name)}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'player-fallback',textContent:'${escapeHTML(initials)}'}))">
        <div class="profile-identity"><div class="season">${escapeHTML(latest.SEASON_ID)} / Latest season</div><h2>${escapeHTML(name)}</h2><p>${fmt(latest.GP,0)} games logged · Per-game production</p></div>
      </div>
      <div class="profile-body">
        <div class="stat-grid">${stats.map(([label,value]) => `<div class="stat"><b>${value}</b><span>${label}${["PTS","AST","REB"].includes(label) ? " / game" : ""}</span></div>`).join("")}</div>
        <div class="profile-lower">
          <div><div class="subhead"><h3>League standing</h3><span>${percentileData ? escapeHTML(percentileData.season) : "NOT AVAILABLE"}</span></div>
            ${pctEntries.length ? pctEntries.map(([key,value]) => `<div class="pct-row"><label title="${escapeHTML(key)}">${escapeHTML(key)}</label><div class="track"><div class="fill" style="width:${Math.max(0,Math.min(100,Number(value)))}%"></div></div><b>${Math.round(value)}</b></div>`).join("") : '<p class="search-hint">Current-season percentiles are available for active players with a qualifying sample.</p>'}
          </div>
          <div><div class="subhead"><h3>Career trail</h3><span>PTS · AST · REB</span></div><div class="career-list">
            ${seasons.slice().reverse().map((season,index) => `<div class="career-row ${index === 0 ? "current" : ""}"><b>${escapeHTML(season.SEASON_ID)}</b><span>${fmt(season.PTS)}</span><span>${fmt(season.AST)}</span><span>${fmt(season.REB)}</span></div>`).join("")}
          </div></div>
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
    const refreshDeep = () => loadProfileDeep(id, name, $("profile-season").value, $("profile-season-type").value);
    $("profile-season").addEventListener("change", refreshDeep);
    $("profile-season-type").addEventListener("change", refreshDeep);
    await refreshDeep();
  } catch (error) { profile.innerHTML = `<div class="empty-state"><div><h3>Profile unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`; }
}

function percentileRows(entries) {
  return entries.length ? entries.map(([key,value]) => `<div class="pct-row"><label>${escapeHTML(key.replaceAll("_"," "))}</label><div class="track"><div class="fill" style="width:${Math.max(0,Math.min(100,Number(value)))}%"></div></div><b>${Math.round(value)}</b></div>`).join("") : '<p class="analytics-note">No qualifying percentile sample.</p>';
}

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

function splitRows(rows) {
  const columns = ["GP","MIN","PTS","REB","AST","FG3M","FG_PCT","PLUS_MINUS"];
  const header = `<div class="split-row header"><span>Split</span>${columns.map(column => `<span>${column.replace("PLUS_MINUS","+/-").replace("FG_PCT","FG%")}</span>`).join("")}</div>`;
  return header + rows.map(row => `<div class="split-row"><b>${escapeHTML(row.Split)}</b>${columns.map(column => `<span>${row[column] == null ? "—" : column === "FG_PCT" ? fmt(Number(row[column])*100)+"%" : fmt(row[column],column === "GP" ? 0 : 1)}</span>`).join("")}</div>`).join("");
}

function positionOctagonEntries(percentiles) {
  const preferred = ["PTS","AST","REB","STL","BLK","FG_PCT","NET_RATING","DPM"];
  const available = Object.entries(percentiles || {}).filter(([,value]) => Number.isFinite(Number(value)));
  const selected = preferred.filter(stat => Number.isFinite(Number(percentiles?.[stat])));
  available.forEach(([stat]) => { if (selected.length < 8 && !selected.includes(stat)) selected.push(stat); });
  return selected.slice(0,8).map(stat => [stat,Number(percentiles[stat])]);
}

function renderPositionOctagon(entries, playerName, positionGroup) {
  if (entries.length !== 8) return '<p class="analytics-note">The octagon requires eight qualifying position metrics; exact available percentiles are shown below.</p>';
  const group = positionGroup || "position";
  const labels={PTS:"Scoring",AST:"Creation",REB:"Rebounding",STL:"Steals",BLK:"Blocks",
    FG_PCT:"FG efficiency",NET_RATING:"Net rating",DPM:"DPM",FG3_PCT:"3PT efficiency",FT_PCT:"FT efficiency"};
  const width=640,height=500,cx=320,cy=235,radius=165,labelRadius=207;
  const point=(index,value,r=radius)=>{const angle=-Math.PI/2+index*Math.PI/4;
    return [cx+Math.cos(angle)*r*value/100,cy+Math.sin(angle)*r*value/100];};
  const polygon=value=>entries.map((_,index)=>point(index,value).map(number=>number.toFixed(1)).join(",")).join(" ");
  const grid=[25,50,75,100].map(level=>`<polygon points="${polygon(level)}" fill="none" stroke="#303741" stroke-width="1"/><text x="${cx+5}" y="${(cy-radius*level/100+4).toFixed(1)}" fill="#6f7681" font-size="10">${level}</text>`).join("");
  const axes=entries.map(([stat],index)=>{const [x,y]=point(index,100),[lx,ly]=point(index,100,labelRadius),anchor=lx<cx-12?"end":lx>cx+12?"start":"middle";
    return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#303741"/><text x="${lx.toFixed(1)}" y="${(ly+5).toFixed(1)}" text-anchor="${anchor}" fill="#979da8" font-size="13">${escapeHTML(labels[stat]||stat.replaceAll("_"," "))}</text>`;}).join("");
  const shape=entries.map(([,value],index)=>point(index,value).map(number=>number.toFixed(1)).join(",")).join(" ");
  const dots=entries.map(([stat,value],index)=>{const [x,y]=point(index,value);return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" fill="#ff5c35"><title>${escapeHTML(labels[stat]||stat)}: ${Math.round(value)}th percentile among ${escapeHTML(group)}s</title></circle>`;}).join("");
  return `<div class="position-octagon"><div class="position-octagon-scroll"><svg class="position-octagon-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHTML(playerName)} position percentile octagon"><title>${escapeHTML(playerName)} compared with inferred ${escapeHTML(group)} peers</title>${grid}${axes}<polygon points="${polygon(50)}" fill="none" stroke="#f2f0e9" stroke-opacity=".7" stroke-width="2" stroke-dasharray="7 6"/><polygon points="${shape}" fill="#ff5c35" fill-opacity=".13" stroke="#ff5c35" stroke-width="4" stroke-linejoin="round"/>${dots}</svg></div><div class="position-octagon-legend"><span><i></i>${escapeHTML(playerName)}</span><span><i class="median"></i>${escapeHTML(group)} median · 50th percentile</span></div><p class="analytics-note">Shape is percentile rank against inferred ${escapeHTML(group)} peers. Higher and farther from center is better.</p></div>`;
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
  const ratings = insights?.ratings || {}, positionEntries = positionOctagonEntries(insights?.position_percentiles);
  const quality = shots?.quality || {}, breakdown = shots?.breakdown || [];
  // Exact position-percentile bars intentionally stay hidden; octagon dots retain values.
  target.innerHTML = `
    <section class="deep-panel"><div class="subhead"><h3>Scouting context</h3><span>${escapeHTML(insights?.season || season)} · ${escapeHTML(insights?.position_group || "League")}</span></div>
      ${insights?.scouting_take ? `<div class="scouting-card">${escapeHTML(insights.scouting_take)}</div>` : '<p class="analytics-note">Scouting context is unavailable for this sample.</p>'}
      <div class="context-grid">
        <div class="context-tile"><b>${ratings.NET_RATING == null ? "—" : `${Number(ratings.NET_RATING)>=0?"+":""}${fmt(ratings.NET_RATING)}`}</b><span>Net rating</span></div>
        <div class="context-tile"><b>${ratings.CLUTCH_NET_RATING == null ? "—" : `${Number(ratings.CLUTCH_NET_RATING)>=0?"+":""}${fmt(ratings.CLUTCH_NET_RATING)}`}</b><span>Clutch net</span></div>
        <div class="context-tile"><b>${ratings.DPM == null ? "—" : `${Number(ratings.DPM)>=0?"+":""}${fmt(ratings.DPM)}`}</b><span>DARKO DPM</span></div>
        <div class="context-tile"><b>${escapeHTML(insights?.draft || "Undrafted")}</b><span>Draft pedigree</span></div>
      </div>${positionEntries.length ? `<div class="subhead" style="margin-top:20px"><h3>Position percentiles</h3><span>Inferred ${escapeHTML(insights.position_group)}</span></div>${renderPositionOctagon(positionEntries,name,insights.position_group)}` : ""}
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
      <div class="profile-controls"><label>Split by<select id="split-mode"><option value="home_away">Home / away</option><option value="month">Month</option><option value="rest">Rest</option><option value="opponent">Opponent</option></select></label></div><div id="split-viz" class="split-table">${splitRows(splits?.splits?.home_away || [])}</div>
    </section>
    <section class="deep-panel"><div class="subhead"><h3>Contract & salary</h3><span>LOCAL-ONLY DATA</span></div>
      ${contract ? `<div class="context-grid"><div class="context-tile"><b>${money(Object.values(contract.salaries)[0])}</b><span>Current salary</span></div><div class="context-tile"><b>${money(Object.values(contract.salaries).reduce((sum,value)=>sum+Number(value),0))}</b><span>Committed total</span></div><div class="context-tile"><b>${money(contract.guaranteed)}</b><span>Guaranteed</span></div></div><div style="margin-top:13px">${Object.entries(contract.salaries).map(([year,value]) => `<div class="contract-row"><b>${escapeHTML(year)}</b><span>${money(value)}</span><span></span><span></span></div>`).join("")}</div><p class="analytics-note">Scraped weekly for personal use and served only to the local machine.</p>` : '<p class="analytics-note">No listed contract, or this request is not coming from the local machine.</p>'}
    </section>`;
  $("shot-mode")?.addEventListener("change", event => { $("shot-viz").innerHTML = shotCourt(shots,event.target.value); });
  $("split-mode")?.addEventListener("change", event => { $("split-viz").innerHTML = splitRows(splits?.splits?.[event.target.value] || []); });
}

let pulseLoaded = false;
let pulseData = null;
let metaData = null;
async function loadMeta(){
  if(metaData)return metaData;
  metaData=await api("/meta");
  const options=metaData.seasons.map(season=>`<option value="${escapeHTML(season)}">${escapeHTML(season)}</option>`).join("");
  ["pulse-season","explore-season","games-season","tracking-season"].forEach(id=>{if($(id))$(id).innerHTML=options;});
  const forecastOptions=(metaData.prediction_seasons||[metaData.current_season]).map((season,index)=>`<option value="${escapeHTML(season)}" ${index?"selected":""}>${escapeHTML(season)}${index?" · preseason projection":""}</option>`).join("");
  ["prediction-season","outlook-season"].forEach(id=>{if($(id))$(id).innerHTML=forecastOptions;});
  const askEnabled=Boolean(metaData.capabilities?.ask_ai);
  $("more-ask").classList.toggle("hidden",!askEnabled);
  if(!askEnabled){
    $("ask-go").disabled=true;
    $("ask-output").innerHTML='<div class="empty-state" style="min-height:330px"><div><h3>Ask AI is not configured</h3><p>This optional tool appears when the server has the Anthropic package and credential. All non-AI analytics remain available.</p></div></div>';
  }
  updateConnectionStatus();
  return metaData;
}
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
    const formRows = teams.map((team,index) => {
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

async function openPlayerProfile(id,name){
  showPage("players");
  $("search").value=name;
  $("search-hint").classList.add("hidden");
  $("results").innerHTML="";
  await loadProfile(id,name);
}
async function openTeamRoom(team){
  await loadTeamPicker();
  showPage("teams");
  $("team-pick").value=team;
  $("team-pick").dispatchEvent(new Event("change"));
}
async function openMatchup(away,home){
  await loadTeams();
  showPage("matchup");
  $("away").value=away;
  $("home").value=home;
}
$("pulse-content").addEventListener("click",event=>{
  const player=event.target.closest("[data-player-id]");
  if(player){openPlayerProfile(Number(player.dataset.playerId),player.dataset.playerName);return;}
  const team=event.target.closest("[data-team]");
  if(team){openTeamRoom(team.dataset.team);return;}
  const game=event.target.closest("[data-away][data-home]");
  if(game)openMatchup(game.dataset.away,game.dataset.home);
});

let exploreLoaded = false;
let exploreData = null;
async function loadExplore() {
  if (!exploreLoaded) {
    try {
      await loadMeta();
      const teams = await api("/teams");
      $("explore-team").innerHTML = '<option value="">All teams</option>' + teams.map(team => `<option>${escapeHTML(team)}</option>`).join("");
    } catch {}
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

const FAVORITES_KEY="nba-insights-favorites-v1",ALERTS_KEY="nba-insights-tracking-alerts-v1",TRACKING_SEEN_KEY="nba-insights-tracking-seen-v1";
let trackingInitialized=false,trackingResult=null;
const loadFavorites=()=>{try{return JSON.parse(localStorage.getItem(FAVORITES_KEY))||[];}catch{return [];}};
const saveFavorites=favorites=>localStorage.setItem(FAVORITES_KEY,JSON.stringify(favorites));
async function initializeTracking(){
  if(trackingInitialized)return;await loadMeta();
  const teams=await api("/teams"),params=new URLSearchParams(location.search);
  $("tracking-team").innerHTML='<option value="">All teams</option>'+teams.map(team=>`<option>${escapeHTML(team)}</option>`).join('');
  if(params.get("tracking_category"))$("tracking-category").value=params.get("tracking_category");
  if(params.get("tracking_scope"))$("tracking-scope").value=params.get("tracking_scope");
  if(params.get("tracking_season"))$("tracking-season").value=params.get("tracking_season");
  if(params.get("tracking_team"))$("tracking-team").value=params.get("tracking_team");
  if(params.get("tracking_min_games"))$("tracking-min-games").value=params.get("tracking_min_games");
  if(params.get("tracking_query"))$("tracking-query").value=params.get("tracking_query");
  $("tracking-notifications").textContent=localStorage.getItem(ALERTS_KEY)==="enabled"?"Local alerts enabled":"Enable local alerts";
  trackingInitialized=true;
}
async function loadTracking(){
  const output=$("tracking-output");output.innerHTML='<div class="panel empty-state"><div class="loading">LOADING OFFICIAL TRACKING FEED…</div></div>';
  try{
    await initializeTracking();
    const params=new URLSearchParams({season:$("tracking-season").value,category:$("tracking-category").value,scope:$("tracking-scope").value,min_games:$("tracking-min-games").value||"0",team:$("tracking-team").value,query:$("tracking-query").value.trim(),limit:"150"});
    const result=await api(`/tracking?${params}`);trackingResult=result;
    const source=result.source||{},fresh=source.fetched_at?new Date(source.fetched_at).toLocaleString():"timestamp unavailable";
    $("tracking-source").querySelector("span").innerHTML=`<b>${escapeHTML(source.status||'unknown')} · ${escapeHTML(source.endpoint||'official feed')}</b><br>${escapeHTML(result.count)} displayed of ${escapeHTML(source.upstream_rows??0)} upstream rows · fetched ${escapeHTML(fresh)}${source.stale?' · stale cache':''}`;
    const definitions=Object.entries(result.definitions||{}).map(([key,value])=>`<div class="context-tile"><b>${escapeHTML(key.replaceAll('_',' '))}</b><span>${escapeHTML(value)}</span></div>`).join('');
    $("tracking-definitions").innerHTML=`<div class="subhead"><h3>${escapeHTML(result.label)} definitions</h3><span>${escapeHTML(result.scope)} · ${escapeHTML(result.season)} · ${escapeHTML(result.minimum_games)}+ GAMES</span></div><div class="context-grid">${definitions}</div><p class="analytics-note">Schema audit: ${(source.schema_audit?.available||[]).length} expected fields available${source.schema_audit?.missing?.length?` · unavailable upstream: ${source.schema_audit.missing.map(value=>escapeHTML(value)).join(', ')}`:''}.</p>`;
    if(source.status==="unavailable"||!result.records?.length){output.innerHTML=`<div class="panel empty-state"><div><h3>${source.status==="unavailable"?'Upstream category unavailable':'No qualified rows'}</h3><p>${escapeHTML(source.detail||'Try a lower games threshold or a different category.')}</p></div></div>`;return;}
    const metrics=result.available_metrics||Object.keys(result.definitions||{}),pct=new Set(result.percentage_metrics||[]),favorites=loadFavorites(),scope=result.scope;
    const identity=row=>scope==="player"?{id:row.PLAYER_ID,name:row.PLAYER_NAME,team:row.TEAM_ABBREVIATION}:{id:row.TEAM_ID,name:row.TEAM_NAME,team:row.TEAM_ABBREVIATION};
    const template=`36px minmax(160px,1.3fr) 55px repeat(${metrics.length},minmax(76px,1fr))`;
    const header=`<div class="tracking-row header" role="row" style="grid-template-columns:${template}"><span role="columnheader">Save</span><span role="columnheader">${scope==="player"?'Player':'Team'}</span><span role="columnheader">GP</span>${metrics.map(metric=>`<span role="columnheader" title="${escapeHTML(result.definitions[metric])}">${escapeHTML(metric.replaceAll('_',' '))}</span>`).join('')}</div>`;
    const rows=result.records.map(row=>{const item=identity(row),key=`${scope}:${item.id}`,saved=favorites.includes(key),games=row.GP??row.G??'—';return `<div class="tracking-row" role="row" style="grid-template-columns:${template}"><span role="cell"><button class="favorite-toggle ${saved?'saved':''}" data-favorite="${escapeHTML(key)}" aria-pressed="${saved}" aria-label="${saved?'Remove':'Save'} ${escapeHTML(item.name)} favorite">★</button></span><b role="cell">${escapeHTML(item.name)}<small style="display:block;color:var(--muted-2)">${escapeHTML(item.team)}</small></b><span role="cell">${escapeHTML(games)}</span>${metrics.map(metric=>`<span role="cell">${row[metric]==null?'—':pct.has(metric)?`${fmt(Number(row[metric])*100,1)}%`:fmt(row[metric],2)}</span>`).join('')}</div>`;}).join('');
    output.innerHTML=`<div class="tracking-table" role="table" aria-label="${escapeHTML(result.label)}">${header}${rows}</div>`;
    const filterQuery=new URLSearchParams({tracking_category:result.category,tracking_scope:result.scope,tracking_season:result.season,tracking_team:$("tracking-team").value,tracking_min_games:$("tracking-min-games").value||"0",tracking_query:$("tracking-query").value.trim()});history.replaceState(null,"",`${location.pathname}?${filterQuery}#tracking`);
    const seen=localStorage.getItem(TRACKING_SEEN_KEY),alerts=localStorage.getItem(ALERTS_KEY)==="enabled";if(alerts&&"Notification" in window&&seen&&source.fetched_at&&seen!==source.fetched_at&&favorites.length&&Notification.permission==="granted")new Notification("NBA tracking data refreshed",{body:`${result.label} has new cached data for your saved players and teams.`});if(source.fetched_at)localStorage.setItem(TRACKING_SEEN_KEY,source.fetched_at);
  }catch(error){output.innerHTML=`<div class="panel empty-state"><div><h3>Tracking feed unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="tracking">Retry tracking data</button></div></div>`;}
}
$("tracking-go").addEventListener("click",loadTracking);
$("tracking-category").addEventListener("change",loadTracking);
$("tracking-scope").addEventListener("change",loadTracking);
$("tracking-output").addEventListener("click",event=>{const button=event.target.closest("[data-favorite]");if(!button)return;let favorites=loadFavorites(),key=button.dataset.favorite;if(favorites.includes(key))favorites=favorites.filter(value=>value!==key);else favorites.push(key);saveFavorites(favorites);button.classList.toggle("saved",favorites.includes(key));button.setAttribute("aria-pressed",String(favorites.includes(key)));button.setAttribute("aria-label",`${favorites.includes(key)?'Remove':'Save'} favorite`);});
$("tracking-share").addEventListener("click",async event=>{const url=trackingResult?.share_url?new URL(trackingResult.share_url,location.origin).href:location.href;try{await navigator.clipboard.writeText(url);event.currentTarget.textContent="Link copied";}catch{prompt("Copy this filtered tracking link",url);}});
$("tracking-notifications").addEventListener("click",async event=>{if(!("Notification" in window)){event.currentTarget.textContent="Notifications unsupported";return;}const permission=await Notification.requestPermission();if(permission==="granted"){localStorage.setItem(ALERTS_KEY,"enabled");event.currentTarget.textContent="Local alerts enabled";}else{localStorage.removeItem(ALERTS_KEY);event.currentTarget.textContent="Alerts not enabled";}});

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
document.addEventListener("click",event=>{
  const retry=event.target.closest("[data-retry]");
  if(!retry)return;
  if(retry.dataset.retry==="pulse"){pulseLoaded=false;loadPulse();}
  if(retry.dataset.retry==="explore")loadExplore();
  if(retry.dataset.retry==="team")$("team-pick").dispatchEvent(new Event("change"));
  if(retry.dataset.retry==="tracking")loadTracking();
  if(retry.dataset.retry==="games"){gameData=null;loadGames();}
  if(retry.dataset.retry==="outlook"){forecastLoadedFor=null;loadSeasonForecast(true);}
});

function gameFlowSVG(story) {
  const points=story.timeline||[];
  if(!points.length)return '<p class="analytics-note">Timeline data is unavailable.</p>';
  const width=700,height=260,pad=34,maxElapsed=Math.max(...points.map(point=>Number(point.ELAPSED)||0),1);
  const x=point=>pad+(Number(point.ELAPSED)||0)/maxElapsed*(width-pad*2);
  const y=point=>height-pad-(Number(point.HOME_WIN_PROB)||0)*(height-pad*2);
  const path=points.map((point,index)=>`${index?'L':'M'} ${x(point).toFixed(1)} ${y(point).toFixed(1)}`).join(' ');
  const quarters=[1,2,3].map(q=>{const qx=pad+q*720/maxElapsed*(width-pad*2);return qx<width-pad?`<line x1="${qx}" y1="${pad}" x2="${qx}" y2="${height-pad}" stroke="#2a3039" stroke-dasharray="3 5"/>`:'';}).join('');
  return `<svg class="game-flow-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Home win probability by game time"><line x1="${pad}" y1="${height/2}" x2="${width-pad}" y2="${height/2}" stroke="#343c46"/>${quarters}<text x="6" y="${pad+4}" fill="#979da8" font-size="10">100%</text><text x="12" y="${height/2+4}" fill="#979da8" font-size="10">50%</text><text x="18" y="${height-pad+4}" fill="#979da8" font-size="10">0%</text><path d="${path}" fill="none" stroke="#ff5c35" stroke-width="4" stroke-linejoin="round"/><circle cx="${x(points.at(-1))}" cy="${y(points.at(-1))}" r="6" fill="#c7ff4a"/></svg>`;
}

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
  return `<div class="game-story-grid"><section class="panel game-story-card wide"><div class="subhead"><h3>Game flow</h3><span>HOME WIN PROBABILITY</span></div>${gameFlowSVG(story)}<p class="analytics-note">${escapeHTML(story.win_probability_method)}</p></section><section class="panel game-story-card"><div class="subhead"><h3>Turning points</h3><span>LARGEST PROBABILITY SWINGS</span></div><div class="game-story-list">${turns||'<p class="analytics-note">No score changes were cached.</p>'}</div></section><section class="panel game-story-card"><div class="subhead"><h3>Game context</h3><span>RUNS · CLUTCH</span></div><div class="context-grid"><div class="context-tile"><b>${escapeHTML(story.biggest_runs?.[story.away]??'—')}</b><span>${escapeHTML(story.away)} biggest run</span></div><div class="context-tile"><b>${escapeHTML(story.biggest_runs?.[story.home]??'—')}</b><span>${escapeHTML(story.home)} biggest run</span></div><div class="context-tile"><b>${escapeHTML(story.lead_changes)}</b><span>Lead changes</span></div><div class="context-tile"><b>${escapeHTML(story.clutch_points?.[story.away]??0)}–${escapeHTML(story.clutch_points?.[story.home]??0)}</b><span>Clutch pts · away–home</span></div></div></section><section class="panel game-story-card"><div class="subhead"><h3>Shot profile</h3><span>${chart?'LOCATION CACHE':'SUMMARY ONLY'}</span></div>${chart||'<p class="analytics-note">Shot coordinates are not present in this older cache. Shot-type totals remain available below.</p>'}<div style="margin-top:14px">${shotSummary||'<p class="analytics-note">Shot events are unavailable.</p>'}</div></section><section class="panel game-story-card"><div class="subhead"><h3>Top lineups</h3><span>ON-COURT STINTS</span></div>${lineups||'<p class="analytics-note">Rotation data is not cached for this game, so lineup stints cannot be reconstructed.</p>'}</section><section class="panel game-story-card wide"><div class="subhead"><h3>Advanced team box</h3><span>EFFICIENCY · POSSESSION CONTEXT</span></div><div class="split-table"><div class="advanced-row header"><span>Team</span><span>PTS</span><span>eFG%</span><span>TS%</span><span>TOV%</span><span>FT rate</span><span>AST/TO</span><span>OREB</span><span>REB</span></div>${advanced}</div></section><section class="panel game-story-card wide"><div class="subhead"><h3>Latest events</h3><span>PLAY-BY-PLAY FEED</span></div><div class="game-story-list">${feed||'<p class="analytics-note">Detailed events are unavailable.</p>'}</div></section></div>`;
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
    box=`<section class="team-sections panel" style="margin-top:12px"><div class="subhead"><h3>Full box score</h3><span>${escapeHTML(result.source.replaceAll("_"," "))} · GAME ${escapeHTML(result.game_id)}</span></div>${Object.entries(result.teams).map(([team,players])=>`<div class="team-section"><div class="subhead"><h3>${escapeHTML(team)}</h3><span>PLAYER TOTALS</span></div><div class="split-table"><div class="split-row header"><span>Player</span><span>MIN</span><span>PTS</span><span>REB</span><span>AST</span><span>STL</span><span>BLK</span><span>TO</span><span>FG</span></div>${players.map(player=>`<div class="split-row"><b>${escapeHTML(player.PLAYER)}</b><span>${fmt(player.MIN)}</span><span>${escapeHTML(player.PTS)}</span><span>${escapeHTML(player.REB)}</span><span>${escapeHTML(player.AST)}</span><span>${escapeHTML(player.STL)}</span><span>${escapeHTML(player.BLK)}</span><span>${escapeHTML(player.TO)}</span><span>${escapeHTML(player.FG)}</span></div>`).join("")}</div></div>`).join("")}</section>`;
  }else{box=`<section class="panel panel-pad" style="margin-top:12px"><h3>Player box score unavailable</h3><p class="error">${escapeHTML(boxResult.reason.message)}</p><p class="analytics-note">The score and game summary above remain available. NBA box-score data may not yet be cached or the upstream endpoint may be temporarily unavailable.</p></section>`;}
  const story=storyResult.status==="fulfilled"?renderGameStory(storyResult.value):`<section class="panel panel-pad" style="margin-top:12px"><h3>Game story unavailable</h3><p class="error">${escapeHTML(storyResult.reason.message)}</p><p class="analytics-note">Timeline analysis requires cached play-by-play data.</p></section>`;
  output.innerHTML=summary+story+box;
});

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
const compareProfileColors = ["#ff5c35", "#7ab8ff", "#c7ff4a", "#c58cff"];
function renderCompareProfile(names, percentiles) {
  const eligible = names.filter(name => compareProfileMetrics.filter(([stat]) =>
    Number.isFinite(Number(percentiles?.[name]?.[stat]))).length >= 3);
  if (eligible.length < 2) return `<section class="compare-visual"><div class="subhead"><h3>At-a-glance profile</h3><span>CURRENT SEASON</span></div><p class="analytics-note">The normalized visual needs at least two active players with a qualifying current-season sample. Exact career and season values remain below.</p></section>`;
  const metrics = compareProfileMetrics.filter(([stat]) => eligible.every(name =>
    Number.isFinite(Number(percentiles[name][stat]))));
  if (metrics.length < 3) return "";
  const width=640,height=470,cx=320,cy=224,radius=158,labelRadius=195;
  const point=(index,value,r=radius)=>{const angle=-Math.PI/2+index*2*Math.PI/metrics.length;
    return [cx+Math.cos(angle)*r*value/100,cy+Math.sin(angle)*r*value/100];};
  const points=value=>metrics.map((_,index)=>point(index,value).map(number=>number.toFixed(1)).join(",")).join(" ");
  const leaders=Object.fromEntries(eligible.map(name=>[name,0]));
  metrics.forEach(([stat])=>{const best=Math.max(...eligible.map(name=>Number(percentiles[name][stat])));
    eligible.forEach(name=>{if(Number(percentiles[name][stat])===best)leaders[name]++;});});
  const grid=[25,50,75,100].map(level=>`<polygon points="${points(level)}" fill="none" stroke="#303741" stroke-width="1"/><text x="${cx+4}" y="${(cy-radius*level/100+4).toFixed(1)}" fill="#6f7681" font-size="9">${level}</text>`).join("");
  const axes=metrics.map(([stat,label],index)=>{const [x,y]=point(index,100),[lx,ly]=point(index,100,labelRadius),anchor=lx<cx-12?"end":lx>cx+12?"start":"middle";
    return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#303741"/><text x="${lx.toFixed(1)}" y="${(ly+4).toFixed(1)}" text-anchor="${anchor}" fill="#979da8" font-size="11">${escapeHTML(label)}</text>`;}).join("");
  const profiles=eligible.map((name,index)=>{const color=compareProfileColors[index],values=metrics.map(([stat])=>Number(percentiles[name][stat])),shape=values.map((value,metric)=>point(metric,value).map(number=>number.toFixed(1)).join(",")).join(" ");
    return `<g><polygon points="${shape}" fill="${color}" fill-opacity=".07" stroke="${color}" stroke-width="3" stroke-linejoin="round"/>${values.map((value,metric)=>{const [x,y]=point(metric,value);return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="${color}"><title>${escapeHTML(name)} · ${escapeHTML(metrics[metric][1])}: ${Math.round(value)}th percentile</title></circle>`;}).join("")}</g>`;}).join("");
  const legend=eligible.map((name,index)=>{const average=metrics.reduce((sum,[stat])=>sum+Number(percentiles[name][stat]),0)/metrics.length;
    return `<div class="compare-profile-key"><i style="background:${compareProfileColors[index]}"></i><b>${escapeHTML(name)}</b><span>${Math.round(average)} avg<br>${leaders[name]} lead${leaders[name]===1?"":"s"}</span></div>`;}).join("");
  const excluded=names.filter(name=>!eligible.includes(name));
  return `<section class="compare-visual"><div class="subhead"><div><div class="panel-kicker">Normalized on one honest scale</div><h3>At-a-glance skill profile</h3></div><span>LEAGUE PERCENTILE · HIGHER IS BETTER</span></div><svg class="compare-profile-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="League percentile profile comparison for ${eligible.map(escapeHTML).join(", ")}"><title>Current-season league percentile comparison</title>${grid}${axes}${profiles}</svg><div class="compare-profile-legend">${legend}</div><p class="analytics-note">Shape shows current-season league percentile, not raw totals or position-adjusted value. Exact numbers are below.${excluded.length?` No qualifying percentile shape for ${excluded.map(escapeHTML).join(", ")}.`:""}</p></section>`;
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
    const grid=`120px repeat(${names.length},1fr)`;
    const careerStats=[...new Set(names.flatMap(name=>Object.keys(result.career?.[name]||{})))];
    const careerRows=careerStats.map(stat=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${escapeHTML(stat.replaceAll("_"," "))}</label>${names.map(name=>`<span>${result.career?.[name]?.[stat]==null?"—":fmt(result.career[name][stat],stat==="GP"?0:2)}</span>`).join("")}</div>`).join("");
    const pctStats=[...new Set(names.flatMap(name=>Object.keys(result.percentiles?.[name]||{})))];
    const pctRows=pctStats.map(stat=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${escapeHTML(stat.replaceAll("_"," "))}</label>${names.map(name=>`<span>${result.percentiles?.[name]?.[stat]==null?"—":fmt(result.percentiles[name][stat],0)+"th"}</span>`).join("")}</div>`).join("");
    const qualityRows=[["XEFG","Shot diet (xeFG%)"],["EFG","Actual eFG%"],["MAKING","Shot making"]].map(([stat,label])=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${label}</label>${names.map(name=>`<span>${result.shot_quality?.[name]?.[stat]==null?"—":`${Number(result.shot_quality[name][stat])>=0&&stat==="MAKING"?"+":""}${fmt(Number(result.shot_quality[name][stat])*100,1)}`}</span>`).join("")}</div>`).join("");
    const seasonRows=[...new Set(names.flatMap(name=>(result.career_seasons?.[name]||[]).map(row=>row.SEASON_ID)))].sort().reverse().map(season=>`<div class="compare-table-row" style="grid-template-columns:${grid}"><label>${escapeHTML(season)}</label>${names.map(name=>{const row=(result.career_seasons?.[name]||[]).find(item=>item.SEASON_ID===season);return `<span>${row?fmt(row.PTS):"—"}</span>`;}).join("")}</div>`).join("");
    const currentRows=body?body.replaceAll('class="compare-table-row"',`class="compare-table-row" style="grid-template-columns:${grid}"`):'<p class="analytics-note">Current-season stats require every selected player to be active.</p>';
    const posterLink=result.poster_png?`<a class="btn btn-primary" style="margin-top:24px" href="${escapeHTML(result.poster_png)}" target="_blank" rel="noopener">Download comparison poster ↗</a>`:"";
    $("compare-output").innerHTML = `<div class="compare-head" style="grid-template-columns:${grid}"><div class="panel-kicker">${escapeHTML(result.season)}</div>${names.map(name=>`<div>${escapeHTML(name)}</div>`).join("")}</div>${renderCompareProfile(names,result.percentiles)}<div class="subhead" style="margin-top:22px"><h3>Current season</h3><span>PER GAME</span></div>${currentRows}<div class="subhead" style="margin-top:28px"><h3>Career averages</h3><span>VOLUME-WEIGHTED</span></div>${careerRows}<div class="subhead" style="margin-top:28px"><h3>Season by season</h3><span>POINTS PER GAME</span></div>${seasonRows}<div class="subhead" style="margin-top:28px"><h3>League percentiles</h3><span>CURRENT SEASON</span></div>${pctRows||'<p class="analytics-note">Requires every player active this season.</p>'}<div class="subhead" style="margin-top:28px"><h3>Shot quality</h3><span>EXPECTED VS ACTUAL</span></div>${qualityRows}${posterLink}`;
  } catch (error) { $("compare-output").innerHTML = `<div class="empty-state" style="min-height:280px"><div><h3>Comparison unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div></div>`; }
});

let teamOptionsCache = null;
async function loadTeamOptions(){
  if(!teamOptionsCache)teamOptionsCache=await api("/teams");
  return teamOptionsCache;
}
let teamPickerLoaded = false;
async function loadTeamPicker() {
  if (teamPickerLoaded) return;
  try {
    const teams = pulseData?.team_form?.map(row => row.team) || await loadTeamOptions();
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
    const finances = result.finances ? `<section class="team-section"><div class="subhead"><h3>Payroll & contract book</h3><span>LOCAL-ONLY · ${money(result.finances.payroll)}</span></div><div class="split-table"><div class="split-row header"><span>Player</span>${result.finances.seasons.map(year=>`<span>${escapeHTML(year)}</span>`).join("")}</div>${result.finances.contracts.map(player=>`<div class="split-row"><b>${escapeHTML(player.PLAYER_NAME)}</b>${result.finances.seasons.map(year=>`<span>${money(player[year])}</span>`).join("")}</div>`).join("")}</div><p class="analytics-note">Current and future commitments from the weekly local salary cache.</p></section>` : "";
    $("roster-panel").innerHTML = `<div class="team-sections">${result.scouting_take?`<div class="scouting-card">${escapeHTML(result.scouting_take)}</div>`:""}<section><div class="subhead"><h3>Roster</h3><span>${result.record.wins}-${result.record.losses} · ${escapeHTML(result.season)}</span></div><div role="table" aria-label="${escapeHTML(team)} roster statistics">${head}${rows}</div></section><section class="team-section"><div class="subhead"><h3>Four factors</h3><span>VALUE · LEAGUE RANK</span></div><div class="factor-grid">${factors}</div></section><section class="team-section"><div class="subhead"><h3>Recent games</h3><span>LAST 10</span></div>${recent||'<p class="analytics-note">Recent games unavailable.</p>'}</section><section class="team-section"><div class="subhead"><h3>Five-man lineups</h3><span>MOST USED</span></div>${lineups||'<p class="analytics-note">Lineup data unavailable.</p>'}</section><section class="team-section"><div class="subhead"><h3>On / off impact</h3><span>100+ MINUTES</span></div>${impact||'<p class="analytics-note">On/off data unavailable.</p>'}</section>${finances}<section class="team-section"><div class="subhead"><h3>Conference standings</h3><span>SEASON TO DATE</span></div><div class="standings-grid">${standings}</div></section></div>`;
  } catch (error) { $("roster-panel").innerHTML = `<div class="empty-state" style="min-height:330px"><div><h3>Team unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="team">Retry team</button></div></div>`; }
});
$("roster-panel").addEventListener("click",event=>{
  const player=event.target.closest("[data-player-id]");
  if(player)openPlayerProfile(Number(player.dataset.playerId),player.dataset.playerName);
});

let teamsLoaded = false;
let sharedMatchupRun = false;
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
    mountChart($("outlook-playoff-chart"),{
      title:"Playoff probability",
      takeaway:"The 50% guide separates likely qualifiers from teams whose postseason case remains fragile.",
      description:`All teams · ${Number(result.n_sims).toLocaleString()} simulations.`,
      plotFactory:probabilityPlot(allTeams,"Playoff","PLAYOFF_PROB"),
    });
    mountChart($("outlook-title-chart"),{
      title:"Championship probability",
      takeaway:`${result.favorites.championship.team} leads the title field, but the full distribution shows how concentrated that edge is.`,
      description:`Model probability, not betting odds · ${result.basis_season} basis.`,
      plotFactory:probabilityPlot(allTeams,"NBA title","CHAMP_PROB","#ff5c35"),
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
      tableHTML:`<div class="forecast-conferences">${cupGroups}</div>`,
      dataLabel:"View group and knockout probabilities",
    });
    forecastLoadedFor=season;
  }catch(error){output.innerHTML=`<div class="empty-state" style="min-height:260px"><div><h3>Season forecast unavailable</h3><p class="error">${escapeHTML(error.message)}</p><button class="btn" data-retry="outlook">Retry projection</button></div></div>`;}
}
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
$("prediction-season").addEventListener("change",event=>{const upcoming=event.target.selectedIndex>0;$("prediction-basis-note").textContent=upcoming?`${event.target.value} is a preseason projection using ${metaData.current_season} team form and rosters. It will move to season-to-date inputs once the new season begins.`:"Uses live season-to-date team form, availability assumptions, carried-over Elo, and home court.";});
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
  if(metaData&&season===metaData.current_season){scenarioRoster=[];syncScenarioPlayers();$("scenario-output").innerHTML='<p class="analytics-note">Scenario Lab uses the next-season roster forecast. Select the preseason projection above.</p>';return;}
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
  const driverTable=drivers?`<div aria-label="Exact model driver contributions">${drivers}</div>`:"";
  output.innerHTML=`<div class="subhead"><div><div class="panel-kicker">${escapeHTML(result.season)} · data through ${escapeHTML(result.sample.as_of)}</div><h3>${escapeHTML(away)} at ${escapeHTML(home)} · full comparison</h3></div><div class="comparison-actions"><button class="btn" id="comparison-share">Copy share link</button><button class="btn" id="comparison-export">Export JSON</button></div></div><p class="analytics-note">${escapeHTML(result.sample.definition)} · ${escapeHTML(away)} ${escapeHTML(result.sample.games[away])} games · ${escapeHTML(home)} ${escapeHTML(result.sample.games[home])} games.</p><div class="viz-legend"><span><i class="away"></i>${escapeHTML(away)}</span><span><i></i>${escapeHTML(home)}</span></div><div class="viz-grid" style="margin-top:14px"><div id="matchup-rank-chart"></div><div id="matchup-driver-chart"></div></div><div class="rotation-grid">${rotation(away)}${rotation(home)}</div><div class="context-grid"><div class="context-tile"><b>${escapeHTML(h2h.first_wins??0)}–${escapeHTML(h2h.second_wins??0)}</b><span>${escapeHTML(away)}–${escapeHTML(home)} head to head</span></div><div class="context-tile"><b>${h2h.first_average_margin==null?'—':`${Number(h2h.first_average_margin)>=0?'+':''}${fmt(h2h.first_average_margin)}`}</b><span>${escapeHTML(away)} average margin</span></div><div class="context-tile"><b>${fmt(Number(result.home_win_prob)*100,0)}%</b><span>${escapeHTML(home)} model probability</span></div><div class="context-tile"><b>${escapeHTML(result.basis_season)}</b><span>Model data basis</span></div></div><ul class="limitations">${(result.limitations||[]).map(item=>`<li>${escapeHTML(item)}</li>`).join("")}</ul>`;
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
    takeaway:`Orange steps move the forecast toward ${home}; blue steps move it toward ${away}.`,
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

let methodologyLoaded=false;
async function loadMethodology(){if(methodologyLoaded)return;try{const result=await api("/methodology"),metrics=result.metrics||{};const journeyMax=Math.max(...result.journey.map(row=>row.accuracy));$("methodology-output").innerHTML=`<div class="method-grid"><article class="panel method-card"><h3>Evaluation protocol</h3><p>${escapeHTML(result.evaluation.protocol)}</p><p>${escapeHTML(result.evaluation.leakage)}</p><p><b>Decision metrics:</b> ${result.evaluation.decision_metrics.map(escapeHTML).join(" · ")}</p></article><article class="panel method-card"><h3>Artifact record</h3><div class="context-grid" style="grid-template-columns:1fr 1fr"><div class="context-tile"><b>${metrics.outcome?fmt(Number(metrics.outcome.accuracy)*100,1)+"%":"—"}</b><span>Outcome accuracy</span></div><div class="context-tile"><b>${metrics.outcome?fmt(metrics.outcome.log_loss,3):"—"}</b><span>Outcome log loss</span></div><div class="context-tile"><b>${metrics.points?fmt(metrics.points.mae,2):"—"}</b><span>Points MAE</span></div><div class="context-tile"><b>${metrics.points?fmt(Number(metrics.points.interval_coverage)*100,1)+"%":"—"}</b><span>80% interval coverage</span></div></div></article><article class="panel method-card"><h3>Modeling journey</h3>${result.journey.map(row=>`<div class="pct-row"><label>${escapeHTML(row.stage)}</label><div class="track"><div class="fill" style="width:${row.accuracy/journeyMax*100}%"></div></div><b>${fmt(row.accuracy,1)}%</b></div>`).join("")}</article><article class="panel method-card"><h3>Models served</h3>${Object.entries(result.models).map(([name,text])=>`<h4>${escapeHTML(name)}</h4><p>${escapeHTML(text)}</p>`).join("")}</article><article class="panel method-card" style="grid-column:1/-1"><h3>What did not win</h3><p>${result.rejected.map(escapeHTML).join(" · ")}</p><p>Rejected ideas remain documented so the reported gains retain context.</p></article></div>`;methodologyLoaded=true;}catch(error){$("methodology-output").innerHTML=`<div class="panel empty-state"><p class="error">${escapeHTML(error.message)}</p></div>`;}}

const loadMethodologyBase=loadMethodology;
loadMethodology=async()=>{await loadMethodologyBase();if($("model-registry-card"))return;try{const result=await api("/methodology/registry"),models=result.models||{},backtest=result.season_backtest?.metrics||{},components=result.season_backtest?.component_validation||{},grid=$("methodology-output").querySelector(".method-grid");if(!grid)return;const cutoff=value=>value&&typeof value==="object"?Object.entries(value).map(([season,date])=>`${season}: ${date}`).join(" · "):(value||"—");const registry=`<article class="panel method-card" id="model-registry-card" style="grid-column:1/-1"><h3>Model registry</h3><div class="forecast-conferences">${Object.entries(models).map(([name,model])=>`<div class="result-card"><div class="panel-kicker">${escapeHTML(model.version)}</div><h4>${escapeHTML(name.replaceAll("_"," "))}</h4><p><b>${escapeHTML(model.kind)}</b><br>${escapeHTML(model.status)}</p><p class="analytics-note">Data cutoff: ${escapeHTML(cutoff(model.data_cutoff))}${model.roster_overlay?`<br>Roster overlay: ${escapeHTML(model.roster_overlay.status)}`:''}</p></div>`).join("")}</div></article>`;const record=backtest.record||{},playoffs=backtest.playoffs||{},champ=backtest.championship||{},cup=backtest.nba_cup||{};const validation=`<article class="panel method-card" style="grid-column:1/-1"><h3>Season forecast backtest</h3>${backtest.team_seasons?`<p>${escapeHTML(backtest.season_count)} seasons · ${escapeHTML(backtest.team_seasons)} team-seasons. Lower error is better.</p><div class="context-grid"><div class="context-tile"><b>${fmt(record.mae,2)}</b><span>Record MAE vs ${fmt(record.baseline_mae,2)} baseline</span></div><div class="context-tile"><b>${fmt(playoffs.brier,3)}</b><span>Playoff Brier vs ${fmt(playoffs.baseline_brier,3)}</span></div><div class="context-tile"><b>${fmt(champ.brier,3)}</b><span>Title Brier vs ${fmt(champ.baseline_brier,3)}</span></div><div class="context-tile"><b>${fmt(cup.brier,3)}</b><span>Cup Brier vs ${fmt(cup.baseline_brier,3)}</span></div></div><div style="margin-top:18px">${(playoffs.calibration||[]).map(row=>`<div class="pct-row"><label>${fmt(Number(row.lower)*100,0)}–${fmt(Number(row.upper)*100,0)}% (${row.count})</label><div class="track"><div class="fill" style="width:${Number(row.observed_rate)*100}%"></div></div><b>${fmt(Number(row.mean_probability)*100,0)}% / ${fmt(Number(row.observed_rate)*100,0)}%</b></div>`).join("")}</div><p class="analytics-note">Calibration rows show mean forecast / observed rate. Record and playoff forecasts currently edge their simple baselines; title and Cup results do not yet beat uniform baselines.${components.roster_overlay?` Roster overlay: ${escapeHTML(components.roster_overlay.status)} — ${escapeHTML(components.roster_overlay.reason)}`:''}</p>`:'<p class="analytics-note">Backtest artifact missing. Run uv run python -m nba_insights.ml.backtest.</p>'}</article>`;grid.insertAdjacentHTML("beforeend",registry+validation);}catch(error){console.warn("model registry unavailable",error);}};

$("ask-go").addEventListener("click",async()=>{const question=$("ask-question").value.trim(),output=$("ask-output");if(question.length<3){output.innerHTML='<div class="answer error">Enter a basketball question.</div>';return;}output.innerHTML='<div class="empty-state" style="min-height:330px"><div class="loading">QUERYING THE LEAGUE TABLE…</div></div>';try{const response=await fetch("/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question})});if(!response.ok){let message=response.statusText;try{message=(await response.json()).detail||message;}catch{}throw new Error(message);}const result=await response.json();output.innerHTML=`<div class="answer">${escapeHTML(result.answer)}<p class="analytics-note">${escapeHTML(result.season)} · ${escapeHTML(result.model)} · verify anything important</p></div>`;}catch(error){output.innerHTML=`<div class="answer"><h3>AI answer unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div>`;}});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").then(registration=>registration.update());
