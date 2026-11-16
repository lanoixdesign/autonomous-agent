"""Shared "neon" look for the harness pages (chat, dashboard, connect): dark background with a soft purple
glow, neon blue / purple accents, visible keyboard focus. Plain CSS, no external resources (system fonts;
Inter is used if it is installed). Animations are turned off for `prefers-reduced-motion: reduce`."""

BASE_CSS = r"""
 :root{--bg:#05050B;--panel:#14141C;--panel2:#1E1E24;--line:#2A2A35;--text:#FFFFFF;--soft:#D1D5DB;--muted:#9CA3AF;
  --blue:#00D4FF;--blue2:#2563EB;--purple:#9D00FF;--purple2:#B92BFF;--ok:#22C55E;--warn:#F59E0B;--bad:#F87171;
  --font:Inter,"Inter var",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color-scheme:dark;
  --strong:#FFFFFF;--sunk:#0D0D14;--card:rgba(20,20,28,.92);--card2:rgba(20,20,28,.85);--chip:#2A2A35;--line2:#3A3A46;
  --t-bad:#FCA5A5;--t-warn:#FCD34D;--t-violet:#E9D5FF;--t-ok:#BBF7D0;--t-cyan:#BAF3FF;--hover:#7FE9FF;--shadow:rgba(0,0,0,.35)}
 /* Day theme: light surfaces, dark text, accents darkened for WCAG AA contrast (>= 4.5:1 on white) */
 html[data-theme=light]{--bg:#F4F6FB;--panel:#FFFFFF;--panel2:#EEF1F7;--line:#D5DBE6;--line2:#BAC3D3;--text:#0F172A;--strong:#0B1020;
  --soft:#334155;--muted:#526075;--blue:#0369A1;--blue2:#2563EB;--purple:#7C3AED;--purple2:#9333EA;--ok:#166534;--warn:#92400E;--bad:#B91C1C;
  --sunk:#FFFFFF;--card:rgba(255,255,255,.97);--card2:rgba(255,255,255,.92);--chip:#E4E8F0;
  --t-bad:#B91C1C;--t-warn:#92400E;--t-violet:#6D28D9;--t-ok:#166534;--t-cyan:#0369A1;--hover:#075985;--shadow:rgba(15,23,42,.10);color-scheme:light}
 html[data-theme=light] body{background:radial-gradient(ellipse 70% 55% at 50% 40%,rgba(124,58,237,.07),rgba(37,99,235,.04) 45%,transparent 75%),var(--bg)}
 html[data-theme=light] input::placeholder,html[data-theme=light] textarea::placeholder{color:#64748B}
 html[data-theme=light] section,html[data-theme=light] .card,html[data-theme=light] .step,html[data-theme=light] .ap{box-shadow:0 4px 18px var(--shadow)!important}
 html[data-theme=light] :focus-visible{outline-color:#2563EB;box-shadow:0 0 0 4px rgba(37,99,235,.25)}
 h1[tabindex="-1"]:focus,h1[tabindex="-1"]:focus-visible,h2[tabindex="-1"]:focus-visible{outline:none;box-shadow:none}
 html[data-theme=light] .grey{background:#E4E8F0!important;border-color:#BAC3D3!important;color:#0F172A!important}
 .themebtn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;min-width:34px;padding:0;border-radius:50%;
  border:1px solid var(--line2);background:var(--sunk);color:var(--text);font-size:17px;line-height:1;cursor:pointer;margin-right:6px}
 .themebtn:hover{border-color:var(--blue);box-shadow:0 0 10px rgba(0,212,255,.3)}
 .themebtn::before{content:"\263E"} html[data-theme=light] .themebtn::before{content:"\2600\FE0E";color:#B45309}
 html{background:var(--bg)}
 body{font-family:var(--font);color:var(--soft);
  background:radial-gradient(ellipse 70% 55% at 50% 45%,rgba(157,0,255,.18),rgba(157,0,255,.06) 45%,transparent 75%),var(--bg);
  background-attachment:fixed}
 a{color:var(--blue)} a:hover{color:var(--hover)}
 :focus{outline:none}
 :focus-visible{outline:2px solid var(--blue);outline-offset:2px;box-shadow:0 0 0 4px rgba(0,212,255,.25)}
 input,textarea,select{background:var(--sunk);color:var(--text);border:1px solid var(--line);border-radius:10px}
 input::placeholder,textarea::placeholder{color:#6B7280}
 input:focus-visible,textarea:focus-visible,select:focus-visible{border-color:var(--blue);outline:none;box-shadow:0 0 0 3px rgba(0,212,255,.25)}
 ::-webkit-scrollbar{width:10px;height:10px} ::-webkit-scrollbar-thumb{background:var(--chip);border-radius:6px;border:2px solid transparent;background-clip:padding-box}
 ::-webkit-scrollbar-track{background:transparent}
 #lang{border-color:var(--line2)!important;background:var(--sunk)} #lang button{color:var(--soft)} #lang button.on{background:linear-gradient(90deg,var(--blue2),var(--purple))!important;color:#fff}
 @media (prefers-reduced-motion: reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
"""

# Dashboard: the existing layout, recoloured.
DASH_CSS = r"""
 body{background-color:var(--bg)}
 header{background:var(--card2)!important;border-bottom:1px solid var(--line);backdrop-filter:blur(8px)}
 header h1{color:var(--text)} header a.c{color:var(--blue)!important}
 section{background:var(--card)!important;border:1px solid var(--line)!important;border-radius:16px!important;box-shadow:0 10px 30px rgba(0,0,0,.35)}
 h2{color:var(--t-violet)!important}
 button{background:var(--panel2);color:var(--text);border:1px solid var(--line2);border-radius:999px;padding:6px 14px;font-family:var(--font)}
 button:hover{border-color:var(--blue)} #stopall{background:#7F1D1D!important;border-color:#B91C1C!important;border-radius:999px!important}
 .task{color:var(--soft)} .task:hover{background:var(--panel2)!important} .task.sel{border-color:var(--blue)!important;background:rgba(37,99,235,.15)!important}
 .st{background:var(--chip)!important;color:var(--soft)} .st.running,.st.queued,.st.cancelling{background:rgba(0,212,255,.15)!important;color:var(--blue)}
 .st.done{background:rgba(34,197,94,.15)!important;color:var(--ok)}
 .st.error,.st.cancelled,.st.stopped,.st.interrupted,.st.denied,.st.expired{background:rgba(248,113,113,.15)!important;color:var(--bad)}
 .agent{background:var(--sunk)!important;border-left:3px solid var(--purple2)!important;border-radius:8px;box-shadow:0 0 12px rgba(157,0,255,.18)}
 .agent small,.muted{color:var(--muted)!important} .ev{border-bottom:1px solid var(--line)!important} .ev b{color:var(--blue)!important}
 .ap{background:var(--panel2)!important;border:1px solid var(--line2)!important;border-radius:16px!important;box-shadow:0 12px 30px rgba(0,0,0,.45)}
 .ap button{border-radius:999px} .ap button.ok,.ap button:first-of-type{background:var(--blue2);border-color:var(--blue2)}
 td,th{border-bottom:1px solid var(--line)!important;color:var(--soft)} tr.conv td{background:var(--panel2)!important;color:var(--text)}
 .sched{border-color:var(--line)!important;border-radius:12px!important}
 pre{color:var(--soft)}
"""

# /connect page.
CONNECT_CSS = r"""
 header{background:var(--card2)!important;border-bottom:1px solid var(--line)} header h1{color:var(--text)}
 section{background:var(--card)!important;border:1px solid var(--line)!important;border-radius:20px!important;box-shadow:0 10px 30px rgba(0,0,0,.35)}
 h2{color:var(--text)} .muted{color:var(--muted)!important}
 button,.btn{background:var(--blue2)!important;color:#fff;border-radius:999px!important;font-family:var(--font)!important;box-shadow:0 0 18px rgba(37,99,235,.35)}
 button.lite{background:#374151!important;color:#fff!important;box-shadow:none} button.danger{background:#7F1D1D!important;color:#FECACA!important;box-shadow:none}
 #qr svg{background:#fff;padding:6px;box-shadow:0 0 28px rgba(0,212,255,.35)}
 #qrurl{background:var(--sunk)!important;color:var(--soft)} code{background:var(--panel2)!important;color:var(--soft)}
 .ok{color:var(--ok)!important} .err{color:var(--bad)!important} .warn{background:rgba(245,158,11,.12)!important;color:var(--t-warn)}
 header a{color:var(--blue)!important}
 #lang button{background:transparent!important;box-shadow:none!important;width:auto;margin:0;padding:4px 9px;border-radius:0!important;font:600 11px var(--font)!important}
 #lang button.on{background:linear-gradient(90deg,var(--blue2),var(--purple))!important}
"""

# Shared by the chat and the dashboard: approvals and work-trace lines in plain language (v0.6), plus the
# original short question / reason helpers. ROLES maps agent ids (root.1…) to the role the agent gave them.
APPROVAL_JS = r"""
let ROLES = {};
function cutS(s,n){ s=String(s==null?"":s); return s.length>n ? s.slice(0,n)+"…" : s; }
function hostOf(u){ try{ return new URL(u).host; }catch(e){ return cutS(u,40); } }
function roleOf(task){ const s=String(task||""), m=/^\s*([^:\n]{1,32}):/.exec(s); return m ? m[1].trim() : ""; }
function rolesOf(g){ const ts=Array.isArray(g.tasks) ? g.tasks : (g.task!=null ? [g.task] : []);
  return ts.map(x=>roleOf(typeof x==="string" ? x : (x && (x.role||x.name||x.task)) || "")).filter(Boolean); }
function agentWho(id){ if(!id || id==="root") return t("who.agent");
  return ROLES[id] ? t("who.helperRole",{role:ROLES[id]}) : t("who.helperN",{n:id.split(".").slice(1).join(".")}); }
function agentShort(id){ if(!id || id==="root") return t("who.short.root");
  return ROLES[id] || t("who.short.helper",{n:id.split(".").slice(1).join(".")}); }
// What an agent wants to do / did, as one sentence. kind: "human" (approval card) or "simple" (trace line).
function plain(kind, tool, g, agent, category){
  g=g||{}; const who=agentWho(agent), p=cutS(g.path||"",60);
  if(kind==="human"){
    if(tool==="spawn_agents"){ const r=rolesOf(g), n=Array.isArray(g.tasks)?g.tasks.length:1;
      return r.length ? t("human.spawnMany",{who,n,names:r.join(", ")}) : t("human.spawnManyNoNames",{who,n}); }
    if(tool==="spawn_agent"){ const r=rolesOf(g); return r.length ? t("human.spawn",{who,names:r[0]}) : t("human.spawnNoName",{who}); }
  }
  const k={read_file:"read",list_files:"list",search_files:"searchFiles",write_file:"write",edit_file:"edit",web_fetch:"fetch",
    web_search:"search",shell:"shell",memory_write:"memory",memory_forget:"forget",memory_recall:"recall",load_skill:"skill",list_skills:"skill",
    github_write:"github",github_get:kind==="human"?"githubRead":"github"}[tool];
  const v={who,path:p,q:cutS(g.query||g.pattern||"",50),host:hostOf(g.url),tool};
  if(kind==="human" && tool==="github_write") v.path=cutS(g.path||g.repo||"",60);
  if(k && !(kind==="human" && k==="recall")) return tr(kind,k,v);
  if(kind==="human" && (category==="send" || category==="spend")) return tr("human",category,v);
  return tr(kind,"other",v);
}
function askText(a){ return plain("human", a.tool, a.args, a.agent, a.category); }
function reasonText(r){
  r=String(r||""); let m;
  const tail=s=>!s ? "" : (/--yolo ignored/.test(s) ? t("reason.yolo") : (/upgraded by --yolo/.test(s) ? t("reason.upgraded") : ""));
  if((m=/^category default '([\w-]+): (\w+)'(;.*)?$/.exec(r))) return t("reason.category",{category:tr("cat",m[1]),mode:tr("mode",m[2])})+tail(m[3]);
  if((m=/^tool rule '([\w-]+): (\w+)'(;.*)?$/.exec(r))) return t("reason.tool",{tool:m[1],mode:tr("mode",m[2])})+tail(m[3]);
  return r;
}
"""

# "?" tooltips: <button type="button" class="tip" data-tip="tip.xxx"></button> next to a term.
TIP_CSS = r"""
 .tip{display:inline-flex!important;align-items:center;justify-content:center;width:20px!important;height:20px;min-height:20px!important;padding:0!important;margin:0 4px;
  border-radius:50%!important;border:1px solid rgba(0,212,255,.55)!important;background:rgba(0,212,255,.10)!important;color:var(--blue)!important;
  font:700 12px var(--font)!important;cursor:pointer;vertical-align:middle;position:relative;box-shadow:none!important}
 .tip::before{content:"?"} .tip:hover{background:rgba(0,212,255,.22)!important}
 .tipbox{position:absolute;z-index:90;max-width:300px;background:var(--panel2);color:var(--text);border:1px solid rgba(0,212,255,.55);border-radius:12px;
  padding:10px 12px;font:500 13px/1.45 var(--font);box-shadow:0 12px 30px rgba(0,0,0,.55);text-align:left}
 html.big body{zoom:1.18}
 html.big body.fullh{height:calc(100vh / 1.18)}
"""
TIP_JS = r"""
(function(){
  const BIG="bigText"; try{ if(localStorage.getItem(BIG)==="1") document.documentElement.classList.add("big"); }catch(e){}
  window.setBig=function(on){ document.documentElement.classList.toggle("big",!!on); try{ localStorage.setItem(BIG,on?"1":"0"); }catch(e){} };
  let open=null;
  function close(){ if(open){ open.box.remove(); open.btn.setAttribute("aria-expanded","false"); open=null; } }
  function show(b){ close(); const box=document.createElement("div"); box.className="tipbox"; box.setAttribute("role","tooltip");
    box.id="tipbox"; box.textContent=t(b.dataset.tip); document.body.append(box);
    const r=b.getBoundingClientRect(), z=parseFloat(getComputedStyle(document.body).zoom)||1;
    const x=Math.min(r.left/z, (document.documentElement.clientWidth/z)-310), y=r.bottom/z+6;
    box.style.left=Math.max(8,x+window.scrollX/z)+"px"; box.style.top=(y+window.scrollY/z)+"px";
    b.setAttribute("aria-expanded","true"); b.setAttribute("aria-describedby","tipbox"); open={box,btn:b}; }
  window.initTips=function(root){ (root||document).querySelectorAll("button.tip").forEach(b=>{ if(b._tip) return; b._tip=1; b.type="button";
    b.setAttribute("aria-label",t("tip.label")); b.setAttribute("aria-expanded","false");
    b.addEventListener("click",ev=>{ ev.preventDefault(); ev.stopPropagation(); if(open && open.btn===b) close(); else show(b); }); }); };
  document.addEventListener("click",close); document.addEventListener("keydown",e=>{ if(e.key==="Escape") close(); });
  window.addEventListener("scroll",close,true);
  initTips();
})();
"""

# Navigation shared by every page: Chat | Dashboard | Settings | Help | Connect. Plain links, so the browser's
# back / forward buttons and history work as usual. The current page is marked from <body data-page>.
NAV_HTML = ('<nav class="tabs" data-i18n-aria="nav.label">'
            '<a href="/" data-nav="chat" data-i18n="nav.chat"></a>'
            '<a href="/dashboard" data-nav="dashboard" data-i18n="nav.dashboard"></a>'
            '<a href="/settings" data-nav="settings" data-i18n="nav.settings"></a>'
            '<a href="/help" data-nav="help" data-i18n="nav.help"></a>'
            '<a href="/connect" data-nav="connect" data-i18n="nav.connect"></a></nav>')

NAV_CSS = r"""
 nav.tabs{display:inline-flex;gap:3px;padding:3px;border:1px solid var(--line);border-radius:999px;background:var(--card2);flex-shrink:0}
 nav.tabs a{padding:6px 14px;border-radius:999px;color:var(--soft)!important;text-decoration:none;font:600 13px var(--font);white-space:nowrap;line-height:1.3}
 nav.tabs a:hover{color:var(--strong)!important;background:var(--panel2)}
 nav.tabs a.on{color:#fff!important;background:linear-gradient(90deg,var(--blue2),var(--purple));box-shadow:0 0 14px rgba(37,99,235,.35)}
 .apphead{display:flex;align-items:center;gap:12px;padding:10px 16px;padding-top:max(10px,env(safe-area-inset-top));flex-wrap:wrap;
  background:var(--card2)!important;border-bottom:1px solid var(--line);backdrop-filter:blur(10px);position:sticky;top:0;z-index:20}
 .apphead .brand{font:700 15px var(--font);color:var(--text);white-space:nowrap}
 .apphead .sp{flex:1}
 a.back{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;border:1px solid rgba(0,212,255,.45);color:var(--blue)!important;
  text-decoration:none;font:600 13px var(--font);white-space:nowrap;background:rgba(0,212,255,.08)}
 a.back:hover{background:rgba(0,212,255,.16)}
 @media (max-width:760px){
  nav.tabs{display:flex;overflow-x:auto;max-width:100%;order:10;flex:1 1 100%;justify-content:space-between}
  nav.tabs a{padding:9px 10px;min-height:38px;flex:1;text-align:center;font-size:13px}
  .apphead{gap:8px;padding:8px 10px}
 }
"""

NAV_JS = r"""
document.querySelectorAll("nav.tabs a").forEach(a => { const on = a.dataset.nav === document.body.dataset.page;
  a.classList.toggle("on", on); if(on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
"""


# Day / night switch: one round button (moon at night, sun by day) in every page header and the phone menu.
THEME_BTN = '<button type="button" class="themebtn" data-theme-btn></button>'

# Runs in <head> before the first paint: picks the theme (saved choice, else the Settings default, "auto" = system),
# sets <html data-theme>, follows the system when on "auto", and wires every .themebtn.
THEME_HEAD = r"""<script>(function(){var D="__THEME_DEFAULT__",K="theme",V=["auto","light","dark"],R=document.documentElement;
var mq=window.matchMedia?window.matchMedia("(prefers-color-scheme: light)"):null;
function pref(){try{var v=localStorage.getItem(K);if(V.indexOf(v)>=0)return v;}catch(e){}return V.indexOf(D)>=0?D:"auto";}
function eff(p){return p==="auto"?(mq&&mq.matches?"light":"dark"):p;}
function label(){var e=R.getAttribute("data-theme"),k=e==="light"?"theme.toDark":"theme.toLight",s=k;
 try{if(typeof t==="function"){s=t(k);}}catch(x){}
 var b=document.querySelectorAll("[data-theme-btn]");for(var i=0;i<b.length;i++){b[i].setAttribute("aria-label",s);b[i].title=s;b[i].setAttribute("aria-pressed",String(e==="light"));}}
function apply(){var p=pref(),e=eff(p);R.setAttribute("data-theme",e);R.setAttribute("data-theme-pref",p);
 var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute("content",e==="light"?"#F4F6FB":"#05050B");label();}
window.themePref=pref;window.themeNow=function(){return eff(pref());};
window.setTheme=function(p){if(V.indexOf(p)<0)return;try{localStorage.setItem(K,p);}catch(e){}apply();
 try{document.dispatchEvent(new CustomEvent("themechange",{detail:p}));}catch(e){}};
window.toggleTheme=function(){window.setTheme(eff(pref())==="light"?"dark":"light");};
if(mq){if(mq.addEventListener)mq.addEventListener("change",apply);else if(mq.addListener)mq.addListener(apply);}
window.addEventListener("storage",function(ev){if(ev.key===K)apply();});
document.addEventListener("click",function(ev){var b=ev.target&&ev.target.closest&&ev.target.closest("[data-theme-btn]");if(b){window.toggleTheme();}
 else if(ev.target&&ev.target.closest&&ev.target.closest("#lang"))setTimeout(label,0);});
apply();document.addEventListener("DOMContentLoaded",label);window.addEventListener("load",label);})();</script>"""
