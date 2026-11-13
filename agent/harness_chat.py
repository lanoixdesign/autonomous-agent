"""The harness chat page (served at / and /chat). Plain HTML + JS, no external resources.
Live updates by Server-Sent Events (/tasks/{id}/stream), falling back to polling if the stream fails.
Bilingual (EN/FR): every visible string comes from agent/i18n.py through t(); see agent/i18n_js.py."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH

CHAT_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="chat.pageTitle">autonomous-agent · chat</title>
<style>
 *{box-sizing:border-box} body{margin:0;font:14px/1.45 system-ui,sans-serif;color:#1d2127;background:#f4f5f7;height:100vh;display:flex}
 aside{width:260px;background:#1d2127;color:#e8eaee;display:flex;flex-direction:column}
 aside h1{font-size:15px;margin:14px 14px 8px} aside button.new{margin:0 12px 10px;padding:8px;border:0;border-radius:6px;background:#4062bb;color:#fff;cursor:pointer}
 #convs{flex:1;overflow:auto} .conv{padding:8px 14px;cursor:pointer;border-left:3px solid transparent}
 .conv:hover{background:#2a2f37} .conv.sel{background:#2f3540;border-left-color:#7e9cff}
 .conv .t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .conv small{color:#9aa3b0}
 #quota{max-height:38vh;overflow:auto;padding:4px 12px;font-size:11.5px;border-top:1px solid #2f3540}
 #quota h2{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#9aa3b0;margin:6px 0}
 .qk{margin:0 0 8px} .qk b{color:#e8eaee} .qk code{color:#9aa3b0;font-size:11px} .qk .off{color:#f19a92}
 .ql{display:flex;justify-content:space-between;color:#c5cad3} .bar{height:3px;background:#3a414c;border-radius:2px;margin:1px 0 3px}
 .bar i{display:block;height:3px;background:#7fc79a;border-radius:2px} .bar i.hi{background:#f0a73a} .bar i.full{background:#e5534b}
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
 #top button.lite{background:#e7ecfa;color:#2f4aa0} #top button#stopall{background:#7a0f0a;font-weight:700}
 #mode{font-size:11px;color:#8a919c}
 .card .remember{display:flex;gap:6px;margin-top:6px} .card .remember button{flex:1;padding:5px;font-weight:500;font-size:11.5px;background:#eef1f6;color:#2f4aa0}
 .card .never{font-size:11px;color:#9a1d14;margin-top:6px}
 .badge{font-size:11px;padding:1px 7px;border-radius:9px;background:#e4e7eb;color:#333}
 .badge.running,.badge.queued,.badge.cancelling{background:#fff0c2} .badge.done{background:#d3f2dc}
 .badge.error,.badge.cancelled,.badge.stopped,.badge.interrupted{background:#f7d4d4}
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
 @media (prefers-reduced-motion: reduce){.card{animation:none}}
 @media (min-width:900px){body.has-popups #log{padding-right:410px}}
 .card h3{margin:0 0 4px;font-size:13px} .card .meta{font-size:12px;color:#5a6270}
 .card pre{background:#f6f7f9;border-radius:6px;padding:6px;max-height:160px;overflow:auto;font-size:11.5px;white-space:pre-wrap;word-break:break-word}
 .card .cat{font-weight:600;text-transform:uppercase;font-size:11px;padding:1px 6px;border-radius:6px;background:#fdecd2;color:#8a4b00}
 .card .cat.send,.card .cat.spend,.card .cat.execute{background:#fbd9d6;color:#9a1d14}
 .card .btns{display:flex;gap:8px;margin-top:6px} .card button{flex:1;padding:7px;border:0;border-radius:6px;cursor:pointer;font-weight:600}
 .card .ok{background:#1f7a45;color:#fff} .card .no{background:#e4e7eb}
 #idcbox{display:inline-flex;align-items:center;gap:4px;font:600 12px system-ui;color:#5b3d8f;background:#efe8fa;border-radius:8px;padding:4px 8px;cursor:pointer}
 #idcbox.on{background:#5b3d8f;color:#fff} #idcbox input{margin:0}
 #idcpanel{padding:6px 16px 8px;background:#f8f5fd;border-bottom:1px solid #e3d9f3;font-size:12px;color:#3d2a63}
 #idcpanel .vrow{display:flex;justify-content:space-between;gap:10px} #idcpanel .why{color:#b3261e;font-weight:600}
 .vbar{height:8px;background:#e4e7eb;border-radius:4px;overflow:hidden;margin:4px 0}
 .vbar i{display:block;height:8px;background:#7c5cc4;transition:width .3s} .vbar i.low{background:#f0a73a} .vbar i.dead{background:#e5534b}
 @media (prefers-reduced-motion: reduce){.vbar i{transition:none}}
 #idcpanel summary{cursor:pointer;font-weight:600} #idcpanel ol{margin:4px 0 0;padding-left:20px;max-height:22vh;overflow:auto}
 #idcpanel li{margin:2px 0} #idcpanel li .k{font-weight:600} #idcpanel li .u{color:#b3261e} #idcpanel li .s{color:#1f7a45}
 .step.idc{color:#5b3d8f} .step.idcbad{color:#b3261e}
 #idcdefrow{display:flex;align-items:center;gap:6px;margin-top:8px;cursor:pointer} #idcdefrow input{width:auto;margin:0}
 #menu{display:none;background:#e7ecfa!important;color:#2f4aa0!important;font-size:18px;padding:4px 10px!important}
 #connectlink{display:block;margin-top:8px} #scrim{display:none}
 #err a{color:#2f4aa0;font-weight:600}
 /* ---- phones and small tablets: drawer sidebar, bottom-sheet approval cards, big touch targets */
 @media (max-width:760px){
  body{height:100vh;height:100dvh}
  aside{position:fixed;top:0;bottom:0;left:0;width:84vw;max-width:320px;z-index:30;transform:translateX(-102%);transition:transform .2s ease;padding-top:env(safe-area-inset-top)}
  body.nav aside{transform:none;box-shadow:0 0 40px rgba(0,0,0,.4)}
  body.nav #scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:25}
  #menu{display:inline-block}
  #top{flex-wrap:wrap;padding:8px 10px;padding-top:max(8px,env(safe-area-inset-top));gap:6px}
  #title{flex:1 1 60%;font-size:15px} #mode,#expmd,#expjson{display:none!important}
  #top button{padding:8px 10px;min-height:36px}
  #log{padding:10px 10px 16px} .bubble{max-width:88%} .step{margin-left:2px;font-size:11.5px;word-break:break-word}
  #popups{left:8px;right:8px;top:auto;bottom:calc(76px + env(safe-area-inset-bottom));width:auto;max-height:62vh}
  .card{padding:12px 14px} .card button{padding:12px;font-size:15px;min-height:46px} .card .remember button{min-height:40px;font-size:13px}
  .card pre{max-height:22vh}
  #composer{padding:8px;padding-bottom:max(8px,env(safe-area-inset-bottom))} #composer textarea{font-size:16px;height:48px}
  #composer button{min-width:60px;padding:0 12px} #attach{padding:0 10px!important}
  #idcpanel{padding:6px 10px} #idcpanel ol{max-height:16vh}
  aside button.new{padding:12px} .conv{padding:12px 14px} #idcdefrow input{width:20px;height:20px}
 }
 @media (max-width:760px) and (prefers-reduced-motion: reduce){aside{transition:none}}
/*LANG_CSS*/
</style></head><body>
<aside><h1>autonomous-agent</h1>
 <button class="new" id="new" data-i18n="chat.new"></button>
 <div id="convs"></div>
 <div id="quota"></div>
 <footer><span data-i18n="token.label"></span><input id="token" type="password">
  <a id="connectlink" href="/connect" data-i18n="chat.connect"></a>
  <label id="idcdefrow" data-i18n-title="idc.default.title"><input type="checkbox" id="idcdef"><span data-i18n="idc.default"></span></label>
  <div style="margin-top:6px;display:flex;justify-content:space-between;align-items:center"><a href="/dashboard" data-i18n="link.dashboard"></a>/*LANG_SWITCH*/</div></footer></aside>
<main>
 <div id="top"><button id="menu" class="lite" data-i18n-title="chat.menu">☰</button><span id="title"></span><span id="status"></span><span id="mode"></span>
  <label id="idcbox"><input type="checkbox" id="idc"><span data-i18n="idc.label"></span></label>
  <button id="cancel" style="display:none" data-i18n="chat.stop"></button>
  <button id="expmd" class="lite" style="display:none" data-i18n-title="chat.expmd.title">⇩ MD</button>
  <button id="expjson" class="lite" style="display:none" data-i18n-title="chat.expjson.title">⇩ JSON</button>
  <button id="stopall" data-i18n="btn.stopall" data-i18n-title="title.stopall"></button></div>
 <div id="idcpanel" hidden></div>
 <div id="log"></div>
 <div id="err"></div>
 <div id="chips"></div>
 <div id="composer"><button id="attach" data-i18n-title="chat.attach.title">📎</button>
  <input id="files" type="file" multiple hidden>
  <textarea id="input" data-i18n-placeholder="chat.input.placeholder"></textarea>
  <button id="send" data-i18n="chat.send"></button></div>
 <div id="drop" data-i18n="chat.drop"></div>
</main>
<div id="popups"></div>
<div id="scrim"></div>
<script>
/*I18N_JS*/
const $ = id => document.getElementById(id);
const tok = $("token"); tok.value = sessionStorage.getItem("harnessToken") || "";
tok.onchange = () => { sessionStorage.setItem("harnessToken", tok.value); loadConfig(); };
let cur = location.hash.slice(1) || null, tasks = [];
const cache = {};            // task id -> {since, events: []}
const answering = new Set(); // approval ids being answered
if(cur) cache[cur]={since:0,events:[]};
function pick(id){ cur=id; history.replaceState(null,"",(id?"#"+id:location.pathname+location.search)); if(id) cache[id]=cache[id]||{since:0,events:[]}; render(); stream(); poll(); }
// ---- live events: EventSource first, polling as a fallback
let es=null, esFor=null, live=false, retryAt=0;
function stream(){
  if(es && esFor===cur) return; if(es){ es.close(); es=null; live=false; }
  if(!cur || !window.EventSource || Date.now()<retryAt) return mode();
  const c=cache[cur], id=cur;
  es=new EventSource("/tasks/"+id+"/stream?since="+c.since+(tok.value?"&access_token="+encodeURIComponent(tok.value):"")); esFor=id;
  es.onopen=()=>{ live=true; mode(); };
  es.onmessage=m=>{ if(esFor!==cur) return; let e; try{ e=JSON.parse(m.data); }catch(_){ return; } add(c,[e]); };
  es.onerror=()=>{ if(es) es.close(); es=null; live=false; retryAt=Date.now()+15000; mode(); };
  mode();
}
function mode(){ $("mode").textContent = cur ? t(live ? "chat.live" : "chat.polling") : ""; }
function add(c, evs){
  const fresh=evs.filter(e=>e.seq>=c.since); if(!fresh.length) return;
  const log=$("log"), atEnd = log.scrollTop+log.clientHeight >= log.scrollHeight-40, first=!c.events.length;
  c.events.push(...fresh); c.since=fresh[fresh.length-1].seq+1;
  if(first) render(); else fresh.forEach(e=>{ const n=node(e); if(n) log.append(n); });
  if(atEnd) log.scrollTop=log.scrollHeight;
  if(fresh.some(e=>e.kind==="idc"||e.kind==="idc_toggle")) idcUI();
}
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
function fail(e){
  if(e.status===401){ const b=$("err"); b.replaceChildren(t("err.signin")+" "); const a=el("a",null,t("err.signinLink")); a.href="/connect"; b.append(a); return; }
  $("err").textContent=t("err.prefix",{msg:e.message}); }
async function api(method, path, body){
  const h={"Content-Type":"application/json"}; if(tok.value) h.Authorization="Bearer "+tok.value;
  const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  const j=await r.json().catch(()=>({})); if(!r.ok){ const e=new Error(j.error||("HTTP "+r.status)); e.status=r.status; throw e; } return j;
}
// ---- mobile: the sidebar is a drawer
function nav(open){ document.body.classList.toggle("nav", open); }
$("menu").onclick=()=>nav(!document.body.classList.contains("nav"));
$("scrim").onclick=()=>nav(false);
// remote mode: a device that is not signed in goes to /connect
fetch("/auth/status").then(r=>r.json()).then(s=>{ if(s.required && !s.authenticated && !tok.value) location.replace("/connect"); }).catch(()=>{});
function depth(id){ return id ? id.split(".").length-1 : 0; }
function short(v,n){ const s = typeof v==="string" ? v : JSON.stringify(v); return s && s.length>n ? s.slice(0,n)+"…" : (s||""); }
function badge(s){ return el("span","badge "+s,tr("status",s)); }
function render(){
  const log=$("log"); log.replaceChildren();
  if(!cur){ log.append(el("div","sys",t("chat.intro"))); return; }
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
  if(e.kind==="idc"){
    if(e.commit && e.commit.kind!=="final"){ const c=e.commit;
      return el("div","step "+(c.supported?"idc":"idcbad"),t("idc.step.commit",{agent:c.agent||e.agent,id:c.id,kind:tr("idc.kind",c.kind),
        support:t(c.supported?"idc.supported":"idc.unsupported"),cost:num(c.cost,2),text:short(c.text,220)})+(c.revises?" · "+t("idc.revises",{id:c.revises}):"")); }
    if(e.collapse) return el("div","step conflict",t("idc.step.collapse",{agent:e.agent,why:tr("idc.why",e.collapse),v:num(e.vitality,1)}));
    return null; }
  if(e.kind==="idc_toggle") return el("div","sys",t("idc.step.toggled",{state:t(e.enabled?"idc.on":"idc.off")}));
  if(e.kind==="audit"){
    if(["idc_commit","idc_collapse","idc_toggle"].includes(e.event)) return null;
    if(e.event==="spawn") return el("div","step spawn",t("step.spawn",{agent:e.agent,child:e.child,isolated:e.isolated?t("step.isolated"):"",task:short(e.task,160)}));
    if(e.event==="child_done") return el("div","step spawn",t("step.childDone",{agent:e.agent,reason:tr("status",e.stop_reason)}));
    if(e.event==="upload") return el("div","step merge",t("step.upload",{path:e.path,size:size(e.bytes)}));
    if(e.event==="rule_applied") return null;
    if(e.event==="rule_created") return el("div","step merge",t("step.ruleCreated",{rule:e.rule,tool:e.tool,scope:tr("scope",e.scope)}));
    if(e.event==="rule_revoked") return el("div","step deny",t("step.ruleRevoked",{rule:e.rule,tool:e.tool}));
    if(e.event==="stop_all") return el("div","step conflict",t("step.stopAll"));
    if(e.event && !["merge","spawn","child_done"].includes(e.event)) return el("div","step",e.event+(e.agent?" ["+e.agent+"]":""));
    if(e.event==="merge" && e.skipped) return el("div","step conflict",t("step.mergeSkipped",{why:tr("status",e.skipped)}));
    if(e.event==="merge"){ const d=el("div");
      (e.applied||[]).forEach(a=>d.append(el("div","step merge",t("step.merged",{path:a.path,action:tr("action",a.action),agent:a.agent}))));
      (e.conflicts||[]).forEach(c=>d.append(el("div","step conflict",t("step.conflict",{path:c.path,reason:tr("conflict",c.reason),agents:c.agents.join(", ")})+(c.files.length?" → "+c.files.join(", "):""))));
      if(!(e.applied||[]).length && !(e.conflicts||[]).length) d.append(el("div","step merge",t("step.noChanges")));
      return d; }
    const s=el("div","step"+(e.decision!=="allow"?" deny":(e.ok===false?" err":"")));
    s.append(el("b",null,"["+(e.agent||"root")+"] "), document.createTextNode("🔧 "+e.tool+" · "+(e.category?tr("cat",e.category):"?")+" · "+tr("decision",e.decision)+" "+short(e.args,120)));
    if(e.error) s.append(document.createTextNode(" — "+short(e.error,160)));
    else if(e.result){ const d=el("details"); d.append(el("summary",null,t("step.result")), el("pre",null,short(e.result,1500))); s.append(d); }
    return s; }
  if(e.kind==="approval" && e.status==="auto-approved") return el("div","step merge",t("step.autoApproved",{agent:e.agent,tool:e.tool,rule:e.rule}));
  if(e.kind==="approval") return el("div","step"+(e.status==="approved"||e.status==="pending"?"":" deny"),
      t("step.approval",{agent:e.agent,tool:e.tool,status:tr("status",e.status)}));
  if(e.kind==="status" && ["done","stopped","cancelled","error","interrupted"].includes(e.status)) return el("div","sys","— "+tr("status",e.status)+" —");
  return null;
}
async function poll(){
  try{
    tasks=(await api("GET","/tasks")).tasks; const box=$("convs"); box.replaceChildren();
    tasks.slice().reverse().forEach(x=>{ const d=el("div","conv"+(x.id===cur?" sel":""));
      d.append(el("div","t",x.task)); const s=el("small",null,t("chat.turns",{n:x.turns})+" "); s.append(badge(x.status));
      d.append(s); d.onclick=()=>{ nav(false); pick(x.id); }; box.append(d); });
    const c=tasks.find(x=>x.id===cur);
    $("title").textContent = c ? c.task : t("chat.newTitle");
    $("status").replaceChildren(c ? badge(c.status) : "");
    $("cancel").style.display = c && ["queued","running","cancelling"].includes(c.status) ? "" : "none";
    $("expmd").style.display = $("expjson").style.display = c ? "" : "none";
    idcUI();
    if(cur){ stream(); if(!live){ const k=cache[cur], r=await api("GET","/tasks/"+cur+"/events?since="+k.since); add(k, r.events); } }
    await popups(); $("err").textContent="";
  }catch(e){ fail(e); }
}
async function popups(){
  const list=(await api("GET","/approvals")).approvals, box=$("popups"), ids=new Set(list.map(a=>a.id));
  [...box.children].forEach(c=>{ if(!ids.has(c.dataset.id) || c.dataset.lang!==LANG) c.remove(); });
  list.forEach(a=>{ if(box.querySelector('[data-id="'+a.id+'"]')) return;
    const conv=tasks.find(x=>x.id===a.task), c=el("div","card"); c.dataset.id=a.id; c.dataset.lang=LANG;
    const h=el("h3"); h.append(el("span","who",a.agent), document.createTextNode(t("card.wants",{tool:a.tool})), el("span","cat "+a.category,tr("cat",a.category)));
    c.append(h, el("div","meta",t("card.conversation",{name:conv?short(conv.task,60):a.task})), el("pre",null,JSON.stringify(a.args,null,2)), el("div","meta",a.reason));
    const b=el("div","btns"), ok=el("button","ok",t("card.approve")), no=el("button","no",t("card.deny"));
    const answer=async (d,remember)=>{ if(answering.has(a.id)) return; answering.add(a.id); ok.disabled=no.disabled=true;
      try{ await api("POST","/approvals/"+a.id,remember?{decision:d,remember}:{decision:d}); c.remove(); }catch(e){ fail(e); ok.disabled=no.disabled=false; }
      answering.delete(a.id); };
    ok.onclick=()=>answer("approve"); no.onclick=()=>answer("deny");
    b.append(ok,no); c.append(b);
    if(a.rememberable){ const m=el("div","remember"), rc=el("button",null,t("card.alwaysConv",{tool:a.tool})), rs=el("button",null,t("card.alwaysSession"));
      rc.onclick=()=>answer("approve","conversation"); rs.onclick=()=>answer("approve","session"); m.append(rc,rs); c.append(m); }
    else c.append(el("div","never",t("card.never",{category:tr("cat",a.category)})));
    box.append(c); });
  document.body.classList.toggle("has-popups", box.children.length>0);
}
// ---- attachments: chips before sending, sent base64 in the JSON body
let limits={uploads:true,max_upload_bytes:20*1048576,max_message_bytes:50*1048576}, pending=[];
function num(v,d){ return v.toLocaleString(LANG,{maximumFractionDigits:d}); }
function size(n){ return n<1024 ? t("size.b",{n}) : n<1048576 ? t("size.kb",{n:num(n/1024,1)}) : t("size.mb",{n:num(n/1048576,1)}); }
async function loadConfig(){ try{ limits=await api("GET","/config"); }catch(e){} }
function tooBig(f){ return f.size>limits.max_upload_bytes; }
function chips(){ const box=$("chips"); box.replaceChildren();
  pending.forEach((f,i)=>{ const c=el("span","chip"+(tooBig(f)?" bad":""),"📎 "+f.name+" · "+size(f.size)+(tooBig(f)?t("chip.tooBig"):""));
    const x=el("button",null,"×"); x.title=t("chip.remove"); x.onclick=()=>{ pending.splice(i,1); chips(); }; c.append(x); box.append(c); }); }
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
  if(pending.some(tooBig)){ $("err").textContent=t("err.filesTooBig",{size:size(limits.max_upload_bytes)}); return; }
  const total=pending.reduce((s,f)=>s+f.size,0);
  if(total>limits.max_message_bytes){ $("err").textContent=t("err.messageTooBig",{size:size(limits.max_message_bytes)}); return; }
  $("send").disabled=true;
  try{
    const files=[]; for(const f of pending) files.push({name:f.name, content_b64:await b64(f)});
    if(!cur){ const r=await api("POST","/tasks",{task:text,files,idc:idcOn()}); nextIdc=null; tasks.push(r); pick(r.id); }
    else await api("POST","/tasks/"+cur+"/messages",{text,files});
    $("input").value=""; pending=[]; chips(); poll();
  }catch(e){ fail(e); }
  $("send").disabled=false;
}
$("send").onclick=send;
$("input").addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); send(); } });
$("new").onclick=()=>{ nav(false); pick(null); $("input").focus(); };
$("cancel").onclick=async()=>{ if(cur) try{ await api("POST","/tasks/"+cur+"/cancel",{}); poll(); }catch(e){} };
$("stopall").onclick=async()=>{ if(!confirm(t("confirm.stopall"))) return;
  try{ const r=await api("POST","/stop-all",{disable_schedules:true});
    $("err").textContent=t("msg.stopped",{tasks:r.cancelled.length,approvals:r.approvals_denied.length,schedules:r.schedules_paused.length}); poll(); }
  catch(e){ fail(e); } };
async function download(fmt){ if(!cur) return;
  const h={}; if(tok.value) h.Authorization="Bearer "+tok.value;
  const r=await fetch("/tasks/"+cur+"/export?format="+fmt+"&lang="+LANG,{headers:h}); if(!r.ok){ $("err").textContent=t("err.export",{status:r.status}); return; }
  const url=URL.createObjectURL(await r.blob()), a=el("a"); a.href=url; a.download="conversation-"+cur+"."+fmt; document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),5000); }
$("expmd").onclick=()=>download("md"); $("expjson").onclick=()=>download("json");
// ---- API keys: remaining quota per key and category (keys arrive masked from the server)
function fmt(f,v){ return f.startsWith("cost") ? num(v,2) : (v>=10000 ? num(Math.round(v/1000),0)+"k" : num(v,2)); }
async function quotas(){
  let st; try{ st=await api("GET","/keys"); }catch(e){ return; }
  const box=$("quota"); box.replaceChildren(); if(!st.keys || !st.keys.length) return;
  box.append(el("h2",null,t("quota.title")+(st.currency?t("quota.currency",{currency:st.currency}):"")));
  st.keys.forEach(k=>{ const d=el("div","qk"); const h=el("div");
    h.append(el("b",null,k.name+" "), el("code",null,k.key));
    if(!k.available) h.append(el("span","off",t("quota.notSet"))); if(k.cooldown_s) h.append(el("span","off",t("quota.cooldown",{s:k.cooldown_s})));
    d.append(h, el("div",null,t("quota.priority",{categories:k.categories.join(", "),p:k.priority})));
    Object.entries(k.limits).forEach(([f,v])=>{ const r=el("div","ql"); r.append(el("span",null,tr("limit",f)), el("span",null,t("quota.left",{left:fmt(f,v.remaining),limit:fmt(f,v.limit)})));
      const pct=v.limit? Math.min(100,100*v.used/v.limit):0, b=el("div","bar"), i=el("i",pct>=100?"full":pct>=80?"hi":""); i.style.width=pct+"%"; b.append(i); d.append(r,b); });
    box.append(d); });
}
// ---- IDC: per-conversation toggle, global default, vitality bar + append-only commitments
let settings={idc:false}, nextIdc=null;
async function loadSettings(){ try{ settings=await api("GET","/settings"); $("idcdef").checked=!!settings.idc; }catch(e){} idcUI(); }
$("idcdef").onchange=async e=>{ try{ settings=await api("POST","/settings",{idc:e.target.checked}); nextIdc=null; }catch(err){ fail(err); e.target.checked=!e.target.checked; } idcUI(); };
function curTask(){ return tasks.find(x=>x.id===cur); }
function idcOn(){ const c=curTask(); return c ? !!c.idc : (nextIdc!=null ? nextIdc : !!settings.idc); }
$("idc").onchange=async e=>{ const v=e.target.checked;
  if(!cur){ nextIdc=v; idcUI(); return; }
  try{ await api("POST","/tasks/"+cur+"/idc",{enabled:v}); const c=curTask(); if(c) c.idc=v; idcUI(); poll(); }
  catch(err){ fail(err); e.target.checked=!v; } };
function idcUI(){
  const on=idcOn(), c=curTask(), box=$("idcbox"), p=$("idcpanel");
  $("idc").checked=on; box.classList.toggle("on",on); box.title=t(cur?"idc.toggle.title":"idc.toggle.newTitle");
  $("idc").disabled=!!(c && ["queued","running","cancelling"].includes(c.status));
  if(!on || !cur){ p.hidden=true; return; }
  const evs=((cache[cur]||{}).events||[]).filter(e=>e.kind==="idc");
  const last=[...evs].reverse().find(e=>(e.agent||"root")==="root");
  const commits=evs.filter(e=>e.commit).map(e=>e.commit);
  p.hidden=false; p.replaceChildren();
  const row=el("div","vrow"), v=last?last.vitality:null, mx=last?last.max:(settings.idc_config||{}).vitality||100;
  const left=el("span",null,t("idc.vitality",{v:num(v==null?mx:v,1),max:num(mx,0)})+(last&&last.reserved>0?t("idc.reserved",{r:num(last.reserved,1)}):""));
  row.append(left); if(last&&last.collapsed) row.append(el("span","why",t("idc.collapsed",{why:tr("idc.why",last.collapsed)})));
  const bar=el("div","vbar"), i=el("i"), pct=Math.max(0,Math.min(100,100*(v==null?mx:v)/mx));
  i.className = v!=null && v<=0 ? "dead" : (last && v<=last.threshold ? "low" : ""); i.style.width=pct+"%"; bar.append(i);
  const d=el("details"); d.open=commits.length>0 && commits.length<=6;
  d.append(el("summary",null,t("idc.commitments",{n:commits.length})));
  if(!commits.length) d.append(el("div",null,t("idc.none")));
  else { const ol=el("ol"); commits.forEach(cm=>{ const li=el("li"); li.title=cm.id+(cm.evidence&&cm.evidence.length?" — "+cm.evidence.join(" | "):"");
    li.append(el("span","k",tr("idc.kind",cm.kind)+" "));
    if(cm.supported!=null) li.append(el("span",cm.supported?"s":"u","("+t(cm.supported?"idc.supported":"idc.unsupported")+") "));
    li.append(document.createTextNode(short(cm.text,200)+(cm.revises?" · "+t("idc.revises",{id:cm.revises}):"")+" · "+cm.agent));
    ol.append(li); }); d.append(ol); }
  p.append(row,bar,d);
}
const narrow = matchMedia("(max-width:760px)");
function placeholder(){ $("input").placeholder = t(narrow.matches ? "chat.input.short" : "chat.input.placeholder"); }
narrow.addEventListener && narrow.addEventListener("change", placeholder);
placeholder();
onLang = () => { placeholder(); render(); mode(); poll(); quotas(); chips(); idcUI(); };
render(); loadConfig(); loadSettings(); setInterval(poll,1000); stream(); poll(); setInterval(quotas,5000); quotas();
</script></body></html>
"""
CHAT_PAGE = CHAT_PAGE.replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", LANG_SWITCH).replace("/*I18N_JS*/", I18N_JS)
