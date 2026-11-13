"""The Settings page (/settings) and the first-run wizard (/welcome): everything configurable without a
terminal — API keys per category with limits and failover order, language, IDC, permissions, phone access,
parallel tasks, approval timeout, workspace, restart / quit. Plain HTML + JS, no external resources, EN/FR.
Secrets are typed here and sent once to the server; they never come back (only masked)."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH
from .theme import BASE_CSS, NAV_CSS, NAV_HTML, NAV_JS

COMMON_CSS = r"""
 *{box-sizing:border-box} body{margin:0;font-size:14px;line-height:1.5;min-height:100vh}
 h1,h2,h3{color:var(--text);margin:0} h2{font-size:17px;margin-bottom:4px} h3{font-size:14px;margin:14px 0 6px}
 p{margin:6px 0} .muted{color:var(--muted);font-size:13px}
 .card{background:rgba(20,20,28,.92);border:1px solid var(--line);border-radius:18px;padding:18px 20px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
 button,.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 18px;border-radius:999px;border:1px solid #3A3A46;background:var(--panel2);
  color:var(--text);font:600 13px var(--font);cursor:pointer;text-decoration:none;min-height:38px}
 button:hover,.btn:hover{border-color:var(--blue)} button:disabled{opacity:.55;cursor:default}
 .primary{background:linear-gradient(90deg,var(--blue2),var(--purple));border-color:transparent;color:#fff!important;box-shadow:0 0 18px rgba(37,99,235,.35)}
 .blue{background:#2563EB;border-color:#2563EB;color:#fff} .grey{background:#374151;border-color:#374151;color:#fff}
 .danger{background:#7F1D1D;border-color:#B91C1C;color:#FECACA}
 .linkish{background:none;border:0;color:var(--blue);padding:0;min-height:0;text-decoration:underline}
 input[type=text],input[type=password],input[type=number],input[type=url],select{width:100%;padding:10px 12px;font:14px var(--font);min-height:40px}
 label.f{display:block;font-size:12.5px;color:var(--soft);margin:10px 0 4px;font-weight:600}
 .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap} .row>*{min-width:0}
 .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11.5px;font-weight:600;background:#2A2A35;color:var(--soft)}
 .pill.ok{background:rgba(34,197,94,.15);color:var(--ok)} .pill.bad{background:rgba(248,113,113,.15);color:var(--bad)}
 .pill.blue{background:rgba(0,212,255,.14);color:var(--blue)} .pill.purple{background:rgba(157,0,255,.18);color:#D8A8FF}
 .switch{display:inline-flex;align-items:center;gap:10px;cursor:pointer;font-weight:600;color:var(--text)}
 .switch input{appearance:none;width:42px;height:24px;border-radius:999px;background:#2A2A35;border:1px solid #3A3A46;position:relative;cursor:pointer;margin:0;flex-shrink:0;transition:background .2s}
 .switch input::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#D1D5DB;transition:left .2s}
 .switch input:checked{background:linear-gradient(90deg,var(--blue2),var(--purple));border-color:transparent} .switch input:checked::after{left:20px;background:#fff}
 #toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#1E1E24;border:1px solid #3A3A46;border-radius:999px;padding:10px 18px;
  box-shadow:0 12px 30px rgba(0,0,0,.5);color:var(--text);font-weight:600;z-index:60;display:none;max-width:90vw;text-align:center}
 #toast.on{display:block} #toast.err{border-color:var(--bad);color:#FCA5A5}
 #overlay{position:fixed;inset:0;background:rgba(5,5,11,.92);z-index:80;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px;text-align:center;padding:24px}
 #overlay[hidden]{display:none} #overlay .big{font-size:20px;color:#fff;font-weight:700;max-width:520px}
 .spin{width:34px;height:34px;border-radius:50%;border:4px solid rgba(0,212,255,.25);border-top-color:var(--blue);animation:spin 1s linear infinite}
 @keyframes spin{to{transform:rotate(360deg)}}
"""

COMMON_JS = r"""
const $ = id => document.getElementById(id);
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
let CSRF = "", ST = {};
async function api(method, path, body){
  const h = {"Content-Type":"application/json"}; if(CSRF) h["X-CSRF-Token"] = CSRF;
  let tk = ""; try{ tk = sessionStorage.getItem("harnessToken") || ""; }catch(e){} if(tk) h.Authorization = "Bearer "+tk;
  const r = await fetch(path, {method, headers:h, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({})); if(!r.ok){ const e = new Error(j.error || ("HTTP "+r.status)); e.status = r.status; e.body = j; throw e; } return j;
}
let toastT = null;
function toast(msg, bad){ const b=$("toast"); b.textContent=msg; b.className="on"+(bad?" err":""); clearTimeout(toastT); toastT=setTimeout(()=>{ b.className=""; }, bad?6000:2600); }
function fail(e){ if(e && e.status===401){ location.href="/connect"; return; } toast(t("err.prefix",{msg:e.message}), true); }
async function status(){ ST = await api("GET","/app/status"); CSRF = ST.csrf || ""; return ST; }
function overlay(key, spin){ const o=$("overlay"); o.replaceChildren(); if(spin) o.append(el("div","spin")); o.append(el("div","big",t(key))); o.hidden=false; }
async function restartNow(){
  if(!confirm(t("set.confirmRestart"))) return;
  try{ await api("POST","/app/restart",{}); }catch(e){ return fail(e); }
  overlay("set.restarting", true);
  await new Promise(r=>setTimeout(r,1500));
  for(let i=0;i<120;i++){ try{ const r=await fetch("/app/status",{cache:"no-store"}); if(r.status<500){ location.reload(); return; } }catch(e){} await new Promise(r=>setTimeout(r,700)); }
}
async function quitNow(){
  if(!confirm(t("set.confirmQuit"))) return;
  try{ await api("POST","/app/quit",{}); }catch(e){ return fail(e); }
  overlay("set.stopped", false);
}
"""

SETTINGS_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="set.pageTitle">autonomous-agent · settings</title>
<style>
/*THEME*/
/*COMMON_CSS*/
 .wrap{display:grid;grid-template-columns:220px minmax(0,1fr);gap:18px;max-width:1180px;margin:0 auto;padding:18px}
 .side{position:sticky;top:76px;align-self:start;display:flex;flex-direction:column;gap:4px}
 .side a{padding:9px 14px;border-radius:12px;color:var(--soft)!important;text-decoration:none;font-weight:600;border:1px solid transparent}
 .side a:hover{background:#14141C;border-color:var(--line)}
 .cols{display:flex;flex-direction:column;gap:16px;min-width:0}
 section.card{scroll-margin-top:80px}
 .banner{max-width:1180px;margin:14px auto 0;padding:12px 18px;border-radius:14px;font-weight:600}
 .banner.lock{background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.45);color:#FCD34D}
 .banner.warn{background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.45);color:#FCA5A5}
 .banner.restart{background:rgba(0,212,255,.10);border:1px solid rgba(0,212,255,.45);color:#BAF3FF;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
 .banner[hidden]{display:none}
 .pcard{border:1px solid rgba(185,43,255,.55);border-radius:14px;padding:12px 14px;margin:10px 0;background:#101018;box-shadow:0 0 14px rgba(157,0,255,.18)}
 .pcard.off{opacity:.6;border-color:#3A3A46;box-shadow:none}
 .pcard .ptop{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 .pcard .pname{font-weight:700;color:#fff;font-size:15px} .pcard code{font:12.5px var(--mono);color:var(--soft);background:#0D0D14;border:1px solid var(--line);border-radius:8px;padding:2px 8px}
 .pcard .rank{font:700 12px var(--mono);color:var(--blue);min-width:26px}
 .pcard .pmeta{font-size:12.5px;color:var(--muted);margin-top:4px}
 .pcard .acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px} .pcard .acts button{padding:6px 14px;min-height:34px}
 .ibtn{width:34px;min-height:34px;padding:0} 
 .lim{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:4px 16px;margin-top:8px}
 .lim .ql{display:flex;justify-content:space-between;font-size:12px;color:var(--soft)} .bar{height:5px;background:#2A2A35;border-radius:3px;margin:2px 0 4px;overflow:hidden}
 .bar i{display:block;height:100%;background:linear-gradient(90deg,#00D4FF,#7DD3FC);box-shadow:0 0 8px #00D4FF} .bar i.hi{background:var(--warn);box-shadow:none} .bar i.full{background:var(--bad);box-shadow:none}
 .testline{font-size:12.5px;margin-top:6px} .testline.ok{color:var(--ok)} .testline.bad{color:var(--bad)}
 #pform{border:1px solid rgba(0,212,255,.4);border-radius:16px;padding:14px 16px;margin-top:12px;background:#0E0E16;box-shadow:0 0 22px rgba(0,212,255,.10)}
 #pform[hidden]{display:none}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 16px} .grid3{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:0 14px}
 .chips{display:flex;flex-wrap:wrap;gap:8px} .chips label{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid #3A3A46;border-radius:999px;cursor:pointer;font-size:13px}
 .chips input{accent-color:var(--blue);margin:0;width:16px;height:16px}
 details summary{cursor:pointer;color:var(--blue);font-weight:600;margin:10px 0 4px}
 table.perm{width:100%;border-collapse:collapse} table.perm td{padding:9px 6px;border-bottom:1px solid #1F1F29;vertical-align:middle}
 table.perm td:first-child{width:38%} .pc{font-weight:700;color:#fff} .pd{font-size:12px;color:var(--muted)}
 .seg{display:inline-flex;border:1px solid #3A3A46;border-radius:999px;overflow:hidden;background:#0D0D14}
 .seg label{position:relative;cursor:pointer} .seg input{position:absolute;opacity:0;width:1px;height:1px}
 .seg span{display:inline-block;padding:7px 14px;font:600 12.5px var(--font);color:var(--soft)}
 .seg input:checked+span{background:linear-gradient(90deg,var(--blue2),var(--purple));color:#fff}
 .seg input:focus-visible+span{outline:2px solid var(--blue);outline-offset:-2px}
 .seg input:disabled+span{opacity:.35;cursor:not-allowed;text-decoration:line-through}
 .lock{font-size:11.5px;color:#FCA5A5;margin-top:3px}
 .langbtns{display:inline-flex;gap:8px}
 .langbtns button.on{background:linear-gradient(90deg,var(--blue2),var(--purple));border-color:transparent;color:#fff}
 #qrbox svg{width:240px;height:auto;background:#fff;padding:8px;border-radius:12px;box-shadow:0 0 28px rgba(0,212,255,.35);display:block;margin:10px 0}
 #tokbox{word-break:break-all;font:13px var(--mono);background:#0D0D14;border:1px solid var(--line);border-radius:10px;padding:10px;margin-top:8px}
 #tokbox[hidden]{display:none}
 fieldset{border:0;padding:0;margin:0} fieldset:disabled{opacity:.6}
 @media (max-width:760px){
  .wrap{grid-template-columns:1fr;padding:10px;gap:10px} .side{position:static;flex-direction:row;overflow-x:auto;gap:6px}
  .side a{white-space:nowrap;border-color:var(--line);padding:7px 12px;font-size:12.5px}
  .card{padding:14px;border-radius:16px} .grid2{grid-template-columns:1fr}
  table.perm td{display:block;width:auto!important;border:0;padding:4px 0} table.perm tr{display:block;border-bottom:1px solid #1F1F29;padding:8px 0}
  .seg span{padding:9px 14px} input,select{font-size:16px!important} .banner{margin:10px}
 }
/*NAV_CSS*/
/*LANG_CSS*/
</style></head><body data-page="settings">
<header class="apphead"><a class="back" href="/" data-i18n="nav.back"></a><span class="brand">autonomous-agent</span>/*NAV*/<span class="sp"></span>/*LANG_SWITCH*/</header>
<div id="lockbar" class="banner lock" hidden></div>
<div id="warnbar" class="banner warn" hidden></div>
<div id="restartbar" class="banner restart" hidden><span id="restartwhat"></span><button id="restart1" class="primary" data-i18n="set.restart"></button></div>
<div class="wrap">
 <nav class="side" data-i18n-aria="set.heading">
  <a href="#keys" data-i18n="set.sec.keys"></a><a href="#general" data-i18n="set.sec.general"></a><a href="#safety" data-i18n="set.sec.safety"></a>
  <a href="#idc" data-i18n="set.sec.idc"></a><a href="#phone" data-i18n="set.sec.phone"></a><a href="#app" data-i18n="set.sec.app"></a></nav>
 <fieldset id="all" class="cols">
 <section id="keys" class="card"><h2 data-i18n="set.sec.keys"></h2>
  <p class="muted" data-i18n="set.keys.help"></p>
  <div class="row" style="justify-content:space-between"><label class="switch"><input type="checkbox" id="demo"><span data-i18n="set.demo"></span></label><span id="modebadge" class="pill"></span></div>
  <p id="storage" class="muted"></p>
  <p class="muted" data-i18n="set.keys.failover"></p>
  <div id="plist"></div>
  <div class="row"><button id="addkey" class="primary" data-i18n="set.keys.add"></button></div>
  <form id="pform" hidden autocomplete="off">
   <h3 id="ftitle"></h3>
   <div class="grid2">
    <div><label class="f" for="fprov" data-i18n="set.f.provider"></label><select id="fprov"></select></div>
    <div><label class="f" for="fname" data-i18n="set.f.name"></label><input id="fname" type="text" maxlength="60"></div>
   </div>
   <label class="f" for="fkey" data-i18n="set.f.key"></label>
   <input id="fkey" type="password" autocomplete="new-password" spellcheck="false">
   <div class="row" style="justify-content:space-between"><a id="getkey" target="_blank" rel="noopener noreferrer" data-i18n="set.f.getKey"></a><label class="switch"><input type="checkbox" id="fenabled" checked><span data-i18n="set.f.enabled"></span></label></div>
   <label class="f" data-i18n="set.f.cats"></label><div id="fcats" class="chips"></div><p class="muted" data-i18n="set.f.catsHelp"></p>
   <details id="fadv"><summary data-i18n="set.f.advanced"></summary>
    <div class="grid2"><div><label class="f" for="fmodel" data-i18n="set.f.model"></label><input id="fmodel" type="text"></div>
     <div><label class="f" for="fbase" data-i18n="set.f.base"></label><input id="fbase" type="url"></div></div>
   </details>
   <details id="flimd"><summary data-i18n="set.f.limits"></summary><div id="flims" class="grid3"></div>
    <h3 data-i18n="set.f.pricing"></h3><div id="fprices" class="grid3"></div>
    <div style="max-width:200px"><label class="f" for="fcur" data-i18n="set.f.currency"></label><input id="fcur" type="text" maxlength="8"></div></details>
   <div id="ftest" class="testline" aria-live="polite"></div>
   <div class="row" style="margin-top:12px"><button type="button" id="ftestb" data-i18n="set.f.test"></button><span class="sp" style="flex:1"></span>
    <button type="button" id="fcancel" class="grey" data-i18n="set.f.cancel"></button><button type="submit" id="fsave" class="blue" data-i18n="set.f.save"></button></div>
  </form>
 </section>
 <section id="general" class="card"><h2 data-i18n="set.sec.general"></h2>
  <label class="f" data-i18n="set.lang"></label><div class="langbtns" id="langbtns"></div><p class="muted" data-i18n="set.lang.help"></p>
  <label class="f" for="ws" data-i18n="set.workspace"></label><div class="row"><input id="ws" type="text" style="flex:1"></div>
  <p class="muted"><span data-i18n="set.workspace.help"></span> <span id="wsactive"></span></p>
  <div class="grid2"><div><label class="f" for="maxt" data-i18n="set.maxTasks"></label><input id="maxt" type="number" min="1" max="16"><p class="muted" data-i18n="set.maxTasks.help"></p></div>
   <div><label class="f" for="tmo" data-i18n="set.timeout"></label><input id="tmo" type="number" min="10" max="3600"><p class="muted" data-i18n="set.timeout.help"></p></div></div>
  <div class="row"><button id="gsave" class="blue" data-i18n="set.save"></button></div>
 </section>
 <section id="safety" class="card"><h2 data-i18n="set.sec.safety"></h2><p class="muted" data-i18n="set.safety.help"></p>
  <table class="perm"><tbody id="perms"></tbody></table><p id="permtools" class="muted"></p>
  <div class="row"><button id="psave" class="blue" data-i18n="set.save"></button></div></section>
 <section id="idc" class="card"><h2 data-i18n="set.sec.idc"></h2><p class="muted" data-i18n="set.idc.help"></p>
  <label class="switch"><input type="checkbox" id="idcon"><span data-i18n="set.idc.enabled"></span></label>
  <details><summary data-i18n="set.f.advanced"></summary><div id="idcf" class="grid3"></div></details>
  <div class="row" style="margin-top:10px"><button id="isave" class="blue" data-i18n="set.save"></button></div></section>
 <section id="phone" class="card"><h2 data-i18n="set.sec.phone"></h2><p class="muted" data-i18n="set.phone.help"></p>
  <p id="phonestate" class="pill"></p>
  <label class="switch"><input type="checkbox" id="remon"><span data-i18n="set.phone.enable"></span></label>
  <div class="grid2"><div><label class="f" for="tunnel" data-i18n="set.phone.tunnel"></label><select id="tunnel"></select></div>
   <div><label class="f" for="purl" data-i18n="set.phone.url"></label><input id="purl" type="url" data-i18n-placeholder="set.phone.urlPh"></div></div>
  <div class="row" style="margin-top:10px"><button id="rsave" class="blue" data-i18n="set.save"></button><button id="qrb" data-i18n="set.phone.qr"></button><button id="newtok" class="grey" data-i18n="set.phone.newToken"></button></div>
  <div id="qrbox"></div><div id="tokbox" hidden></div>
  <p id="remset" class="muted"></p></section>
 <section id="app" class="card"><h2 data-i18n="set.sec.app"></h2><p class="muted" data-i18n="set.app.help"></p>
  <p id="appinfo" class="muted"></p>
  <div class="row"><button id="restart2" class="primary" data-i18n="set.restart"></button><button id="quit" class="danger" data-i18n="set.quit"></button><a class="btn" href="/welcome" data-i18n="set.app.wizard"></a></div></section>
 </fieldset>
</div>
<div id="toast" role="status" aria-live="polite"></div>
<div id="overlay" hidden role="alert"></div>
<script>
/*I18N_JS*/
/*NAV_JS*/
/*COMMON_JS*/
let V = null, P = [], editing = null;
const PROVS = ["groq","openai","openrouter","ollama","custom"];
function num(v,d){ return Number(v||0).toLocaleString(LANG,{maximumFractionDigits:d}); }
function fmt(f,v){ return f.startsWith("cost") ? num(v,2) : (v>=10000 ? num(Math.round(v/1000),0)+"k" : num(v,2)); }
async function load(){
  try{ await status(); }catch(e){ if(e.status===401){ location.href="/connect"; return; } return fail(e); }
  const lock=$("lockbar"), warn=$("warnbar");
  if(!ST.available){ lock.hidden=false; lock.textContent=t("set.unavailable"); $("all").disabled=true; return; }
  if(!ST.editable){ lock.hidden=false; lock.textContent=t("set.locked"); $("all").disabled=true; return; }
  lock.hidden=true; warn.hidden=!( !ST.local && ST.remote_settings ); warn.textContent=t("set.remoteEditing");
  try{ V=await api("GET","/app/settings"); P=(await api("GET","/app/providers")).providers; }catch(e){ return fail(e); }
  draw();
}
function draw(){ if(!V) return; drawKeys(); drawGeneral(); drawPerms(); drawIdc(); drawPhone(); drawApp(); drawRestart(); }
function drawRestart(){ const r=V.restart_needed||[], b=$("restartbar"); b.hidden=!r.length;
  $("restartwhat").textContent=t("set.restartNeeded")+" "+r.map(k=>tr("rf",k)).join(", "); $("restart1").disabled=$("restart2").disabled=!V.can_restart; }
// ---------------- keys
function drawKeys(){
  $("demo").checked=!!V.demo; const mb=$("modebadge"); mb.textContent=tr("set.mode",V.mode); mb.className="pill "+(V.mode==="demo"?"purple":"ok");
  $("storage").textContent=V.storage==="keyring" ? t("set.storage.keyring") : t("set.storage.file",{home:V.secrets_dir||V.home});
  const box=$("plist"); box.replaceChildren();
  if(!P.length){ box.append(el("p","muted",t("set.keys.none"))); return; }
  P.forEach((p,i)=>{ const c=el("div","pcard"+(p.enabled?"":" off"));
    const top=el("div","ptop"); top.append(el("span","rank","#"+(i+1)), el("span","pname",p.name), el("span","pill blue",tr("prov",p.provider)));
    top.append(el("span","pill "+(!p.enabled?"":(p.available?"ok":"bad")), !p.enabled?t("set.keys.disabled"):(p.cooldown_s?t("set.keys.cooldown",{s:p.cooldown_s}):(p.available?t("set.keys.available"):t("set.keys.unavailable")))));
    if(p.needs_key) top.append(el("code",null,p.key||"—"));
    c.append(top);
    c.append(el("div","pmeta",t("set.keys.model",{model:p.model})+" · "+t("set.keys.for",{cats:p.categories.map(x=>tr("kcat",x)).join(", ")})));
    const u=p.used||{}; c.append(el("div","pmeta",t("set.keys.today",{req:num(u.requests_per_day||0,0),tok:fmt("tokens",u.tokens_per_day||0),cost:num(u.cost_per_day||0,4)+(V.currency?" "+V.currency:"")})));
    const lims=Object.entries(p.usage||{});
    if(lims.length){ const g=el("div","lim"); lims.forEach(([f,v])=>{ const r=el("div"); const q=el("div","ql"); q.append(el("span",null,tr("limit",f)), el("span",null,t("quota.left",{left:fmt(f,v.remaining),limit:fmt(f,v.limit)})));
        const pct=v.limit?Math.min(100,100*v.used/v.limit):0, b=el("div","bar"), ii=el("i",pct>=100?"full":pct>=80?"hi":""); ii.style.width=pct+"%"; b.append(ii); r.append(q,b); g.append(r); }); c.append(g); }
    else c.append(el("div","pmeta",t("set.keys.noLimit")));
    const tl=el("div","testline"); tl.setAttribute("aria-live","polite");
    const a=el("div","acts"), up=el("button","ibtn","↑"), dn=el("button","ibtn","↓"), te=el("button",null,t("set.keys.test")), ed=el("button",null,t("set.keys.edit")), de=el("button","danger",t("set.keys.delete"));
    up.title=up.ariaLabel=t("set.keys.up"); dn.title=dn.ariaLabel=t("set.keys.down"); up.disabled=i===0; dn.disabled=i===P.length-1;
    up.onclick=()=>move(i,-1); dn.onclick=()=>move(i,1);
    te.onclick=async()=>{ tl.className="testline"; tl.textContent=t("set.f.testing"); try{ showTest(tl, await api("POST","/app/providers/"+p.id+"/test",{})); }catch(e){ fail(e); tl.textContent=""; } };
    ed.onclick=()=>openForm(p); de.onclick=async()=>{ if(!confirm(t("set.keys.confirmDelete",{name:p.name}))) return; try{ await api("POST","/app/providers/"+p.id+"/delete",{}); toast(t("set.saved")); await reload(); }catch(e){ fail(e); } };
    a.append(up,dn,te,ed,de); c.append(a,tl); box.append(c); });
}
function showTest(line,r){ line.className="testline "+(r.ok?"ok":"bad"); line.textContent=tr("test",r.code,{http:r.http_status||"?"}); }
async function move(i,d){ const ids=P.map(p=>p.id); const [x]=ids.splice(i,1); ids.splice(i+d,0,x);
  try{ P=(await api("POST","/app/providers/order",{ids})).providers; drawKeys(); toast(t("set.savedLive")); }catch(e){ fail(e); } }
async function reload(){ V=await api("GET","/app/settings"); P=(await api("GET","/app/providers")).providers; draw(); }
$("demo").onchange=async e=>{ try{ V=await api("POST","/app/settings",{demo:e.target.checked}); draw(); toast(t("set.savedLive")); }catch(err){ fail(err); e.target.checked=!e.target.checked; } };
function buildForm(){
  const s=$("fprov"); s.replaceChildren(); PROVS.forEach(k=>{ const o=el("option",null,tr("prov",k)); o.value=k; s.append(o); });
  const cats=$("fcats"); cats.replaceChildren(); (V.categories||[]).forEach(c=>{ const l=el("label"), i=el("input"); i.type="checkbox"; i.value=c; l.append(i, document.createTextNode(tr("kcat",c))); cats.append(l); });
  const lims=$("flims"); lims.replaceChildren(); (V.limit_fields||[]).forEach(f=>{ const d=el("div"), l=el("label","f",tr("limit",f)), i=el("input"); i.type="number"; i.min="0"; i.step="any"; i.dataset.limit=f; i.id="lim-"+f; l.htmlFor=i.id; d.append(l,i); lims.append(d); });
  const pr=$("fprices"); pr.replaceChildren(); (V.pricing_fields||[]).forEach(f=>{ const d=el("div"), l=el("label","f",tr("price",f)), i=el("input"); i.type="number"; i.min="0"; i.step="any"; i.dataset.price=f; i.id="price-"+f; l.htmlFor=i.id; d.append(l,i); pr.append(d); });
}
function presetFill(keep){ const k=$("fprov").value, pre=(V.presets||{})[k]||{};
  if(!keep){ $("fbase").value=pre.base_url||""; $("fmodel").value=pre.model||""; if(!$("fname").value || PROVS.some(p=>$("fname").value===tr("prov",p).split(" (")[0])) $("fname").value=tr("prov",k).split(" (")[0]; }
  const g=$("getkey"); g.hidden=!pre.keys_url; g.href=pre.keys_url||"#"; $("fkey").disabled=!pre.key && k!=="custom";
  if(k==="custom") $("fadv").open=true; }
$("fprov").onchange=()=>presetFill(false);
function openForm(p){ editing=p||null; buildForm(); const f=$("pform"); f.hidden=false; $("ftest").textContent="";
  $("ftitle").textContent=p?t("set.f.title.edit",{name:p.name}):t("set.f.title.add");
  $("fprov").value=p?p.provider:"groq"; $("fname").value=p?p.name:""; $("fkey").value="";
  $("fkey").placeholder=p&&p.has_key?t("set.f.keyKeep",{key:p.key}):t("set.f.keyPh");
  $("fenabled").checked=p?!!p.enabled:true; presetFill(!!p);
  if(p){ $("fmodel").value=p.model||""; $("fbase").value=p.base_url||""; }
  const cats=p?p.categories:["text","code"]; $("fcats").querySelectorAll("input").forEach(i=>{ i.checked=cats.includes(i.value); });
  $("flims").querySelectorAll("input").forEach(i=>{ const v=p&&p.limits?p.limits[i.dataset.limit]:null; i.value=v==null?"":v; });
  $("fprices").querySelectorAll("input").forEach(i=>{ const v=p&&p.pricing?p.pricing[i.dataset.price]:null; i.value=v==null?"":v; });
  $("fcur").value=V.currency||""; $("flimd").open=!!(p&&Object.keys(p.limits||{}).length);
  f.scrollIntoView({block:"nearest"}); (p?$("fkey"):$("fprov")).focus(); }
function formData(){ const lim={}, pr={};
  $("flims").querySelectorAll("input").forEach(i=>{ if(i.value!=="") lim[i.dataset.limit]=Number(i.value); });
  $("fprices").querySelectorAll("input").forEach(i=>{ if(i.value!=="") pr[i.dataset.price]=Number(i.value); });
  const d={provider:$("fprov").value, name:$("fname").value.trim(), model:$("fmodel").value.trim(), base_url:$("fbase").value.trim(),
    categories:[...$("fcats").querySelectorAll("input:checked")].map(i=>i.value), limits:lim, pricing:pr, enabled:$("fenabled").checked};
  if($("fkey").value.trim()) d.key=$("fkey").value.trim(); return d; }
$("addkey").onclick=()=>openForm(null);
$("fcancel").onclick=()=>{ $("pform").hidden=true; $("fkey").value=""; editing=null; };
$("ftestb").onclick=async()=>{ const line=$("ftest"); line.className="testline"; line.textContent=t("set.f.testing");
  const d=formData(); if(editing) d.id=editing.id; try{ showTest(line, await api("POST","/app/providers/test",d)); }catch(e){ fail(e); line.textContent=""; } };
$("pform").onsubmit=async ev=>{ ev.preventDefault(); const d=formData();
  if(!d.categories.length){ toast(t("set.f.needCat"),true); return; }
  $("fsave").disabled=true;
  try{ if($("fcur").value.trim()!==(V.currency||"")) await api("POST","/app/settings",{currency:$("fcur").value.trim()});
    await api("POST", editing?"/app/providers/"+editing.id:"/app/providers", d);
    $("fkey").value=""; $("pform").hidden=true; editing=null; toast(t("set.savedLive")); await reload(); }
  catch(e){ fail(e); } $("fsave").disabled=false; };
// ---------------- general
function drawGeneral(){ const lb=$("langbtns"); lb.replaceChildren();
  ["en","fr"].forEach(l=>{ const b=el("button",(V.lang===l?"on":""),tr("wiz",l)); b.type="button"; b.setAttribute("aria-pressed",String(V.lang===l));
    b.onclick=async()=>{ try{ V=await api("POST","/app/settings",{lang:l}); setLang(l); toast(t("set.savedLive")); }catch(e){ fail(e); } }; lb.append(b); });
  $("ws").value=V.workspace.saved||V.workspace.active||""; $("wsactive").textContent=V.workspace.active?t("set.workspace.active",{path:V.workspace.active}):"";
  $("maxt").value=V.max_tasks.saved||V.max_tasks.active||4; $("tmo").value=Math.round(V.approval_timeout||300); }
$("gsave").onclick=async()=>{ const d={approval_timeout:Number($("tmo").value), max_tasks:Number($("maxt").value)};
  const ws=$("ws").value.trim(); if(ws && ws!==(V.workspace.saved||V.workspace.active)) d.workspace=ws;
  try{ V=await api("POST","/app/settings",d); draw(); toast(t((V.restart_needed||[]).length?"set.savedRestart":"set.savedLive")); }catch(e){ fail(e); } };
// ---------------- permissions
function drawPerms(){ const tb=$("perms"); tb.replaceChildren(); const pm=V.permissions;
  pm.categories.forEach(c=>{ const tr_=el("tr"), a=el("td"), b=el("td"); a.append(el("div","pc",tr("cat",c)), el("div","pd",tr("perm",c)));
    const seg=el("div","seg"); seg.setAttribute("role","radiogroup"); seg.setAttribute("aria-label",tr("cat",c));
    pm.modes.forEach(m=>{ const l=el("label"), i=el("input"); i.type="radio"; i.name="perm-"+c; i.value=m; i.checked=pm.defaults[c]===m;
      i.disabled = pm.protected.includes(c) && m==="allow"; l.append(i, el("span",null,tr("mode",m))); seg.append(l); });
    b.append(seg); if(pm.protected.includes(c)) b.append(el("div","lock",t("set.safety.locked")));
    tr_.append(a,b); tb.append(tr_); });
  const tools=Object.entries(pm.tools||{}); $("permtools").textContent=tools.length?t("set.safety.tools",{tools:tools.map(([k,v])=>k+": "+tr("mode",v)).join(", ")}):""; }
$("psave").onclick=async()=>{ const d={}; V.permissions.categories.forEach(c=>{ const i=document.querySelector('input[name="perm-'+c+'"]:checked'); if(i) d[c]=i.value; });
  try{ V=await api("POST","/app/settings",{permissions:d}); draw(); toast(t("set.savedLive")); }catch(e){ fail(e); } };
// ---------------- IDC
const IDC_FIELDS=["vitality","step_cost","tool_cost","token_cost","collapse_threshold","stall_limit","commit_cost","unknown_cost","unsupported_cost","revise_cost","child_share","allow_revise"];
function drawIdc(){ $("idcon").checked=!!V.idc.enabled; const g=$("idcf"); g.replaceChildren();
  IDC_FIELDS.forEach(f=>{ const d=el("div"), l=el("label","f",tr("idcf",f)), i=el("input"); i.id="idc-"+f; l.htmlFor=i.id; i.dataset.f=f;
    if(f==="allow_revise"){ i.type="checkbox"; i.checked=!!V.idc[f]; i.style.width="20px"; i.style.height="20px"; } else { i.type="number"; i.step="any"; i.min="0"; i.value=V.idc[f]; }
    d.append(l,i); g.append(d); }); }
$("isave").onclick=async()=>{ const d={enabled:$("idcon").checked}; $("idcf").querySelectorAll("input").forEach(i=>{ d[i.dataset.f]= i.type==="checkbox" ? i.checked : Number(i.value); });
  try{ V=await api("POST","/app/settings",{idc:d}); draw(); toast(t("set.savedLive")); }catch(e){ fail(e); } };
// ---------------- phone
function drawPhone(){ const r=V.remote, s=$("tunnel"); s.replaceChildren(); r.tunnels.forEach(k=>{ const o=el("option",null,tr("tunnel",k)); o.value=k; s.append(o); });
  s.value=r.tunnel||"none"; $("remon").checked=!!r.enabled; $("purl").value=r.public_url||"";
  const st=$("phonestate"); st.className="pill "+(r.active?"ok":""); st.textContent=r.active?(r.active_url?t("set.phone.onUrl",{url:r.active_url}):t("set.phone.onNoUrl")):t("set.phone.off");
  $("qrb").hidden=!r.active; $("newtok").disabled=!!r.token_from_env; $("newtok").title=r.token_from_env?t("set.phone.tokenEnv"):"";
  $("remset").textContent=ST.remote_settings?t("set.phone.remoteSettingsOn"):t("set.phone.remoteSettingsOff"); }
$("rsave").onclick=async()=>{ try{ V=await api("POST","/app/settings",{remote:{enabled:$("remon").checked,tunnel:$("tunnel").value,public_url:$("purl").value.trim()}}); draw();
  toast(t((V.restart_needed||[]).length?"set.savedRestart":"set.saved")); }catch(e){ fail(e); } };
$("qrb").onclick=async()=>{ try{ const r=await api("POST","/auth/pair",{}); const b=$("qrbox"); b.innerHTML=r.svg; b.append(el("p","muted",t("set.phone.qrHelp")), el("code",null,r.url)); }catch(e){ fail(e); } };
$("newtok").onclick=async()=>{ if(!confirm(t("set.phone.confirmToken"))) return;
  try{ const r=await api("POST","/app/remote/token",{}); const b=$("tokbox"); b.hidden=false; b.replaceChildren(el("div",null,t("set.phone.tokenShown")), el("b",null,r.token)); }catch(e){ fail(e); } };
// ---------------- app
function drawApp(){ $("appinfo").textContent=t("set.app.version",{v:V.version})+" · "+t("set.app.home",{home:V.home}); $("quit").disabled=!V.can_restart; }
$("restart1").onclick=$("restart2").onclick=restartNow; $("quit").onclick=quitNow;
onLang=()=>{ draw(); if(ST.available && !ST.editable) $("lockbar").textContent=t("set.locked"); };
load();
</script></body></html>
"""

WELCOME_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="wiz.pageTitle">autonomous-agent · welcome</title>
<style>
/*THEME*/
/*COMMON_CSS*/
 main{max-width:620px;margin:0 auto;padding:28px 18px 40px}
 .logo{width:84px;height:84px;margin:6px auto 14px;border-radius:50%;border:6px solid var(--blue);box-shadow:0 0 22px var(--blue),0 0 48px rgba(0,212,255,.35);display:flex;align-items:center;justify-content:center;background:#0B0B14}
 .logo i{width:28px;height:28px;border-radius:7px;background:var(--blue2);box-shadow:0 0 12px rgba(37,99,235,.8)}
 .steps{display:flex;justify-content:center;gap:8px;margin-bottom:14px} .steps span{width:34px;height:5px;border-radius:3px;background:#2A2A35}
 .steps span.on{background:linear-gradient(90deg,var(--blue),var(--purple));box-shadow:0 0 10px rgba(0,212,255,.5)}
 .card{text-align:center} h1{font-size:24px;margin-bottom:6px} .card p{color:var(--soft)}
 .stepn{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
 .big2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0 6px} .big2 button{padding:18px;font-size:17px;border-radius:16px}
 .big2 button.on{background:linear-gradient(90deg,var(--blue2),var(--purple));border-color:transparent}
 .provs{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0;text-align:left}
 .provs label{display:flex;gap:10px;align-items:center;padding:12px 14px;border:1px solid #3A3A46;border-radius:14px;cursor:pointer;background:#101018}
 .provs label:has(input:checked){border-color:var(--blue);box-shadow:0 0 14px rgba(0,212,255,.25)} .provs input{accent-color:var(--blue);margin:0}
 .form{text-align:left} .acts{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:16px}
 .or{display:flex;align-items:center;gap:10px;color:var(--muted);margin:18px 0 10px} .or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
 .testline{font-size:13px;margin-top:8px;min-height:20px} .testline.ok{color:var(--ok)} .testline.bad{color:var(--bad)}
 section[hidden]{display:none}
 .lang{position:absolute;top:14px;right:14px}
 @media (max-width:520px){ .provs{grid-template-columns:1fr} .big2 button{padding:14px} main{padding:18px 12px} input{font-size:16px!important} }
/*LANG_CSS*/
</style></head><body data-page="welcome">
<div class="lang">/*LANG_SWITCH*/</div>
<main>
 <div class="logo"><i></i></div>
 <div class="steps" aria-hidden="true"><span id="d1"></span><span id="d2"></span><span id="d3"></span></div>
 <section id="s1" class="card"><div class="stepn" id="n1"></div><h1 data-i18n="wiz.welcome"></h1><p data-i18n="wiz.intro"></p><p data-i18n="wiz.chooseLang"></p>
  <div class="big2"><button type="button" data-pick="en" data-i18n="wiz.en"></button><button type="button" data-pick="fr" data-i18n="wiz.fr"></button></div>
  <div class="acts"><button id="next1" class="primary" data-i18n="wiz.next"></button></div></section>
 <section id="s2" class="card" hidden><div class="stepn" id="n2"></div><h1 data-i18n="wiz.keyTitle"></h1><p data-i18n="wiz.keyHelp"></p>
  <div class="form"><div class="provs" id="provs" role="radiogroup"></div>
   <label class="f" for="key" data-i18n="set.f.key"></label><input id="key" type="password" autocomplete="new-password" spellcheck="false" data-i18n-placeholder="set.f.keyPh">
   <p><a id="getkey" target="_blank" rel="noopener noreferrer" data-i18n="set.f.getKey"></a></p>
   <div id="test" class="testline" aria-live="polite"></div></div>
  <div class="acts"><button id="back2" class="grey" data-i18n="wiz.back"></button><button id="testb" data-i18n="set.f.test"></button><button id="save2" class="primary" data-i18n="wiz.save"></button></div>
  <div class="or" data-i18n="wiz.or"></div>
  <button id="demo" class="btn" data-i18n="wiz.demo"></button><p class="muted" data-i18n="wiz.demoHelp"></p>
  <p class="muted" data-i18n="wiz.later"></p></section>
 <section id="s3" class="card" hidden><div class="stepn" id="n3"></div><h1 data-i18n="wiz.doneTitle"></h1><p id="donemsg"></p>
  <div class="acts"><a class="btn primary" href="/" data-i18n="wiz.open"></a><a class="btn" href="/settings" data-i18n="wiz.settings"></a></div></section>
 <section id="slock" class="card" hidden><h1 data-i18n="wiz.welcome"></h1><p data-i18n="wiz.locked"></p><div class="acts"><a class="btn primary" href="/" data-i18n="wiz.open"></a></div></section>
</main>
<div id="toast" role="status" aria-live="polite"></div>
<div id="overlay" hidden></div>
<script>
/*I18N_JS*/
/*COMMON_JS*/
const WPROVS=["groq","openai","openrouter","ollama"]; let PRESETS={}, step=1, doneKey=null;
function show(n){ step=n; [1,2,3].forEach(i=>{ $("s"+i).hidden=i!==n; $("d"+i).className=i<=n?"on":""; $("n"+i).textContent=t("wiz.step",{n:i}); });
  const f=$("s"+n).querySelector("h1"); if(f){ f.tabIndex=-1; f.focus(); } }
function prov(){ const i=document.querySelector('input[name="prov"]:checked'); return i?i.value:"groq"; }
function drawProvs(){ const box=$("provs"), cur=prov(); box.replaceChildren();
  WPROVS.forEach(k=>{ const l=el("label"), i=el("input"); i.type="radio"; i.name="prov"; i.value=k; i.checked=k===cur; i.onchange=provChanged; l.append(i, el("span",null,tr("prov",k))); box.append(l); }); provChanged(); }
function provChanged(){ const p=PRESETS[prov()]||{}; const g=$("getkey"); g.href=p.keys_url||"#"; g.hidden=!p.keys_url || !p.key; $("key").disabled=!p.key; if(!p.key) $("key").value=""; $("test").textContent=""; }
function pickBtns(){ document.querySelectorAll("[data-pick]").forEach(b=>{ b.classList.toggle("on",b.dataset.pick===LANG); b.setAttribute("aria-pressed",String(b.dataset.pick===LANG)); }); }
document.querySelectorAll("[data-pick]").forEach(b=>b.onclick=()=>{ setLang(b.dataset.pick); pickBtns(); });
$("next1").onclick=async()=>{ try{ await api("POST","/app/setup",{lang:LANG}); }catch(e){ return fail(e); } show(2); };
$("back2").onclick=()=>show(1);
$("testb").onclick=async()=>{ const line=$("test"); line.className="testline"; line.textContent=t("set.f.testing");
  try{ const r=await api("POST","/app/providers/test",{provider:prov(),key:$("key").value.trim()}); line.className="testline "+(r.ok?"ok":"bad"); line.textContent=tr("test",r.code,{http:r.http_status||"?"}); }
  catch(e){ fail(e); line.textContent=""; } };
$("save2").onclick=async()=>{ const k=prov(), p=PRESETS[k]||{}, key=$("key").value.trim();
  if(p.key && !key){ const line=$("test"); line.className="testline bad"; line.textContent=t("test.missing"); $("key").focus(); return; }
  const name=tr("prov",k).split(" (")[0];
  try{ await api("POST","/app/providers",{provider:k,name,categories:["text","code"],...(key?{key}:{})}); await api("POST","/app/setup",{demo:false,done:true,lang:LANG}); }
  catch(e){ return fail(e); }
  $("key").value=""; doneKey=name; $("donemsg").textContent=t("wiz.doneKey",{name}); show(3); };
$("demo").onclick=async()=>{ try{ await api("POST","/app/setup",{demo:true,done:true,lang:LANG}); }catch(e){ return fail(e); } doneKey=null; $("donemsg").textContent=t("wiz.doneDemo"); show(3); };
onLang=()=>{ pickBtns(); drawProvs(); show(step); if(step===3) $("donemsg").textContent=doneKey?t("wiz.doneKey",{name:doneKey}):t("wiz.doneDemo"); };
(async()=>{ try{ await status(); }catch(e){ if(e.status===401){ location.href="/connect"; return; } }
  if(!ST.available || !ST.editable){ [1,2,3].forEach(i=>$("s"+i).hidden=true); $("slock").hidden=false; return; }
  try{ PRESETS=(await api("GET","/app/settings")).presets; }catch(e){}
  pickBtns(); drawProvs(); show(1); })();
</script></body></html>
"""


def _finish(page: str) -> str:
    page = page.replace("/*THEME*/", BASE_CSS).replace("/*COMMON_CSS*/", COMMON_CSS).replace("/*NAV_CSS*/", NAV_CSS)
    page = page.replace("/*NAV*/", NAV_HTML).replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", LANG_SWITCH)
    return page.replace("/*I18N_JS*/", I18N_JS).replace("/*NAV_JS*/", NAV_JS).replace("/*COMMON_JS*/", COMMON_JS)


SETTINGS_PAGE = _finish(SETTINGS_PAGE)
WELCOME_PAGE = _finish(WELCOME_PAGE)
