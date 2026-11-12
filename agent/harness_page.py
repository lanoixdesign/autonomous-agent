"""The harness single-page UI (served at /). Plain HTML + JS, no external resources."""

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
 .st.error,.st.cancelled,.st.stopped{background:#f7d4d4}
 .agent{margin:3px 0;padding:4px 6px;border-left:3px solid #4062bb;background:#f7f8fa}
 .agent small{color:#5a6270} pre{white-space:pre-wrap;word-break:break-word;margin:4px 0;font-size:12px}
 #events{max-height:55vh;overflow:auto;font:12px/1.35 ui-monospace,monospace}
 .ev{border-bottom:1px solid #eef0f2;padding:2px 0} .ev b{color:#4062bb}
 .ap{border:1px solid #f0c36d;background:#fffaf0;border-radius:6px;padding:6px;margin-bottom:8px}
 .ap .who{font-weight:600} .muted{color:#8a919c}
</style></head><body>
<header><h1>autonomous-agent · harness</h1>
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
 <section><h2>Pending approvals</h2><div id="approvals" class="muted">None.</div></section>
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
setInterval(refresh, 1000); refresh();
</script></body></html>
"""
