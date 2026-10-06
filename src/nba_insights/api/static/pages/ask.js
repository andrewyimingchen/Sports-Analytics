// Ask the league: optional constrained AI Q&A.
import { $, escapeHTML } from "../core.js";
import { loadMeta } from "../meta.js";
import { registerPage } from "../router.js";

$("ask-go").addEventListener("click",async()=>{const question=$("ask-question").value.trim(),output=$("ask-output");if(question.length<3){output.innerHTML='<div class="answer error">Enter a basketball question.</div>';return;}output.innerHTML='<div class="empty-state" style="min-height:330px"><div class="loading">QUERYING THE LEAGUE TABLE…</div></div>';try{const response=await fetch("/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question})});if(!response.ok){let message=response.statusText;try{message=(await response.json()).detail||message;}catch{/* keep the HTTP status text */}throw new Error(message);}const result=await response.json();output.innerHTML=`<div class="answer">${escapeHTML(result.answer)}<p class="analytics-note">${escapeHTML(result.season)} · ${escapeHTML(result.model)} · verify anything important</p></div>`;}catch(error){output.innerHTML=`<div class="answer"><h3>AI answer unavailable</h3><p class="error">${escapeHTML(error.message)}</p></div>`;}});

registerPage("ask", loadMeta);
