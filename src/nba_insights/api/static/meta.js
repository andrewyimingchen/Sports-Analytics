// Shared app metadata: seasons, capabilities, connection status, team list.
import { $, api, escapeHTML } from "./core.js";

let metaData = null;
let metaRequest = null;

/** The server's season list and capabilities, fetched once (concurrent callers share it). */
export function loadMeta(){
  if(!metaRequest){
    metaRequest=fetchMeta().catch(error=>{
      metaRequest=null; // let the next caller retry
      updateConnectionStatus(true);
      throw error;
    });
  }
  return metaRequest;
}

async function fetchMeta(){
  metaData=await api("/meta");
  const options=metaData.seasons.map(season=>`<option value="${escapeHTML(season)}">${escapeHTML(season)}</option>`).join("");
  ["pulse-season","explore-season","games-season","tracking-season"].forEach(id=>{if($(id))$(id).innerHTML=options;});
  const forecastOptions=(metaData.prediction_seasons||[metaData.current_season]).map((season,index)=>`<option value="${escapeHTML(season)}" ${index?"selected":""}>${escapeHTML(season)}${index?" · preseason projection":""}</option>`).join("");
  ["prediction-season","outlook-season"].forEach(id=>{if($(id))$(id).innerHTML=forecastOptions;});
  const askEnabled=Boolean(metaData.capabilities?.ask_ai);
  $("more-ask").classList.toggle("hidden",!askEnabled);
  if(!askEnabled){
    $("ask-go").disabled=true;
    $("ask-output").innerHTML='<div class="empty-state" style="min-height:330px"><div><h2>Ask AI is not configured</h2><p>This optional tool appears when the server has the Anthropic package and credential. All non-AI analytics remain available.</p></div></div>';
  }
  updateConnectionStatus();
  return metaData;
}

export function updateConnectionStatus(failed=false){
  if(!navigator.onLine){
    $("app-status").innerHTML='<i class="live-dot offline"></i> Offline · showing saved data when available';
  }else if(metaData){
    $("app-status").innerHTML=`<i class="live-dot"></i> ${escapeHTML(metaData.current_season)} data available`;
  }else if(failed){
    $("app-status").innerHTML='<i class="live-dot offline"></i> League data unavailable · retrying on next view';
  }
}
window.addEventListener("online",()=>{updateConnectionStatus();if(!metaData)loadMeta().catch(()=>{});});
window.addEventListener("offline",()=>updateConnectionStatus());

let teamOptionsCache = null;
export async function loadTeamOptions(){
  if(!teamOptionsCache)teamOptionsCache=await api("/teams");
  return teamOptionsCache;
}

/** The loaded /meta payload, or null before loadMeta() resolves. */
export const currentMeta = () => metaData;
