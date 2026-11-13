"""The harness compact dashboard (served at /dashboard; the chat page is harness_chat.py).
Plain HTML + JS, no external resources. Bilingual (EN/FR): strings come from agent/i18n.py."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="dash.pageTitle">autonomous-agent harness</title>
<style>
 body{font:14px/1.4 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1d2127}
 header{background:#1d2127;color:#fff;padding:10px 16px;display:flex;gap:12px;align-items:center}
 header h1{font-size:16px;margin:0;flex:1} header input{width:220px}
 main{display:grid;grid-template-columns:320px 1fr 360px;gap:12px;padding:12px}
 section{background:#fff;border:1px solid #dde1e6;border-radius:8px;padding:10px;min-width:0}
 h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#5a6270;margin:0 0 8px}
 textarea{width:100%;box-sizing:border-box;min-height:80px} button{cursor:pointer}
 .task{padding:6px;border-radius:6px;cursor:pointer;border:1px solid transparent}
 .task:hover{background:#f0f2f5} .task.sel{border-color:#4062bb;background:#eef2fb}
 .st{font-size:11px;padding:1px 6px;border-radius:9px;background:#e4e7eb;margin-left:4px}
 .st.running,.st.queued,.st.cancelling{background:#fff0c2} .st.done{background:#d3f2dc}
 .st.error,.st.cancelled,.st.stopped,.st.interrupted,.st.denied,.st.expired{background:#f7d4d4}
 .agent{margin:3px 0;padding:4px 6px;border-left:3px solid #4062bb;background:#f7f8fa}
 .agent small{color:#5a6270} pre{white-space:pre-wrap;word-break:break-word;margin:4px 0;font-size:12px}
 #events{max-height:55vh;overflow:auto;font:12px/1.35 ui-monospace,monospace}
 .ev{border-bottom:1px solid #eef0f2;padding:2px 0} .ev b{color:#4062bb}
 .ap{border:1px solid #f0c36d;background:#fffaf0;border-radius:6px;padding:6px;margin-bottom:8px}
 .ap .who{font-weight:600} .muted{color:#8a919c}
 table{border-collapse:collapse;width:100%;font-size:12px} td,th{padding:3px 6px;border-bottom:1px solid #eef0f2;text-align:right}
 td:first-child,th:first-child,td.l,th.l{text-align:left} tr.conv td{background:#f3f5f9;font-weight:600}
 #stopall{background:#7a0f0a;color:#fff;border:0;border-radius:6px;padding:6px 12px;font-weight:700}
 .row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0} .row input[type=text]{flex:1;min-width:120px}
 .sched{border:1px solid #dde1e6;border-radius:6px;padding:6px;margin:6px 0} .off{opacity:.55}
/*LANG_CSS*/
 #lang{border-color:#5a6270}
 header a.c{color:#9fb4ff;font-size:12px}
 @media (max-width:900px){
  header{flex-wrap:wrap;padding:10px 12px;padding-top:max(10px,env(safe-area-inset-top))}
  header h1{flex:1 1 100%} header label{flex:1 1 100%;display:flex;flex-direction:column;gap:4px;align-items:stretch;white-space:normal;font-size:12px} header input{width:100%;box-sizing:border-box;min-width:0;font-size:16px;padding:6px}
  main{grid-template-columns:1fr;padding:8px;gap:8px} section{grid-column:auto!important}
  #events{max-height:40vh} table{display:block;overflow-x:auto;white-space:nowrap}
  button{min-height:40px;padding:6px 12px} .ap button{min-width:44%;min-height:44px;font-size:15px}
  textarea,input[type=text],select{font-size:16px}
 }
</style></head><body>
<header><h1><span data-i18n="dash.heading"></span> <a href="/" class="c" data-i18n="link.chat"></a> <a href="/connect" class="c" data-i18n="chat.connect"></a></h1>
 /*LANG_SWITCH*/
 <button id="stopall" data-i18n="btn.stopall" data-i18n-title="title.stopall"></button>
 <label><span data-i18n="token.label"></span> <input id="token" type="password" data-i18n-placeholder="token.placeholder"></label></header>
<main>
 <section><h2 data-i18n="dash.newTask"></h2>
  <textarea id="task" data-i18n-placeholder="dash.taskPlaceholder"></textarea>
  <p><button id="launch" data-i18n="dash.launch"></button> <span id="msg" class="muted"></span></p>
  <h2 data-i18n="dash.tasks"></h2><div id="tasks"></div></section>
 <section><h2><span data-i18n="dash.tree"></span> <span id="cur" class="muted"></span>
   <button id="cancel" style="float:right;display:none" data-i18n="dash.cancel"></button></h2>
  <div id="tree" class="muted" data-i18n="dash.selectTask"></div>
  <h2 style="margin-top:12px" data-i18n="dash.result"></h2><pre id="result" class="muted">—</pre>
  <h2 data-i18n="dash.events"></h2><div id="events"></div></section>
 <section><h2 data-i18n="dash.approvals"></h2><div id="approvals" class="muted"></div>
  <h2 style="margin-top:14px" data-i18n="dash.keys"></h2><div id="keys" class="muted" data-i18n="dash.singleKey"></div></section>
 <section style="grid-column:1 / 3"><h2 data-i18n="dash.usage"></h2><div id="usage" class="muted">—</div></section>
 <section><h2 data-i18n="sched.title"></h2>
  <div class="row"><input id="sprompt" type="text" data-i18n-placeholder="sched.prompt"></div>
  <div class="row"><select id="skind"><option value="every" data-i18n="sched.every"></option><option value="daily" data-i18n="sched.daily"></option></select>
   <input id="swhen" type="text" data-i18n-placeholder="sched.whenPh" style="width:90px"><button id="sadd" data-i18n="sched.add"></button></div>
  <div id="schedules" class="muted"></div>
  <h2 style="margin-top:14px" data-i18n="rules.title"></h2><div id="rules" class="muted"></div>
  <h2 style="margin-top:14px" data-i18n="health.title"></h2><pre id="health" class="muted">—</pre></section>
</main>
<script>
/*I18N_JS*/
const $ = id => document.getElementById(id);
const tok = $("token"); tok.value = sessionStorage.getItem("harnessToken") || "";
tok.onchange = () => sessionStorage.setItem("harnessToken", tok.value);
fetch("/auth/status").then(r=>r.json()).then(s=>{ if(s.required && !s.authenticated && !tok.value) location.replace("/connect"); }).catch(()=>{});
let cur = null, since = 0, evcache = [];
function el(tag, cls, text){const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e;}
function fail(e){ $("msg").textContent = t("err.prefix",{msg:e.message}); }
async function api(method, path, body){
  const h = {"Content-Type":"application/json"}; if(tok.value) h["Authorization"]="Bearer "+tok.value;
  const r = await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error || r.status); return j;
}
function num(v,d){ return (v||0).toLocaleString(LANG,{maximumFractionDigits:d,minimumFractionDigits:0}); }
$("launch").onclick = async () => {
  const x = $("task").value.trim(); if(!x) return;
  try { const r = await api("POST","/tasks",{task:x}); $("task").value=""; $("msg").textContent=t("dash.started",{id:r.id}); select(r.id); }
  catch(e){ fail(e); }
};
$("cancel").onclick = async () => { if(cur) try{ await api("POST","/tasks/"+cur+"/cancel",{}); }catch(e){} };
function select(id){ cur=id; since=0; evcache=[]; $("events").replaceChildren(); refresh(); }
function badge(s){ return el("span","st "+s,tr("status",s)); }
async function refreshTasks(){
  const {tasks} = await api("GET","/tasks"); const box=$("tasks"); box.replaceChildren();
  tasks.slice().reverse().forEach(x => { const d=el("div","task"+(x.id===cur?" sel":""));
    d.append(el("span",null,x.task.slice(0,60)), badge(x.status)); d.onclick=()=>select(x.id); box.append(d); });
}
function evLine(e){
  const d=el("div","ev"), who = e.agent ? "["+e.agent+"] " : ""; let txt;
  if(e.kind==="audit") txt = e.event ? e.event+(e.child?" "+e.child:"")+(e.stop_reason?" "+tr("status",e.stop_reason):"")
                        : (e.tool+" ["+(e.category?tr("cat",e.category):"")+"] "+tr("decision",e.decision)+(e.error?t("ev.error",{error:e.error}):""));
  else if(e.kind==="message") txt = (e.final?t("ev.answer"):"")+e.content;
  else if(e.kind==="approval") txt = t("ev.approval",{tool:e.tool,status:tr("status",e.status)});
  else txt = e.kind+" "+(e.status?tr("status",e.status):(e.reason?tr("status",e.reason):""));
  d.append(el("span","muted",e.ts.slice(11,19)+" "), el("b",null,who), el("span",null,txt)); return d;
}
async function refreshTask(){
  if(!cur) return; const x = await api("GET","/tasks/"+cur);
  $("cur").textContent = "· "+x.id; $("cancel").style.display = ["queued","running","cancelling"].includes(x.status) ? "" : "none";
  const tree=$("tree"); tree.className=""; tree.removeAttribute("data-i18n"); tree.replaceChildren();
  x.agents.forEach(a => { const d=el("div","agent"); d.style.marginLeft=(a.depth*18)+"px";
    d.append(el("b",null,a.id), badge(a.status||"?"), el("div",null,a.task||""));
    if(a.answer) d.append(el("small",null,"→ "+String(a.answer).slice(0,300))); tree.append(d); });
  $("result").textContent = x.result==null ? "—" : "["+tr("status",x.stop_reason)+"] "+x.result;
  const ev = await api("GET","/tasks/"+cur+"/events?since="+since); since = ev.next; evcache.push(...ev.events);
  const box=$("events"); ev.events.forEach(e => box.append(evLine(e)));
  if(ev.events.length) box.scrollTop = box.scrollHeight;
}
async function refreshApprovals(){
  const {approvals} = await api("GET","/approvals"); const box=$("approvals"); box.replaceChildren();
  box.className = approvals.length ? "" : "muted"; if(!approvals.length) box.textContent=t("dash.none");
  approvals.forEach(a => { const d=el("div","ap");
    d.append(el("div","who",t("dash.agentTask",{agent:a.agent,task:a.task})), el("div",null,a.tool+" ["+tr("cat",a.category)+"]"),
             el("pre",null,JSON.stringify(a.args,null,1)), el("div","muted",a.reason));
    const ok=el("button",null,t("card.approve")), no=el("button",null,t("card.deny"));
    ok.onclick=()=>api("POST","/approvals/"+a.id,{decision:"approve"}).then(refreshApprovals).catch(()=>{});
    no.onclick=()=>api("POST","/approvals/"+a.id,{decision:"deny"}).then(refreshApprovals).catch(()=>{});
    d.append(ok, document.createTextNode(" "), no); box.append(d); });
}
async function refresh(){ try{ await refreshTasks(); await refreshTask(); await refreshApprovals(); $("msg").textContent=""; }
  catch(e){ fail(e); } }
async function refreshKeys(){
  let st; try{ st=await api("GET","/keys"); }catch(e){ return; }
  const box=$("keys"); if(!st.keys.length) return; box.className=""; box.removeAttribute("data-i18n"); box.replaceChildren();
  st.keys.forEach(k=>{ const d=el("div","ap"); d.append(el("div","who",k.name+"  "+k.key+(k.available?"":t("dash.keyNotSet"))+(k.cooldown_s?t("dash.keyCooldown",{s:k.cooldown_s}):"")),
      el("div","muted",t("quota.priority",{categories:k.categories.join(", "),p:k.priority})));
    Object.entries(k.limits).forEach(([f,v])=>d.append(el("div",null,t("dash.limitLine",{limit:tr("limit",f),used:num(v.used,4),max:num(v.limit,4),left:num(v.remaining,4)})))); box.append(d); });
}
function money(v){ return num(v,4); }
async function refreshUsage(){
  let u; try{ u=await api("GET","/usage"); }catch(e){ return; }
  const box=$("usage"); box.className=""; const tb=el("table"), hd=el("tr");
  ["usage.agent","usage.turns","usage.steps","usage.toolCalls","usage.tokens","usage.cost","usage.ownSteps","usage.ownTokens","usage.ownCost"].forEach(h=>hd.append(el("th",null,t(h)))); tb.append(hd);
  const row=(cls,cells)=>{ const tr_=el("tr",cls); cells.forEach((c,i)=>tr_.append(el("td",i===0?"l":null,String(c)))); tb.append(tr_); };
  u.conversations.slice().reverse().forEach(c=>{
    row("conv",[c.id+" · "+c.task.slice(0,50)+(c.source!=="chat"?" ["+c.source+"]":""),c.turns,num(c.total.steps,0),num(c.total.tool_calls,0),num(c.total.tokens,0),money(c.total.cost),"","",""]);
    c.agents.forEach(a=>row(null,["\u00a0\u00a0".repeat(a.id.split(".").length)+a.id,"",num(a.steps,0),num(a.tool_calls,0),num(a.tokens,0),money(a.cost),num(a.own.steps,0),num(a.own.tokens,0),money(a.own.cost)])); });
  row("conv",[t("usage.total"),"",num(u.total.steps,0),num(u.total.tool_calls,0),num(u.total.tokens,0),money(u.total.cost),"","",""]);
  box.replaceChildren(tb);
}
$("sadd").onclick=async()=>{ const prompt=$("sprompt").value.trim(), w=$("swhen").value.trim(); if(!prompt||!w) return;
  const body=$("skind").value==="every" ? {prompt, every_minutes:Number(w.replace(",","."))} : {prompt, daily_at:w};
  try{ await api("POST","/schedules",body); $("sprompt").value=$("swhen").value=""; refreshSchedules(); }catch(e){ fail(e); } };
function when(s){ return s.kind==="interval" ? t("sched.everyN",{n:num(s.every_minutes,2)}) : t("sched.dailyAt",{at:s.at}); }
async function refreshSchedules(){
  let r; try{ r=await api("GET","/schedules"); }catch(e){ return; }
  const box=$("schedules"); box.className=r.schedules.length?"":"muted"; box.replaceChildren(); if(!r.schedules.length) box.textContent=t("dash.none");
  r.schedules.forEach(s=>{ const d=el("div","sched"+(s.enabled?"":" off"));
    const info=[when(s), t("sched.next",{date:new Date(s.next_run*1000).toLocaleString(LANG)}), t("sched.runs",{n:s.runs})];
    if(s.skipped) info.push(t("sched.skipped",{n:s.skipped})); if(s.last_task) info.push(t("sched.last",{id:s.last_task}));
    d.append(el("div",null,s.prompt.slice(0,120)), el("div","muted",info.join(" · ")));
    const tg=el("button",null,t(s.enabled?"sched.disable":"sched.enable")), n=el("button",null,t("sched.runNow")), x=el("button",null,t("sched.delete"));
    tg.onclick=()=>api("POST","/schedules/"+s.id,{enabled:!s.enabled}).then(refreshSchedules).catch(()=>{});
    n.onclick=()=>api("POST","/schedules/"+s.id+"/run",{}).then(refreshSchedules).catch(()=>{});
    x.onclick=()=>{ if(confirm(t("sched.confirmDelete"))) api("POST","/schedules/"+s.id+"/delete",{}).then(refreshSchedules).catch(()=>{}); };
    const b=el("div","row"); b.append(tg,n,x); d.append(b); box.append(d); });
}
async function refreshRules(){
  let r; try{ r=await api("GET","/rules"); }catch(e){ return; }
  const box=$("rules"); box.className=r.rules.length?"":"muted"; box.replaceChildren();
  if(!r.rules.length) box.textContent=t("rules.none",{cats:r.never_remembered.map(c=>tr("cat",c)).join(", ")});
  r.rules.forEach(x=>{ const d=el("div","row"); const b=el("button",null,t("rules.revoke"));
    b.onclick=()=>api("POST","/rules/"+x.id+"/revoke",{}).then(refreshRules).catch(()=>{});
    d.append(el("span",null,x.tool+" ["+tr("cat",x.category)+"] · "+tr("scope",x.scope)+(x.scope==="conversation"?" "+x.task_id:"")+" · "+t("rules.used",{n:x.uses})), b); box.append(d); });
}
async function refreshHealth(){ try{ const h=await api("GET","/health"); $("health").className="";
  const keys = t(h.keys.mode==="router"?"keys.mode.router":"keys.mode.single")+(h.keys.keys?" "+h.keys.keys.map(k=>k.name+" "+k.key).join(", "):(h.keys.key?" "+h.keys.provider+" "+h.keys.key:""));
  $("health").textContent=[t("health.line",{status:tr("status",h.status),up:num(Math.round(h.uptime_s),0),running:h.running,max:h.max_tasks,approvals:h.pending_approvals}),
    t("health.keys",{keys}), t("health.persistence",{p:h.persistence||t("health.memoryOnly")})].join("\n"); }catch(e){} }
$("stopall").onclick=async()=>{ if(!confirm(t("confirm.stopall"))) return;
  try{ const r=await api("POST","/stop-all",{disable_schedules:true});
    $("msg").textContent=t("msg.stopped",{tasks:r.cancelled.length,approvals:r.approvals_denied.length,schedules:r.schedules_paused.length}); refresh(); refreshSchedules(); }
  catch(e){ fail(e); } };
function slow(){ refreshKeys(); refreshUsage(); refreshSchedules(); refreshRules(); refreshHealth(); }
onLang = () => { const box=$("events"); box.replaceChildren(...evcache.map(evLine)); refresh(); slow(); };
setInterval(refresh, 1000); refresh(); setInterval(slow, 5000); slow();
</script></body></html>
"""
PAGE = PAGE.replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", LANG_SWITCH).replace("/*I18N_JS*/", I18N_JS)
