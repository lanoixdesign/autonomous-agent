"""The harness chat page (served at / and /chat). Plain HTML + JS, no external resources, polling."""

CHAT_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>autonomous-agent · chat</title>
<style>
 *{box-sizing:border-box} body{margin:0;font:14px/1.45 system-ui,sans-serif;color:#1d2127;background:#f4f5f7;height:100vh;display:flex}
 aside{width:260px;background:#1d2127;color:#e8eaee;display:flex;flex-direction:column}
 aside h1{font-size:15px;margin:14px 14px 8px} aside button.new{margin:0 12px 10px;padding:8px;border:0;border-radius:6px;background:#4062bb;color:#fff;cursor:pointer}
 #convs{flex:1;overflow:auto} .conv{padding:8px 14px;cursor:pointer;border-left:3px solid transparent}
 .conv:hover{background:#2a2f37} .conv.sel{background:#2f3540;border-left-color:#7e9cff}
 .conv .t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .conv small{color:#9aa3b0}
 aside footer{padding:10px 12px;font-size:12px;color:#9aa3b0} aside footer input{width:100%;margin-top:4px}
 aside footer a{color:#9fb4ff}
 main{flex:1;display:flex;flex-direction:column;min-width:0}
 #top{padding:10px 16px;border-bottom:1px solid #dde1e6;background:#fff;display:flex;gap:10px;align-items:center}
 #title{flex:1;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 #log{flex:1;overflow:auto;padding:16px 18px 24px}
 .row{display:flex;margin:6px 0} .row.user{justify-content:flex-end}
 .bubble{max-width:72%;padding:8px 12px;border-radius:12px;background:#fff;border:1px solid #e1e4e8;white-space:pre-wrap;word-break:break-word}
 .user .bubble{background:#4062bb;color:#fff;border-color:#4062bb}
 .bubble.final{border-color:#7fc79a;background:#f2fbf5}
 .who{display:inline-block;font:600 11px ui-monospace,monospace;padding:1px 6px;border-radius:8px;background:#e7ecfa;color:#2f4aa0;margin-bottom:3px}
 .d1 .who{background:#e9f6ef;color:#1f7a45} .d2 .who{background:#fbf0e3;color:#9a5a12} .d3 .who{background:#f6e8f4;color:#8a2c7c}
 .step{font:12px/1.4 ui-monospace,monospace;color:#5a6270;margin:3px 0 3px 8px}
 .step.deny,.step.err{color:#b3261e} .step.spawn{color:#2f4aa0} .step.merge{color:#1f7a45} .step.conflict{color:#b3261e;font-weight:600}
 .step details{display:inline} .step summary{cursor:pointer;display:inline}
 .sys{text-align:center;color:#8a919c;font-size:12px;margin:8px 0}
 #composer{display:flex;gap:8px;padding:10px 16px;border-top:1px solid #dde1e6;background:#fff}
 #composer textarea{flex:1;resize:none;height:56px;padding:8px;border-radius:8px;border:1px solid #cfd4da;font:inherit}
 #composer button,#top button{padding:0 16px;border:0;border-radius:8px;background:#4062bb;color:#fff;cursor:pointer}
 #top button{padding:6px 12px;background:#b3261e}
 .badge{font-size:11px;padding:1px 7px;border-radius:9px;background:#e4e7eb;color:#333}
 .badge.running,.badge.queued,.badge.cancelling{background:#fff0c2} .badge.done{background:#d3f2dc}
 .badge.error,.badge.cancelled,.badge.stopped{background:#f7d4d4}
 #err{color:#b3261e;font-size:12px;padding:0 16px}
 #attach{background:#e7ecfa!important;color:#2f4aa0!important;font-size:18px;padding:0 12px!important}
 #chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px} #chips:not(:empty){padding:8px 16px 0;background:#fff;border-top:1px solid #dde1e6}
 .chip{display:inline-flex;align-items:center;gap:6px;background:#eef1f6;border:1px solid #d6dbe3;border-radius:14px;padding:3px 6px 3px 10px;font-size:12px}
 .chip.bad{background:#fbe3e1;border-color:#f0b4ae} .chip button{border:0;background:none;cursor:pointer;font-size:14px;color:#5a6270;padding:0 2px}
 .atts{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px} .att{font-size:12px;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.4);border-radius:10px;padding:1px 8px}
 #drop{display:none;position:absolute;inset:0;background:rgba(64,98,187,.12);border:3px dashed #4062bb;border-radius:12px;z-index:5;
   align-items:center;justify-content:center;font-size:18px;color:#2f4aa0;font-weight:600;pointer-events:none}
 main.dragging #drop{display:flex} main{position:relative}
 #popups{position:fixed;right:16px;top:56px;width:380px;max-height:calc(100vh - 150px);overflow:auto;display:flex;flex-direction:column;gap:10px;z-index:10}
 .card{background:#fff;border:2px solid #f0a73a;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.18);padding:10px 12px;animation:pop .15s ease-out}
 @keyframes pop{from{transform:translateY(8px);opacity:0}to{transform:none;opacity:1}}
 .card h3{margin:0 0 4px;font-size:13px} .card .meta{font-size:12px;color:#5a6270}
 .card pre{background:#f6f7f9;border-radius:6px;padding:6px;max-height:160px;overflow:auto;font-size:11.5px;white-space:pre-wrap;word-break:break-word}
 .card .cat{font-weight:600;text-transform:uppercase;font-size:11px;padding:1px 6px;border-radius:6px;background:#fdecd2;color:#8a4b00}
 .card .cat.send,.card .cat.spend,.card .cat.execute{background:#fbd9d6;color:#9a1d14}
 .card .btns{display:flex;gap:8px;margin-top:6px} .card button{flex:1;padding:7px;border:0;border-radius:6px;cursor:pointer;font-weight:600}
 .card .ok{background:#1f7a45;color:#fff} .card .no{background:#e4e7eb}
</style></head><body>
<aside><h1>autonomous-agent</h1>
 <button class="new" id="new">+ New conversation</button>
 <div id="convs"></div>
 <footer>token (if AGENT_HARNESS_TOKEN is set)<input id="token" type="password">
  <div style="margin-top:6px"><a href="/dashboard">dashboard</a></div></footer></aside>
<main>
 <div id="top"><span id="title">New conversation</span><span id="status"></span>
  <button id="cancel" style="display:none">Stop</button></div>
 <div id="log"><div class="sys">Type a task below. Sub-agents appear as root.1, root.2… Approvals pop up top-right.</div></div>
 <div id="err"></div>
 <div id="chips"></div>
 <div id="composer"><button id="attach" title="Attach files (or drop them here)">📎</button>
  <input id="files" type="file" multiple hidden>
  <textarea id="input" placeholder="Message (Enter to send, Shift+Enter for a new line) — drop files to attach"></textarea>
  <button id="send">Send</button></div>
 <div id="drop">Drop files to attach</div>
</main>
<div id="popups"></div>
<script>
const $ = id => document.getElementById(id);
const tok = $("token"); tok.value = sessionStorage.getItem("harnessToken") || "";
tok.onchange = () => { sessionStorage.setItem("harnessToken", tok.value); loadConfig(); };
let cur = location.hash.slice(1) || null, tasks = [];
const cache = {};            // task id -> {since, events: []}
const answering = new Set(); // approval ids being answered
if(cur) cache[cur]={since:0,events:[]};
function pick(id){ cur=id; history.replaceState(null,"",id?"#"+id:location.pathname); if(id) cache[id]=cache[id]||{since:0,events:[]}; render(); poll(); }
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
async function api(method, path, body){
  const h={"Content-Type":"application/json"}; if(tok.value) h.Authorization="Bearer "+tok.value;
  const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  const j=await r.json().catch(()=>({})); if(!r.ok) throw new Error(j.error||("HTTP "+r.status)); return j;
}
function depth(id){ return id ? id.split(".").length-1 : 0; }
function short(v,n){ const s = typeof v==="string" ? v : JSON.stringify(v); return s && s.length>n ? s.slice(0,n)+"…" : (s||""); }
function render(){
  const log=$("log"); log.replaceChildren();
  if(!cur){ log.append(el("div","sys","Type a task below. Sub-agents appear as root.1, root.2… Approvals pop up top-right.")); return; }
  for(const e of cache[cur].events) { const n=node(e); if(n) log.append(n); }
  log.scrollTop = log.scrollHeight;
}
function node(e){
  if(e.kind==="user"){ const r=el("div","row user"), b=el("div","bubble",e.text);
    if((e.attachments||[]).length){ const a=el("div","atts");
      e.attachments.forEach(f=>{ const c=el("span","att","📎 "+f.name+" · "+size(f.bytes)); c.title=f.path; a.append(c); }); b.append(a); }
    r.append(b); return r; }
  if(e.kind==="message"){ if(!e.content) return null;
    const r=el("div","row d"+Math.min(depth(e.agent),3)), b=el("div","bubble"+(e.final?" final":""));
    b.append(el("div","who",e.agent), el("div",null,e.content)); r.append(b); return r; }
  if(e.kind==="audit"){
    if(e.event==="spawn") return el("div","step spawn","↳ "+e.agent+" launched "+e.child+(e.isolated?" (isolated copy)":"")+": "+short(e.task,160));
    if(e.event==="child_done") return el("div","step spawn","✓ "+e.agent+" finished ("+e.stop_reason+")");
    if(e.event==="upload") return el("div","step merge","📎 saved "+e.path+" ("+size(e.bytes)+")");
    if(e.event && !["merge","spawn","child_done"].includes(e.event)) return el("div","step",e.event+(e.agent?" ["+e.agent+"]":""));
    if(e.event==="merge" && e.skipped) return el("div","step conflict","⇢ merge skipped ("+e.skipped+")");
    if(e.event==="merge"){ const d=el("div");
      (e.applied||[]).forEach(a=>d.append(el("div","step merge","⇢ merged "+a.path+" ("+a.action+" by "+a.agent+")")));
      (e.conflicts||[]).forEach(c=>d.append(el("div","step conflict","⚠ conflict "+c.path+" — "+c.reason+" ("+c.agents.join(", ")+")"+(c.files.length?" → "+c.files.join(", "):""))));
      if(!(e.applied||[]).length && !(e.conflicts||[]).length) d.append(el("div","step merge","⇢ merge: no file changes"));
      return d; }
    const s=el("div","step"+(e.decision!=="allow"?" deny":(e.ok===false?" err":"")));
    s.append(el("b",null,"["+(e.agent||"root")+"] "), document.createTextNode("🔧 "+e.tool+" · "+(e.category||"?")+" · "+e.decision+" "+short(e.args,120)));
    if(e.error) s.append(document.createTextNode(" — "+short(e.error,160)));
    else if(e.result){ const d=el("details"); d.append(el("summary",null," result"), el("pre",null,short(e.result,1500))); s.append(d); }
    return s; }
  if(e.kind==="approval") return el("div","step"+(e.status==="approved"||e.status==="pending"?"":" deny"),
      "⏳ ["+e.agent+"] approval for "+e.tool+": "+e.status);
  if(e.kind==="status" && ["done","stopped","cancelled","error"].includes(e.status)) return el("div","sys","— "+e.status+" —");
  return null;
}
async function poll(){
  try{
    tasks=(await api("GET","/tasks")).tasks; const box=$("convs"); box.replaceChildren();
    tasks.slice().reverse().forEach(t=>{ const d=el("div","conv"+(t.id===cur?" sel":""));
      d.append(el("div","t",t.task)); const s=el("small",null,t.turns+" turn(s) "); s.append(el("span","badge "+t.status,t.status));
      d.append(s); d.onclick=()=>pick(t.id); box.append(d); });
    const t=tasks.find(x=>x.id===cur);
    $("title").textContent = t ? t.task : "New conversation";
    $("status").replaceChildren(t ? el("span","badge "+t.status,t.status) : "");
    $("cancel").style.display = t && ["queued","running","cancelling"].includes(t.status) ? "" : "none";
    if(cur){ const c=cache[cur], r=await api("GET","/tasks/"+cur+"/events?since="+c.since);
      if(r.events.length){ c.events.push(...r.events); c.since=r.next; const log=$("log");
        const atEnd = log.scrollTop+log.clientHeight >= log.scrollHeight-40;
        if(c.events.length===r.events.length) render(); else r.events.forEach(e=>{ const n=node(e); if(n) log.append(n); });
        if(atEnd) log.scrollTop=log.scrollHeight; } }
    await popups(); $("err").textContent="";
  }catch(e){ $("err").textContent="error: "+e.message; }
}
async function popups(){
  const list=(await api("GET","/approvals")).approvals, box=$("popups"), ids=new Set(list.map(a=>a.id));
  [...box.children].forEach(c=>{ if(!ids.has(c.dataset.id)) c.remove(); });
  list.forEach(a=>{ if(box.querySelector('[data-id="'+a.id+'"]')) return;
    const conv=tasks.find(t=>t.id===a.task), c=el("div","card"); c.dataset.id=a.id;
    const h=el("h3"); h.append(el("span","who",a.agent), document.createTextNode(" wants to run "+a.tool+" "), el("span","cat "+a.category,a.category));
    c.append(h, el("div","meta","conversation: "+(conv?short(conv.task,60):a.task)), el("pre",null,JSON.stringify(a.args,null,2)), el("div","meta",a.reason));
    const b=el("div","btns"), ok=el("button","ok","Approve"), no=el("button","no","Deny");
    const answer=async d=>{ if(answering.has(a.id)) return; answering.add(a.id); ok.disabled=no.disabled=true;
      try{ await api("POST","/approvals/"+a.id,{decision:d}); c.remove(); }catch(e){ $("err").textContent="error: "+e.message; ok.disabled=no.disabled=false; }
      answering.delete(a.id); };
    ok.onclick=()=>answer("approve"); no.onclick=()=>answer("deny");
    b.append(ok,no); c.append(b); box.append(c); });
}
// ---- attachments: chips before sending, sent base64 in the JSON body
let limits={uploads:true,max_upload_bytes:20*1048576,max_message_bytes:50*1048576}, pending=[];
function size(n){ return n<1024 ? n+" B" : n<1048576 ? (n/1024).toFixed(1)+" KB" : (n/1048576).toFixed(1)+" MB"; }
async function loadConfig(){ try{ limits=await api("GET","/config"); }catch(e){} }
function tooBig(f){ return f.size>limits.max_upload_bytes; }
function chips(){ const box=$("chips"); box.replaceChildren();
  pending.forEach((f,i)=>{ const c=el("span","chip"+(tooBig(f)?" bad":""),"📎 "+f.name+" · "+size(f.size)+(tooBig(f)?" (too big)":""));
    const x=el("button",null,"×"); x.title="remove"; x.onclick=()=>{ pending.splice(i,1); chips(); }; c.append(x); box.append(c); }); }
function addFiles(list){ for(const f of list) pending.push(f); chips(); }
function b64(file){ return new Promise((ok,ko)=>{ const r=new FileReader();
  r.onload=()=>ok(String(r.result).split(",",2)[1]||""); r.onerror=()=>ko(r.error); r.readAsDataURL(file); }); }
$("attach").onclick=()=>$("files").click();
$("files").onchange=e=>{ addFiles(e.target.files); e.target.value=""; };
const main=document.querySelector("main"); let depthDrag=0;
main.addEventListener("dragenter",e=>{ if([...e.dataTransfer.types].includes("Files")){ e.preventDefault(); depthDrag++; main.classList.add("dragging"); } });
main.addEventListener("dragover",e=>{ if([...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
main.addEventListener("dragleave",()=>{ if(--depthDrag<=0){ depthDrag=0; main.classList.remove("dragging"); } });
main.addEventListener("drop",e=>{ e.preventDefault(); depthDrag=0; main.classList.remove("dragging"); if(e.dataTransfer.files.length) addFiles(e.dataTransfer.files); });
async function send(){
  const text=$("input").value.trim(); if(!text && !pending.length) return;
  if(pending.some(tooBig)){ $("err").textContent="remove the files over "+size(limits.max_upload_bytes)+" first"; return; }
  const total=pending.reduce((s,f)=>s+f.size,0);
  if(total>limits.max_message_bytes){ $("err").textContent="attachments over "+size(limits.max_message_bytes)+" per message"; return; }
  $("send").disabled=true;
  try{
    const files=[]; for(const f of pending) files.push({name:f.name, content_b64:await b64(f)});
    if(!cur){ const t=await api("POST","/tasks",{task:text,files}); pick(t.id); }
    else await api("POST","/tasks/"+cur+"/messages",{text,files});
    $("input").value=""; pending=[]; chips(); poll();
  }catch(e){ $("err").textContent="error: "+e.message; }
  $("send").disabled=false;
}
$("send").onclick=send;
$("input").addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); send(); } });
$("new").onclick=()=>{ pick(null); $("input").focus(); };
$("cancel").onclick=async()=>{ if(cur) try{ await api("POST","/tasks/"+cur+"/cancel",{}); poll(); }catch(e){} };
loadConfig(); setInterval(poll,1000); poll();
</script></body></html>
"""
