"""The harness compact dashboard (served at /dashboard; the chat page is harness_chat.py). Plain HTML + JS, no external resources."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>autonomous-agent harness</title>
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
 .st.error,.st.cancelled,.st.stopped,.st.interrupted{background:#f7d4d4}
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
</style></head><body>
<header><h1>autonomous-agent · harness <a href="/" style="color:#9fb4ff;font-size:12px">chat</a></h1>
 <button id="stopall" title="Cancel every task, deny every pending approval, pause schedules">⛔ Stop all</button>
 <label>token <input id="token" type="password" placeholder="AGENT_HARNESS_TOKEN (if set)"></label></header>
<main>
 <section><h2>New task</h2>
  <textarea id="task" placeholder="Describe the task"></textarea>
  <p><button id="launch">Launch</button> <span id="msg" class="muted"></span></p>
  <h2>Tasks</h2><div id="tasks"></div></section>
 <section><h2>Agent tree <span id="cur" class="muted"></span>
   <button id="cancel" style="float:right;display:none">Cancel task</button></h2>
  <div id="tree" class="muted">Select a task.</div>
  <h2 style="margin-top:12px">Result</h2><pre id="result" class="muted">—</pre>
  <h2>Event log</h2><div id="events"></div></section>
 <section><h2>Pending approvals</h2><div id="approvals" class="muted">None.</div>
  <h2 style="margin-top:14px">API keys &amp; quotas</h2><div id="keys" class="muted">single-key (.env) mode</div></section>
 <section style="grid-column:1 / 3"><h2>Usage — tokens, cost, steps per conversation and per agent</h2><div id="usage" class="muted">—</div></section>
 <section><h2>Scheduled tasks</h2>
  <div class="row"><input id="sprompt" type="text" placeholder="Prompt to run"></div>
  <div class="row"><select id="skind"><option value="every">every N minutes</option><option value="daily">daily at HH:MM</option></select>
   <input id="swhen" type="text" placeholder="60 or 08:30" style="width:90px"><button id="sadd">Add</button></div>
  <div id="schedules" class="muted">None.</div>
  <h2 style="margin-top:14px">Remembered approval rules</h2><div id="rules" class="muted">None.</div>
  <h2 style="margin-top:14px">Health</h2><pre id="health" class="muted">—</pre></section>
</main>
<script>
const $ = id => document.getElementById(id);
const tok = $("token"); tok.value = sessionStorage.getItem("harnessToken") || "";
tok.onchange = () => sessionStorage.setItem("harnessToken", tok.value);
let cur = null, since = 0;
function el(tag, cls, text){const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e;}
async function api(method, path, body){
  const h = {"Content-Type":"application/json"}; if(tok.value) h["Authorization"]="Bearer "+tok.value;
  const r = await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error || r.status); return j;
}
$("launch").onclick = async () => {
  const t = $("task").value.trim(); if(!t) return;
  try { const r = await api("POST","/tasks",{task:t}); $("task").value=""; $("msg").textContent="started "+r.id; select(r.id); }
  catch(e){ $("msg").textContent = "error: "+e.message; }
};
$("cancel").onclick = async () => { if(cur) try{ await api("POST","/tasks/"+cur+"/cancel",{}); }catch(e){} };
function select(id){ cur=id; since=0; $("events").replaceChildren(); refresh(); }
function badge(s){ return el("span","st "+s,s); }
async function refreshTasks(){
  const {tasks} = await api("GET","/tasks"); const box=$("tasks"); box.replaceChildren();
  tasks.slice().reverse().forEach(t => { const d=el("div","task"+(t.id===cur?" sel":""));
    d.append(el("span",null,t.task.slice(0,60)), badge(t.status)); d.onclick=()=>select(t.id); box.append(d); });
}
async function refreshTask(){
  if(!cur) return; const t = await api("GET","/tasks/"+cur);
  $("cur").textContent = "· "+t.id; $("cancel").style.display = ["queued","running","cancelling"].includes(t.status) ? "" : "none";
  const tree=$("tree"); tree.className=""; tree.replaceChildren();
  t.agents.forEach(a => { const d=el("div","agent"); d.style.marginLeft=(a.depth*18)+"px";
    d.append(el("b",null,a.id), badge(a.status||"?"), el("div",null,a.task||""));
    if(a.answer) d.append(el("small",null,"→ "+String(a.answer).slice(0,300))); tree.append(d); });
  $("result").textContent = t.result==null ? "—" : "["+t.stop_reason+"] "+t.result;
  const ev = await api("GET","/tasks/"+cur+"/events?since="+since); since = ev.next;
  const box=$("events"); ev.events.forEach(e => { const d=el("div","ev");
    const who = e.agent ? "["+e.agent+"] " : ""; let txt;
    if(e.kind==="audit") txt = e.event ? e.event+(e.child?" "+e.child:"")+(e.stop_reason?" "+e.stop_reason:"")
                          : (e.tool+" ["+(e.category||"")+"] "+e.decision+(e.error?" error: "+e.error:""));
    else if(e.kind==="message") txt = (e.final?"answer: ":"")+e.content;
    else if(e.kind==="approval") txt = "approval "+e.tool+": "+e.status;
    else txt = e.kind+" "+(e.status||e.reason||"");
    d.append(el("span","muted",e.ts.slice(11,19)+" "), el("b",null,who), el("span",null,txt)); box.append(d); });
  if(ev.events.length) box.scrollTop = box.scrollHeight;
}
async function refreshApprovals(){
  const {approvals} = await api("GET","/approvals"); const box=$("approvals"); box.replaceChildren();
  box.className = approvals.length ? "" : "muted"; if(!approvals.length) box.textContent="None.";
  approvals.forEach(a => { const d=el("div","ap");
    d.append(el("div","who","agent "+a.agent+" · task "+a.task), el("div",null,a.tool+" ["+a.category+"]"),
             el("pre",null,JSON.stringify(a.args,null,1)), el("div","muted",a.reason));
    const ok=el("button",null,"Approve"), no=el("button",null,"Deny");
    ok.onclick=()=>api("POST","/approvals/"+a.id,{decision:"approve"}).then(refreshApprovals).catch(()=>{});
    no.onclick=()=>api("POST","/approvals/"+a.id,{decision:"deny"}).then(refreshApprovals).catch(()=>{});
    d.append(ok, document.createTextNode(" "), no); box.append(d); });
}
async function refresh(){ try{ await refreshTasks(); await refreshTask(); await refreshApprovals(); $("msg").textContent=""; }
  catch(e){ $("msg").textContent = "error: "+e.message; } }
async function refreshKeys(){
  let st; try{ st=await api("GET","/keys"); }catch(e){ return; }
  const box=$("keys"); if(!st.keys.length) return; box.className=""; box.replaceChildren();
  st.keys.forEach(k=>{ const d=el("div","ap"); d.append(el("div","who",k.name+"  "+k.key+(k.available?"":"  (not set)")+(k.cooldown_s?"  cooldown "+k.cooldown_s+"s":"")),
      el("div","muted",k.categories.join(", ")+" · priority "+k.priority));
    Object.entries(k.limits).forEach(([f,v])=>d.append(el("div",null,f+": "+v.used+" / "+v.limit+" (left "+v.remaining+")"))); box.append(d); });
}
function money(v){ return (v||0).toFixed(4); }
async function refreshUsage(){
  let u; try{ u=await api("GET","/usage"); }catch(e){ return; }
  const box=$("usage"); box.className=""; const tb=el("table"), hd=el("tr");
  ["conversation / agent","turns","steps","tool calls","tokens","cost","own steps","own tokens","own cost"].forEach(h=>hd.append(el("th",null,h))); tb.append(hd);
  const row=(cls,cells)=>{ const tr=el("tr",cls); cells.forEach((c,i)=>tr.append(el("td",i===0?"l":null,String(c)))); tb.append(tr); };
  u.conversations.slice().reverse().forEach(c=>{
    row("conv",[c.id+" · "+c.task.slice(0,50)+(c.source!=="chat"?" ["+c.source+"]":""),c.turns,c.total.steps,c.total.tool_calls,c.total.tokens,money(c.total.cost),"","",""]);
    c.agents.forEach(a=>row(null,["\u00a0\u00a0".repeat(a.id.split(".").length)+a.id,"",a.steps,a.tool_calls,a.tokens,money(a.cost),a.own.steps,a.own.tokens,money(a.own.cost)])); });
  row("conv",["total","",u.total.steps,u.total.tool_calls,u.total.tokens,money(u.total.cost),"","",""]);
  box.replaceChildren(tb);
}
$("sadd").onclick=async()=>{ const prompt=$("sprompt").value.trim(), w=$("swhen").value.trim(); if(!prompt||!w) return;
  const body=$("skind").value==="every" ? {prompt, every_minutes:Number(w)} : {prompt, daily_at:w};
  try{ await api("POST","/schedules",body); $("sprompt").value=$("swhen").value=""; refreshSchedules(); }catch(e){ $("msg").textContent="error: "+e.message; } };
async function refreshSchedules(){
  let r; try{ r=await api("GET","/schedules"); }catch(e){ return; }
  const box=$("schedules"); box.className=r.schedules.length?"":"muted"; box.replaceChildren(); if(!r.schedules.length) box.textContent="None.";
  r.schedules.forEach(s=>{ const d=el("div","sched"+(s.enabled?"":" off"));
    d.append(el("div",null,s.prompt.slice(0,120)), el("div","muted",s.when+" · next "+new Date(s.next_run*1000).toLocaleString()+" · runs "+s.runs+(s.skipped?" · skipped "+s.skipped:"")+(s.last_task?" · last "+s.last_task:"")));
    const t=el("button",null,s.enabled?"Disable":"Enable"), n=el("button",null,"Run now"), x=el("button",null,"Delete");
    t.onclick=()=>api("POST","/schedules/"+s.id,{enabled:!s.enabled}).then(refreshSchedules).catch(()=>{});
    n.onclick=()=>api("POST","/schedules/"+s.id+"/run",{}).then(refreshSchedules).catch(()=>{});
    x.onclick=()=>{ if(confirm("Delete this schedule?")) api("POST","/schedules/"+s.id+"/delete",{}).then(refreshSchedules).catch(()=>{}); };
    const b=el("div","row"); b.append(t,n,x); d.append(b); box.append(d); });
}
async function refreshRules(){
  let r; try{ r=await api("GET","/rules"); }catch(e){ return; }
  const box=$("rules"); box.className=r.rules.length?"":"muted"; box.replaceChildren(); if(!r.rules.length) box.textContent="None. ("+r.never_remembered.join(", ")+" are never remembered)";
  r.rules.forEach(x=>{ const d=el("div","row"); const b=el("button",null,"Revoke");
    b.onclick=()=>api("POST","/rules/"+x.id+"/revoke",{}).then(refreshRules).catch(()=>{});
    d.append(el("span",null,x.tool+" ["+x.category+"] · "+x.scope+(x.scope==="conversation"?" "+x.task_id:"")+" · used "+x.uses), b); box.append(d); });
}
async function refreshHealth(){ try{ const h=await api("GET","/health"); $("health").className="";
  $("health").textContent=h.status+" · up "+Math.round(h.uptime_s)+"s · running "+h.running+"/"+h.max_tasks+" · approvals "+h.pending_approvals+
    "\nkeys: "+h.keys.mode+(h.keys.keys?" "+h.keys.keys.map(k=>k.name+" "+k.key).join(", "):(h.keys.key?" "+h.keys.provider+" "+h.keys.key:""))+
    "\npersistence: "+(h.persistence||"off (memory only)"); }catch(e){} }
$("stopall").onclick=async()=>{ if(!confirm("Emergency stop: cancel EVERY task, deny every pending approval and pause all schedules?")) return;
  try{ const r=await api("POST","/stop-all",{disable_schedules:true}); $("msg").textContent="stopped "+r.cancelled.length+" task(s), denied "+r.approvals_denied.length+" approval(s)"; refresh(); refreshSchedules(); }
  catch(e){ $("msg").textContent="error: "+e.message; } };
function slow(){ refreshKeys(); refreshUsage(); refreshSchedules(); refreshRules(); refreshHealth(); }
setInterval(refresh, 1000); refresh(); setInterval(slow, 5000); slow();
</script></body></html>
"""
