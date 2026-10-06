// Tracking + hustle: official tracking feeds, leaderboards, favorites, alerts.
import { $, api, escapeHTML, fmt } from "../core.js";
import { dataTable } from "../render.js";
import { loadMeta } from "../meta.js";
import { registerPage, registerRetry } from "../router.js";
import {
  leaderboardPlot,
  metricScatterPlot,
  mountChart,
} from "../visualizations.js";

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
    const numeric=metrics.filter(metric=>result.records.some(row=>Number.isFinite(Number(row[metric])))),metricOptions=selected=>numeric.map(metric=>`<option value="${escapeHTML(metric)}" ${metric===selected?"selected":""}>${escapeHTML(metric.replaceAll('_',' '))}</option>`).join('');
    const controls=numeric.length?`<div class="viz-control-row"><div class="control"><label for="tracking-metric">Rank by</label><div class="select-wrap"><select id="tracking-metric">${metricOptions(numeric[0])}</select></div></div>${numeric.length>1?`<div class="control"><label for="tracking-versus">Compare against</label><div class="select-wrap"><select id="tracking-versus">${metricOptions(numeric[1])}</select></div></div>`:''}</div><div class="viz-grid"><div id="tracking-leader-chart"></div><div id="tracking-scatter-chart"></div></div>`:'';
    output.innerHTML=`<div class="visual-output">${controls}<div class="tracking-table" role="table" aria-label="${escapeHTML(result.label)}">${header}${rows}</div></div>`;
    if(numeric.length){
      const nameKey=scope==="player"?"PLAYER_NAME":"TEAM_NAME",noun=scope==="player"?"players":"teams";
      const trackingValue=(metric,value)=>value==null?"—":pct.has(metric)?`${fmt(Number(value)*100,1)}%`:fmt(value,2);
      const renderTrackingCharts=()=>{
        const key=$("tracking-metric").value,versus=$("tracking-versus")?.value,label=key.replaceAll('_',' ');
        const ranked=[...result.records].filter(row=>Number.isFinite(Number(row[key]))).sort((a,b)=>Number(b[key])-Number(a[key])),leader=ranked[0];
        mountChart($("tracking-leader-chart"),{
          title:`${label} leaders`,
          takeaway:`${leader?.[nameKey]??"—"} leads the filtered ${noun}. ${result.definitions?.[key]||""}`,
          description:`${result.season} · ${result.minimum_games}+ games · top 15 of ${result.count} ${noun} shown${pct.has(key)?" · percentage":""}.`,
          plotFactory:leaderboardPlot(result.records,{key,label,nameKey,percent:pct.has(key)}),
          tableHTML:dataTable(`${label} by ${scope}`,[scope==="player"?"Player":"Team","Team",label],ranked.map(row=>[row[nameKey],row.TEAM_ABBREVIATION||"—",trackingValue(key,row[key])])),
          dataLabel:`View all ${ranked.length} ranked ${noun}`,
        });
        if(versus&&versus!==key)mountChart($("tracking-scatter-chart"),{
          title:`${label} vs ${versus.replaceAll('_',' ')}`,
          takeaway:`Upper-right ${noun} are above the sample average on both measures; the labelled points lead on ${label}.`,
          description:`${result.count} ${noun} · grey lines mark the filtered-sample average.`,
          plotFactory:metricScatterPlot(result.records,{xKey:versus,yKey:key,xLabel:versus.replaceAll('_',' '),yLabel:label,nameKey,xPercent:pct.has(versus),yPercent:pct.has(key)}),
          tableHTML:dataTable(`${label} and ${versus.replaceAll('_',' ')} by ${scope}`,[scope==="player"?"Player":"Team",label,versus.replaceAll('_',' ')],ranked.filter(row=>Number.isFinite(Number(row[versus]))).map(row=>[row[nameKey],trackingValue(key,row[key]),trackingValue(versus,row[versus])])),
          dataLabel:"View both measures for every row",
        });
        else $("tracking-scatter-chart").innerHTML=numeric.length<2?'':'<div class="data-figure"><div class="figure-heading"><h4>Choose a second measure</h4><p>Pick a different "Compare against" metric to see how the two relate.</p></div></div>';
      };
      $("tracking-metric").addEventListener("change",renderTrackingCharts);
      $("tracking-versus")?.addEventListener("change",renderTrackingCharts);
      renderTrackingCharts();
    }
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

registerPage("tracking", loadTracking);
registerRetry("tracking", loadTracking);
