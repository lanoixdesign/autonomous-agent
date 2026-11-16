"""The Developer page (/dev): start a small project from a template (static website or Python program), ask a
Coder + Tester team to build it, preview a website in a sandboxed iframe, run the tests (always in the
sandbox) and download the project as a .zip. Plain HTML + JS, no external resources, EN/FR, light/dark."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH
from .theme import BASE_CSS, MENU_BTN, NAV_CSS, NAV_HTML, NAV_JS, THEME_BTN, TIP_CSS, TIP_JS, sidebar

DEV_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="dev.pageTitle">autonomous-agent · developer</title>
<style>
/*THEME*/
 *{box-sizing:border-box} body{margin:0;font-size:15px;line-height:1.5;min-height:100vh}
 main{max-width:1080px;margin:0 auto;padding:20px 18px 48px}
 h1{color:var(--text);font-size:27px;margin:4px 0 6px} h2{color:var(--text);font-size:18px;margin:0 0 10px}
 .intro{color:var(--soft);max-width:720px;margin:0 0 12px}
 .pill{display:inline-flex;gap:8px;align-items:center;padding:7px 14px;border-radius:999px;font-size:13.5px;font-weight:600;
  background:rgba(var(--ok-rgb),0.072);border:1px solid rgba(var(--ok-rgb),0.27);color:var(--t-ok)}
 .pill.off{background:rgba(var(--warn-rgb),0.072);border-color:rgba(var(--warn-rgb),0.3);color:var(--t-warn)}
 .grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;margin-top:14px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:0 10px 30px var(--shadow)}
 label.f{display:block;font-weight:700;color:var(--text);margin:8px 0 5px;font-size:13.5px}
 input[type=text],textarea,select{width:100%;padding:11px 12px;font:15px var(--font)} textarea{min-height:92px;resize:vertical}
 .kinds{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}
 .kind{position:relative;display:block;border:1px solid var(--line2);border-radius:14px;padding:12px;cursor:pointer;background:var(--sunk)}
 .kind input{position:absolute;opacity:0;width:1px;height:1px} .kind b{display:block;color:var(--strong);font-size:15px} .kind span{font-size:12.5px;color:var(--muted)}
 .kind:has(input:checked){border-color:var(--blue);} .kind:has(input:focus-visible){outline:2px solid var(--blue)}
 .btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:10px 16px;border-radius:999px;border:1px solid var(--line2);background:var(--panel2);
  color:var(--text);font:600 14px var(--font);cursor:pointer;min-height:42px;text-decoration:none}
 .btn:hover{border-color:var(--blue)} .btn:disabled{opacity:.5;cursor:default}
 .btn.primary{background:var(--accent);border-color:transparent;color:#fff}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
 .muted{color:var(--muted);font-size:13px}
 #plist{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
 .proj{background:var(--sunk);border:1px solid var(--line);border-radius:16px;padding:14px}
 .proj .h{display:flex;gap:10px;align-items:center} .proj .ic{font-size:26px} .proj b{color:var(--strong);font-size:16px;word-break:break-word}
 .proj .meta{font-size:12.5px;color:var(--muted)} .proj .acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px} .proj .btn{min-height:38px;padding:8px 12px;font-size:13px}
 .res{margin-top:10px;font-size:13.5px;border-radius:12px;padding:10px 12px;background:var(--panel2);border:1px solid var(--line2)}
 .res.ok{border-color:rgba(var(--ok-rgb),0.3);color:var(--t-ok)} .res.bad{border-color:rgba(var(--bad-rgb),0.33);color:var(--t-bad)}
 .res ul{margin:6px 0 0 18px;padding:0;color:var(--soft)} .res pre{white-space:pre-wrap;font:12px var(--mono);color:var(--soft);max-height:220px;overflow:auto;margin:6px 0 0}
 #pv{margin-top:14px} #pv[hidden]{display:none}
 .pvbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap} .pvbar h2{margin:0;flex:1;min-width:160px}
 .pvbar .btn{min-height:36px;padding:6px 12px;font-size:13px} .pvbar .btn.on{border-color:var(--blue);background:rgba(var(--accent-rgb),0.108)}
 .frame{margin-top:10px;display:flex;justify-content:center;background:repeating-conic-gradient(var(--panel2) 0% 25%,var(--sunk) 0% 50%) 50%/22px 22px;border-radius:14px;padding:12px;border:1px solid var(--line)}
 iframe{width:100%;height:520px;border:1px solid var(--line2);border-radius:10px;background:#fff;transition:width .2s}
 iframe.mob{width:390px;max-width:100%;height:640px}
 #toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--panel2);color:var(--text);border:1px solid var(--line2);border-radius:999px;
  padding:10px 18px;font-weight:600;box-shadow:0 10px 30px var(--shadow);opacity:0;pointer-events:none;transition:opacity .2s;z-index:50;max-width:92vw}
 #toast.on{opacity:1} #toast.err{border-color:var(--bad);color:var(--t-bad)}
 .banner{padding:10px 14px;border-radius:12px;background:rgba(var(--warn-rgb),0.072);color:var(--t-warn);margin-top:10px}
 .banner[hidden]{display:none}
 @media (max-width:760px){ main{padding:12px 10px 40px} .grid{grid-template-columns:1fr} h1{font-size:23px} .kinds{grid-template-columns:1fr}
  iframe{height:460px} #plist{grid-template-columns:1fr} input,select,textarea{font-size:16px!important} }
/*TIP_CSS*/
/*NAV_CSS*/
/*LANG_CSS*/
</style></head><body data-page="dev">
/*SIDEBAR*/
<header class="apphead mob">/*MENU_BTN*/<h1 data-i18n="nav.dev"></h1></header>
<main>
 <h1 data-i18n="dev.title"></h1>
 <p class="intro" data-i18n="dev.intro"></p>
 <span id="sbx" class="pill"></span>
 <div id="nows" class="banner" hidden data-i18n="dev.noWs"></div>
 <div id="nopy" class="banner" hidden data-i18n="dev.nopython"></div>
 <div class="grid" id="top">
  <section class="card" aria-labelledby="hnew"><h2 id="hnew" data-i18n="dev.new"></h2>
   <label class="f" for="pname" data-i18n="dev.name"></label><input id="pname" type="text" maxlength="60" data-i18n-placeholder="dev.namePh" autocomplete="off">
   <div class="kinds" role="radiogroup" data-i18n-aria="dev.new">
    <label class="kind"><input type="radio" name="kind" value="web" checked><b data-i18n="dev.kind.web"></b><span data-i18n="dev.kindd.web"></span></label>
    <label class="kind"><input type="radio" name="kind" value="python"><b data-i18n="dev.kind.python"></b><span data-i18n="dev.kindd.python"></span></label>
   </div>
   <div class="row"><button id="create" class="btn primary" type="button" data-i18n="dev.create"></button></div>
  </section>
  <section class="card" aria-labelledby="hask"><h2 id="hask" data-i18n="dev.ask"></h2>
   <label class="f" for="aproj" data-i18n="dev.askProject"></label><select id="aproj"></select>
   <label class="f" for="atext" style="position:absolute;left:-9999px" data-i18n="dev.ask"></label>
   <textarea id="atext" data-i18n-placeholder="dev.askPh" style="margin-top:10px"></textarea>
   <p class="muted" data-i18n="dev.askHelp"></p>
   <div class="row"><button id="go" class="btn primary" type="button" data-i18n="dev.askGo"></button></div>
  </section>
 </div>
 <section id="pv" class="card" hidden aria-labelledby="pvt">
  <div class="pvbar"><h2 id="pvt"></h2>
   <button id="pvd" class="btn on" type="button" data-i18n="dev.pv.desktop"></button><button id="pvm" class="btn" type="button" data-i18n="dev.pv.mobile"></button>
   <button id="pvr" class="btn" type="button" data-i18n="dev.pv.reload"></button><a id="pvo" class="btn" target="_blank" rel="noopener noreferrer" data-i18n="dev.pv.open"></a>
   <button id="pvx" class="btn" type="button" data-i18n="dev.pv.close"></button></div>
  <div class="frame"><iframe id="pvf" sandbox="allow-scripts allow-forms allow-modals" referrerpolicy="no-referrer" loading="lazy"></iframe></div>
  <p class="muted" data-i18n="dev.pv.safe"></p>
 </section>
 <section class="card" style="margin-top:14px" aria-labelledby="hmine"><h2 id="hmine" data-i18n="dev.mine"></h2><div id="plist"></div></section>
</main>
<div id="toast" role="status" aria-live="polite"></div>
<script>
/*I18N_JS*/
/*NAV_JS*/
/*TIP_JS*/
const $ = id => document.getElementById(id);
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
function tokH(){ const h={}; let tk=""; try{ tk=sessionStorage.getItem("harnessToken")||""; }catch(e){} if(tk) h.Authorization="Bearer "+tk; return h; }
async function api(method, path, body){
  const h=Object.assign({"Content-Type":"application/json"}, tokH());
  const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  const j=await r.json().catch(()=>({})); if(!r.ok){ const e=new Error(j.error||("HTTP "+r.status)); e.status=r.status; e.body=j; throw e; } return j; }
let toastT=null;
function toast(msg,bad){ const b=$("toast"); b.textContent=msg; b.className="on"+(bad?" err":""); clearTimeout(toastT); toastT=setTimeout(()=>{ b.className=""; }, bad?6000:2600); }
function errText(e){ const c=e&&e.body&&e.body.code; return (c && I18N.en["dev.err."+c]!=null) ? t("dev.err."+c) : String(e&&e.message||e); }
function fail(e){ if(e && e.status===401){ location.href="/connect"; return; } toast(errText(e), true); }
let D={projects:[],available:true,sandbox:true}, RES={}, PV=null;
async function load(){ try{ D=await api("GET","/dev/projects"); }catch(e){ fail(e); return; } draw(); }
function draw(){
  const s=$("sbx"); s.textContent=t(D.sandbox?"dev.sbxOn":"dev.sbxOff"); s.className="pill"+(D.sandbox?"":" off");
  $("nows").hidden=D.available!==false; $("nopy").hidden=D.python!==false; $("top").hidden=D.available===false;
  const sel=$("aproj"), keep=sel.value; sel.replaceChildren();
  D.projects.forEach(p=>{ const o=el("option",null,p.name+" · "+tr("dev.kindl",p.kind)); o.value=p.name; sel.append(o); });
  if(keep && D.projects.some(p=>p.name===keep)) sel.value=keep;
  const box=$("plist"); box.replaceChildren();
  if(!D.projects.length){ box.append(el("p","muted",t("dev.none"))); return; }
  D.projects.forEach(p=>{ const c=el("div","proj"), h=el("div","h"), ic=el("span","ic",p.kind==="web"?"🌐":(p.kind==="python"?"🐍":"📁")), tx=el("div");
    ic.setAttribute("aria-hidden","true"); tx.append(el("b",null,p.name), el("div","meta",tr("dev.kindl",p.kind)+" · "+t("dev.files",{n:p.files})+" · "+p.path));
    h.append(ic,tx); c.append(h); const a=el("div","acts");
    if(p.preview){ const b=el("button","btn",t("dev.preview")); b.type="button"; b.onclick=()=>preview(p); a.append(b); }
    if(p.kind!=="other"){ const b=el("button","btn",t("dev.test")); b.type="button"; b.onclick=()=>runTests(p.name,b); a.append(b); }
    const z=el("button","btn",t("dev.zip")); z.type="button"; z.onclick=()=>download(p.name); a.append(z);
    const im=el("button","btn",t("dev.improve")); im.type="button"; im.onclick=()=>improve(p.name); a.append(im);
    c.append(a); if(RES[p.name]) c.append(resBox(RES[p.name], p.name)); else { const r=el("div"); r.id="res-"+p.name; c.append(r); }
    box.append(c); });
  if(PV){ const p=D.projects.find(x=>x.name===PV.name); if(p){ $("pvt").textContent=t("dev.pv.title",{name:p.name}); } }
}
function resBox(r,name){ const b=el("div","res "+(r.pending?"":(r.ok?"ok":"bad"))); b.id="res-"+name; b.setAttribute("role","status");
  if(r.pending){ b.textContent=t("dev.testing"); return b; }
  if(r.error){ b.textContent=t("dev.test.err",{msg:r.error}); return b; }
  if(r.kind==="web"){ b.append(el("div",null, r.ok?t("dev.test.okWeb"):t("dev.test.badWeb",{n:(r.problems||[]).length})));
    if(!r.ok){ const u=el("ul"); (r.problems||[]).slice(0,12).forEach(x=>u.append(el("li",null,x))); b.append(u); } return b; }
  const s=r.summary||{passed:0,failed:0};
  b.append(el("div",null, r.ok ? (r.runner==="compile"?t("dev.test.okCompile"):t("dev.test.ok",{passed:s.passed})) : (s.failed? t("dev.test.bad",{failed:s.failed}) : t("dev.test.err",{msg:(r.problems||[])[0]||("exit "+r.exit)}))));
  if(r.output){ const d=el("details"), sm=el("summary",null,t("dev.details")), pre=el("pre",null,r.output.slice(-6000)); d.append(sm,pre); b.append(d); }
  return b; }
function showRes(name,r){ RES[name]=r; const cur=$("res-"+name); if(cur) cur.replaceWith(resBox(r,name)); }
async function runTests(name,btn){ btn.disabled=true; showRes(name,{pending:true});
  try{ showRes(name, await api("POST","/dev/test",{project:name})); }catch(e){ showRes(name,{error:errText(e)}); }
  btn.disabled=false; }
async function download(name){
  try{ const r=await fetch("/dev/zip?project="+encodeURIComponent(name),{headers:tokH()});
    if(!r.ok){ const j=await r.json().catch(()=>({})); const e=new Error(j.error||("HTTP "+r.status)); e.status=r.status; e.body=j; throw e; }
    const u=URL.createObjectURL(await r.blob()), a=el("a"); a.href=u; a.download=name+".zip"; document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(u),5000); }
  catch(e){ fail(e); } }
function preview(p){ PV={name:p.name,url:p.preview}; $("pv").hidden=false; $("pvt").textContent=t("dev.pv.title",{name:p.name});
  $("pvf").title=t("dev.pv.title",{name:p.name}); $("pvf").src=p.preview+"?t="+Date.now(); $("pvo").href=p.preview;
  $("pv").scrollIntoView({behavior:"smooth",block:"start"}); }
function device(mob){ $("pvf").classList.toggle("mob",mob); $("pvm").classList.toggle("on",mob); $("pvd").classList.toggle("on",!mob);
  $("pvm").setAttribute("aria-pressed",String(mob)); $("pvd").setAttribute("aria-pressed",String(!mob)); }
$("pvd").onclick=()=>device(false); $("pvm").onclick=()=>device(true);
$("pvr").onclick=()=>{ if(PV) $("pvf").src=PV.url+"?t="+Date.now(); };
$("pvx").onclick=()=>{ $("pv").hidden=true; $("pvf").removeAttribute("src"); PV=null; };
function improve(name){ $("aproj").value=name; const a=$("atext"); if(!a.value.trim()) a.value=t("dev.improveText",{name}); a.focus(); a.scrollIntoView({behavior:"smooth",block:"center"}); }
$("create").onclick=async()=>{ const name=$("pname").value.trim(), kind=(document.querySelector('input[name="kind"]:checked')||{}).value;
  if(!name){ toast(t("dev.err.bad_name"),true); $("pname").focus(); return; }
  $("create").disabled=true;
  try{ const p=await api("POST","/dev/projects",{name,kind,lang:LANG}); $("pname").value=""; toast(t("dev.created",{name:p.name})); await load(); $("aproj").value=p.name; $("atext").focus(); }
  catch(e){ fail(e); } $("create").disabled=false; };
$("go").onclick=async()=>{ const proj=$("aproj").value, text=$("atext").value.trim();
  if(!proj){ toast(t("dev.needProject"),true); return; } if(!text){ toast(t("dev.needText"),true); $("atext").focus(); return; }
  $("go").disabled=true;
  try{ const r=await api("POST","/tasks",{task:text,dev:proj,lang:LANG}); toast(t("dev.sent")); location.href="/#"+r.id; }
  catch(e){ fail(e); $("go").disabled=false; } };
onLang=draw; load(); setInterval(()=>{ if(!document.hidden) load(); }, 15000);
</script></body></html>
"""
DEV_PAGE = DEV_PAGE.replace("/*THEME*/", BASE_CSS).replace("/*TIP_CSS*/", TIP_CSS).replace("/*NAV_CSS*/", NAV_CSS)
DEV_PAGE = DEV_PAGE.replace("/*SIDEBAR*/", sidebar()).replace("/*MENU_BTN*/", MENU_BTN).replace("/*NAV*/", NAV_HTML).replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", THEME_BTN + LANG_SWITCH)
DEV_PAGE = DEV_PAGE.replace("/*I18N_JS*/", I18N_JS).replace("/*NAV_JS*/", NAV_JS).replace("/*TIP_JS*/", TIP_JS)
