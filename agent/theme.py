"""Shared calm look for the harness pages (v0.9.1): neutral backgrounds, one muted accent, no glow,
visible keyboard focus. Plain CSS, no external resources (system fonts;
Inter is used if it is installed). Animations are turned off for `prefers-reduced-motion: reduce`."""

BASE_CSS = r"""
 /* v0.9.1 calm theme: neutral surfaces, ONE muted accent, desaturated status colours, no glow. Every text colour
    below meets WCAG AA (>= 4.5:1) on --bg, --panel and --panel2 (checked by tests/test_v091_theme.py). */
 :root{--bg:#1D1F23;--panel:#25282D;--panel2:#2C2F35;--sunk:#1A1C20;--line:#373B42;--line2:#474C55;--chip:#33373E;
  --text:#E7E9EC;--strong:#F3F4F6;--soft:#CED2D8;--muted:#A0A7B1;
  --accent:#4A6696;--accent-text:#A3B8DE;--accent-rgb:120,150,200;--on-accent:#FFFFFF;
  --blue:#A3B8DE;--blue2:#4A6696;--purple:#4A6696;--purple2:#A3B8DE;
  --ok:#8CC2A0;--warn:#D8B57A;--bad:#E6A29A;--ok-rgb:140,194,160;--warn-rgb:216,181,122;--bad-rgb:230,162,154;
  --font:Inter,"Inter var",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color-scheme:dark;
  --card:var(--panel);--card2:var(--panel);
  --t-bad:#E6A29A;--t-warn:#D8B57A;--t-violet:#F3F4F6;--t-ok:#8CC2A0;--t-cyan:#A3B8DE;--hover:#C3D2EC;--shadow:rgba(0,0,0,.25)}
 /* Day theme: genuinely light and calm */
 html[data-theme=light]{--bg:#F6F6F4;--panel:#FFFFFF;--panel2:#F0F1F3;--sunk:#FFFFFF;--line:#E1E3E7;--line2:#C9CDD4;--chip:#ECEEF1;
  --text:#1E2227;--strong:#14171B;--soft:#363B42;--muted:#5B626D;
  --accent:#3D5A8F;--accent-text:#34507F;--accent-rgb:61,90,143;--on-accent:#FFFFFF;
  --ok:#2E6B47;--warn:#85571A;--bad:#A33A33;--ok-rgb:46,107,71;--warn-rgb:133,87,26;--bad-rgb:163,58,51;
  --blue:#34507F;--blue2:#3D5A8F;--purple:#3D5A8F;--purple2:#34507F;
  --t-bad:#A33A33;--t-warn:#85571A;--t-violet:#14171B;--t-ok:#2E6B47;--t-cyan:#34507F;
  --hover:#263E63;--shadow:rgba(20,23,27,.06);color-scheme:light}
 html[data-theme=light] input::placeholder,html[data-theme=light] textarea::placeholder{color:#6B717B}
 h1[tabindex="-1"]:focus,h1[tabindex="-1"]:focus-visible,h2[tabindex="-1"]:focus-visible{outline:none;box-shadow:none}
 html[data-theme=light] .grey{background:var(--chip)!important;border-color:var(--line2)!important;color:var(--text)!important}
 .themebtn{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;min-width:32px;padding:0;border-radius:50%;
  border:1px solid var(--line);background:transparent;color:var(--soft);font-size:15px;line-height:1;cursor:pointer;margin-right:6px}
 .themebtn:hover{border-color:var(--line2)}
 .themebtn::before{content:"\263E"} html[data-theme=light] .themebtn::before{content:"\2600\FE0E";color:var(--soft)}
 html{background:var(--bg)}
 body{font-family:var(--font);color:var(--soft);background:var(--bg)}
 a{color:var(--blue)} a:hover{color:var(--hover)}
 :focus{outline:none}
 :focus-visible{outline:2px solid var(--blue);outline-offset:2px;}
 input,textarea,select{background:var(--sunk);color:var(--text);border:1px solid var(--line);border-radius:10px}
 input::placeholder,textarea::placeholder{color:#8A919B}
 input:focus-visible,textarea:focus-visible,select:focus-visible{border-color:var(--blue);outline:none;}
 ::-webkit-scrollbar{width:10px;height:10px} ::-webkit-scrollbar-thumb{background:var(--chip);border-radius:6px;border:2px solid transparent;background-clip:padding-box}
 ::-webkit-scrollbar-track{background:transparent}
 #lang{border-color:var(--line2)!important;background:var(--sunk)} #lang button{color:var(--soft)} #lang button.on{background:var(--accent)!important;color:#fff}
 @media (prefers-reduced-motion: reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
"""

# Dashboard: the existing layout, recoloured.
DASH_CSS = r"""
 body{background-color:var(--bg)}
 header{background:var(--card2)!important;border-bottom:1px solid var(--line);}
 header h1{color:var(--text)} header a.c{color:var(--blue)!important}
 section{background:var(--card)!important;border:1px solid var(--line)!important;border-radius:16px!important;box-shadow:0 10px 30px rgba(0,0,0,.35)}
 h2{color:var(--t-violet)!important}
 button{background:var(--panel2);color:var(--text);border:1px solid var(--line2);border-radius:999px;padding:6px 14px;font-family:var(--font)}
 button:hover{border-color:var(--blue)} #stopall{background:#7F1D1D!important;border-color:#B91C1C!important;border-radius:999px!important}
 .task{color:var(--soft)} .task:hover{background:var(--panel2)!important} .task.sel{border-color:var(--blue)!important;background:rgba(var(--accent-rgb),0.09)!important}
 .st{background:var(--chip)!important;color:var(--soft)} .st.running,.st.queued,.st.cancelling{background:rgba(var(--accent-rgb),0.09)!important;color:var(--blue)}
 .st.done{background:rgba(var(--ok-rgb),0.09)!important;color:var(--ok)}
 .st.error,.st.cancelled,.st.stopped,.st.interrupted,.st.denied,.st.expired{background:rgba(var(--bad-rgb),0.09)!important;color:var(--bad)}
 .agent{background:var(--sunk)!important;border-left:3px solid var(--purple2)!important;border-radius:8px;}
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
 button,.btn{background:var(--blue2)!important;color:#fff;border-radius:999px!important;font-family:var(--font)!important;}
 button.lite{background:#374151!important;color:#fff!important;box-shadow:none} button.danger{background:#7F1D1D!important;color:#FECACA!important;box-shadow:none}
 #qr svg{background:#fff;padding:6px;}
 #qrurl{background:var(--sunk)!important;color:var(--soft)} code{background:var(--panel2)!important;color:var(--soft)}
 .ok{color:var(--ok)!important} .err{color:var(--bad)!important} .warn{background:rgba(var(--warn-rgb),0.072)!important;color:var(--t-warn)}
 header a{color:var(--blue)!important}
 #lang button{background:transparent!important;box-shadow:none!important;width:auto;margin:0;padding:4px 9px;border-radius:0!important;font:600 11px var(--font)!important}
 #lang button.on{background:var(--accent)!important}
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
function agentWho(id){ if(!id || id==="root") return t("who.agent"); if(/\.critic\d+$/.test(id)) return t("who.critic");
  return ROLES[id] ? t("who.helperRole",{role:ROLES[id]}) : t("who.helperN",{n:id.split(".").slice(1).join(".")}); }
function agentShort(id){ if(!id || id==="root") return t("who.short.root"); if(/\.critic\d+$/.test(id)) return t("who.critic");
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
    github_write:"github",github_get:kind==="human"?"githubRead":"github",
    handoff:"handoff",api_list:"apiList",api_get:"apiGet",api_send:"apiSend",api_pay:"apiPay"}[tool];
  const v={who,path:p,q:cutS(g.query||g.pattern||"",50),host:hostOf(g.url),tool,
    role:cutS(g.to||"",40),api:cutS(g.api||"",40),method:String(g.method||"GET").toUpperCase()};
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
  border-radius:50%!important;border:1px solid rgba(var(--accent-rgb),0.33)!important;background:rgba(var(--accent-rgb),0.06)!important;color:var(--blue)!important;
  font:700 12px var(--font)!important;cursor:pointer;vertical-align:middle;position:relative;box-shadow:none!important}
 .tip::before{content:"?"} .tip:hover{background:rgba(var(--accent-rgb),0.132)!important}
 .tipbox{position:absolute;z-index:90;max-width:300px;background:var(--panel2);color:var(--text);border:1px solid rgba(var(--accent-rgb),0.33);border-radius:12px;
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
            '<a href="/dev" data-nav="dev" data-i18n="nav.dev"></a>'
            '<a href="/settings" data-nav="settings" data-i18n="nav.settings"></a>'
            '<a href="/help" data-nav="help" data-i18n="nav.help"></a>'
            '<a href="/connect" data-nav="connect" data-i18n="nav.connect"></a></nav>')

NAV_CSS = r"""
 nav.tabs{display:inline-flex;gap:3px;padding:3px;border:1px solid var(--line);border-radius:999px;background:var(--card2);flex-shrink:0}
 nav.tabs a{padding:6px 14px;border-radius:999px;color:var(--soft)!important;text-decoration:none;font:600 13px var(--font);white-space:nowrap;line-height:1.3}
 nav.tabs a:hover{color:var(--strong)!important;background:var(--panel2)}
 nav.tabs a.on{color:#fff!important;background:var(--accent);}
 .apphead{display:flex;align-items:center;gap:12px;padding:10px 16px;padding-top:max(10px,env(safe-area-inset-top));flex-wrap:wrap;
  background:var(--card2)!important;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20}
 .apphead .brand{font:700 15px var(--font);color:var(--text);white-space:nowrap}
 .apphead .sp{flex:1}
 a.back{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;border:1px solid rgba(var(--accent-rgb),0.27);color:var(--blue)!important;
  text-decoration:none;font:600 13px var(--font);white-space:nowrap;background:rgba(var(--accent-rgb),0.048)}
 a.back:hover{background:rgba(var(--accent-rgb),0.096)}
 @media (max-width:760px){   /* every tab visible without scrolling: one row of 6, or 2 rows of 3 on a phone */
  nav.tabs{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));overflow:visible;max-width:100%;order:10;flex:1 1 100%;border-radius:16px}
  nav.tabs a{padding:8px 4px;min-height:38px;text-align:center;font-size:12.5px;white-space:normal;overflow-wrap:anywhere;
   display:flex;align-items:center;justify-content:center;border-radius:12px}
  .apphead{gap:8px;padding:8px 10px}
 }
 @media (max-width:560px){ nav.tabs{grid-template-columns:repeat(3,minmax(0,1fr))} }
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
 var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute("content",e==="light"?"#F6F6F4":"#1D1F23");label();}
window.themePref=pref;window.themeNow=function(){return eff(pref());};
window.setTheme=function(p){if(V.indexOf(p)<0)return;try{localStorage.setItem(K,p);}catch(e){}apply();
 try{document.dispatchEvent(new CustomEvent("themechange",{detail:p}));}catch(e){}};
window.toggleTheme=function(){window.setTheme(eff(pref())==="light"?"dark":"light");};
if(mq){if(mq.addEventListener)mq.addEventListener("change",apply);else if(mq.addListener)mq.addListener(apply);}
window.addEventListener("storage",function(ev){if(ev.key===K)apply();});
document.addEventListener("click",function(ev){var b=ev.target&&ev.target.closest&&ev.target.closest("[data-theme-btn]");if(b){window.toggleTheme();}
 else if(ev.target&&ev.target.closest&&ev.target.closest("#lang"))setTimeout(label,0);});
apply();document.addEventListener("DOMContentLoaded",label);window.addEventListener("load",label);})();</script>"""


# v0.9.1 "calm" layer, added last to every page (render_page): one muted accent, no glow / halo / text shadow /
# blur / animated gradient, quieter buttons and badges, readable text (15 px, line-height 1.5, ~70ch lines).
# Pages keep their own layout; this layer only takes visual noise away.
CALM_CSS = r"""
 body{font-size:15px;line-height:1.5}
 *,*::before,*::after{text-shadow:none!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important}
 *:not(.spin),*::before,*::after{animation:none!important}
 *,*::before,*::after{box-shadow:none!important}
 *,svg,svg *{filter:none!important}
 :focus-visible{outline:2px solid var(--accent-text)!important;outline-offset:2px}
 input:focus-visible,textarea:focus-visible,select:focus-visible{outline:2px solid var(--accent-text)!important;outline-offset:0;border-color:var(--accent-text)!important}
 /* floating layers only: a very soft shadow */
 #popups .card,.ap,#tourcard,.tipbox,#toast,#filesp,aside.drawer{box-shadow:0 2px 12px var(--shadow)!important}
 /* headings: fewer sizes and weights */
 h1,h2,h3{color:var(--strong)!important;font-weight:600!important;letter-spacing:0!important;text-transform:none!important}
 h2{font-size:17px} h3{font-size:15px}
 p,.muted,.help,li{max-width:70ch}
 .muted{color:var(--muted)!important}
 /* surfaces: flat, one thin border */
 section.card,.card,.step,section{border-color:var(--line)!important}
 /* buttons: one filled (primary) per area, the rest quiet */
 button,.btn,.tbtn{font-weight:500}
 .primary,.blue,#send,aside button.new,.btn.primary,#tourcard button.go,.card button.ok,#login,#apisave{background:var(--accent)!important;border-color:var(--accent)!important;color:var(--on-accent)!important}
 .primary:hover,.blue:hover,#send:hover,aside button.new:hover,.card button.ok:hover{background:var(--accent)!important;border-color:var(--accent-text)!important}
 .grey,.card button.no,button.lite,.lite{background:var(--chip)!important;border:1px solid var(--line2)!important;color:var(--text)!important}
 .danger,button.danger,#stopall,#cancel{background:transparent!important;border:1px solid rgba(var(--bad-rgb),.55)!important;color:var(--bad)!important}
 #quit{background:transparent!important}
 /* navigation: flat tabs, the current one simply marked */
 nav.tabs{background:transparent!important;border-color:var(--line)!important}
 nav.tabs a{font-weight:500!important;color:var(--soft)!important}
 nav.tabs a.on{background:var(--chip)!important;color:var(--strong)!important;font-weight:600!important}
 #lang button.on,.langbtns button.on,.seg input:checked+span,.big2 button.on{background:var(--chip)!important;color:var(--strong)!important;border-color:var(--line2)!important}
 .steps span.on{background:var(--accent)!important}
 .switch input:checked{background:var(--accent)!important}
 a.back{border-color:var(--line)!important;background:transparent!important;color:var(--soft)!important}
 a.back:hover{border-color:var(--line2)!important}
 .apphead,header,#top{background:var(--panel)!important}
 /* badges and chips: discreet */
 .pill,.badge,.st,.bdg,.tag{font-weight:500!important;border:0!important}
 .pill.purple,.pill.blue{background:var(--chip)!important;color:var(--soft)!important}
 .tip{border-color:var(--line2)!important;background:transparent!important;color:var(--muted)!important}
 .tip:hover{background:var(--chip)!important}
 .demotile{background:var(--panel)!important;border-color:var(--line2)!important}
 .themebtn{background:transparent!important;border:1px solid var(--line)!important;color:var(--soft)!important}
 .sample span.b.ok{background:var(--accent)!important;color:var(--on-accent)!important}
 .sample span.b.no{background:var(--chip)!important;color:var(--text)!important}
 .bwhy{font-weight:500!important;color:var(--soft)!important}
 .pill{background:var(--chip)!important;color:var(--soft)!important}
 .pill.ok{color:var(--ok)!important} .pill.bad{color:var(--bad)!important} .pill.warn{color:var(--warn)!important}
 details.adv{margin-top:10px;border-top:1px solid var(--line);padding-top:4px}
 details summary{color:var(--accent-text)!important;font-weight:500!important}

 /* ---- chat */
 body[data-page=chat] aside{background:var(--panel)!important}
 body[data-page=chat] aside h1{font-size:15px}
 .user .bubble{background:rgba(var(--accent-rgb),.10)!important;border:1px solid rgba(var(--accent-rgb),.28)!important;border-bottom-right-radius:16px!important}
 .user .bubble::after{display:none!important}
 .bubble{max-width:min(72%,70ch)!important;line-height:1.55}
 .bubble.final{border-color:var(--line2)!important}
 .who,.d1 .who,.d2 .who,.d3 .who{background:none!important;color:var(--muted)!important;padding:0!important;font:600 12px var(--font)!important}
 .ticks{color:var(--muted)!important}
 .step.spawn,.step.idc{color:var(--soft)!important}
 .trace,.swfoot .fl,.dlb{border-color:var(--line)!important;background:var(--panel)!important}
 .trhead .chev,.swhead .chev{color:var(--muted)!important}
 #ratebar{background:transparent!important;font-size:12px!important;color:var(--muted)!important;padding:3px 16px!important;gap:4px 16px!important}
 #ratebar .rate{flex-direction:row!important;align-items:center;gap:8px!important}
 .rate .rtop b{font-weight:500!important;color:var(--soft)!important}
 .rate .rbar{height:3px!important;min-width:60px!important;max-width:120px!important}
 .rate .rbar i{background:var(--muted)!important} .rate .rbar i.mid{background:var(--warn)!important} .rate .rbar i.lo{background:var(--bad)!important}
 .rate .rest{border-style:solid!important;border-color:var(--line)!important}
 #thinking .dot{background:var(--muted)!important}
 .trhead .live{background:var(--muted)!important}
 #demobadge,.demonote,#idcbox,#idcbox.on{background:var(--chip)!important;border-color:var(--line2)!important;color:var(--soft)!important}
 .ex{background:var(--panel)!important;border-color:var(--line)!important}
 .card .cat,.card .cat.send,.card .cat.spend,.card .cat.execute{background:var(--chip)!important;color:var(--soft)!important}
 /* swarm graph: muted nodes, thin lines, no glow */
 #swarm{border-color:var(--line)!important;background:var(--panel)!important}
 .swlines path{stroke:var(--line2)!important;stroke-width:1.25!important;opacity:1!important}
 .hub{width:56px!important;height:56px!important;border:2px solid var(--line2)!important}
 .hub .inner{width:40px!important;height:40px!important;border:1px solid var(--line)!important}
 .hub .core{width:22px!important;height:22px!important;background:var(--accent)!important}
 .ag{background:var(--panel)!important;border:1px solid var(--line)!important;border-radius:10px!important}
 .ag.done{border-color:var(--line)!important} .ag.bad{border-color:rgba(var(--bad-rgb),.55)!important} .ag.revise{border-color:rgba(var(--warn-rgb),.6)!important}
 .ag .agst{color:var(--muted)!important} .ag.done .agst{color:var(--ok)!important} .ag.bad .agst{color:var(--bad)!important}
 .ag .agname{font:600 12.5px var(--font)!important}
 .ag .prog{height:3px!important;background:var(--chip)!important} .ag .prog i{background:var(--muted)!important}
 .ag .agkey{color:var(--muted)!important}
 .doc,.doc svg{width:44px!important;height:54px!important}
 .doc svg path{stroke:var(--line2)!important;fill:var(--panel2)!important}
 .doc svg path+path+path{stroke:var(--muted)!important;fill:none!important}
 .doc svg path:nth-child(2){fill:none!important}
 .doc .chk{width:22px!important;height:22px!important;right:-7px!important;bottom:-4px!important;background:var(--accent)!important;border:2px solid var(--panel)!important}
 .doc .chk svg{width:12px!important;height:12px!important}
 .swkeys .kc{background:transparent!important}
 /* ---- dashboard */
 .agent{border-left:2px solid var(--line2)!important;background:var(--panel)!important}
 .prog i{background:var(--muted)!important}
 .ev b{color:var(--soft)!important}
 /* ---- phones */
 @media (max-width:760px){ body{font-size:15px} .bubble{max-width:90%!important} }
"""
