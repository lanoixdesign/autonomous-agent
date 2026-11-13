"""Shared "neon" look for the harness pages (chat, dashboard, connect): dark background with a soft purple
glow, neon blue / purple accents, visible keyboard focus. Plain CSS, no external resources (system fonts;
Inter is used if it is installed). Animations are turned off for `prefers-reduced-motion: reduce`."""

BASE_CSS = r"""
 :root{--bg:#05050B;--panel:#14141C;--panel2:#1E1E24;--line:#2A2A35;--text:#FFFFFF;--soft:#D1D5DB;--muted:#9CA3AF;
  --blue:#00D4FF;--blue2:#2563EB;--purple:#9D00FF;--purple2:#B92BFF;--ok:#22C55E;--warn:#F59E0B;--bad:#F87171;
  --font:Inter,"Inter var",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color-scheme:dark}
 html{background:var(--bg)}
 body{font-family:var(--font);color:var(--soft);
  background:radial-gradient(ellipse 70% 55% at 50% 45%,rgba(157,0,255,.18),rgba(157,0,255,.06) 45%,transparent 75%),var(--bg);
  background-attachment:fixed}
 a{color:var(--blue)} a:hover{color:#7FE9FF}
 :focus{outline:none}
 :focus-visible{outline:2px solid var(--blue);outline-offset:2px;box-shadow:0 0 0 4px rgba(0,212,255,.25)}
 input,textarea,select{background:#0D0D14;color:var(--text);border:1px solid var(--line);border-radius:10px}
 input::placeholder,textarea::placeholder{color:#6B7280}
 input:focus-visible,textarea:focus-visible,select:focus-visible{border-color:var(--blue);outline:none;box-shadow:0 0 0 3px rgba(0,212,255,.25)}
 ::-webkit-scrollbar{width:10px;height:10px} ::-webkit-scrollbar-thumb{background:#2A2A35;border-radius:6px;border:2px solid transparent;background-clip:padding-box}
 ::-webkit-scrollbar-track{background:transparent}
 #lang{border-color:#3A3A46!important;background:#0D0D14} #lang button{color:var(--soft)} #lang button.on{background:linear-gradient(90deg,var(--blue2),var(--purple))!important;color:#fff}
 @media (prefers-reduced-motion: reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
"""

# Dashboard: the existing layout, recoloured.
DASH_CSS = r"""
 body{background-color:var(--bg)}
 header{background:rgba(20,20,28,.85)!important;border-bottom:1px solid var(--line);backdrop-filter:blur(8px)}
 header h1{color:var(--text)} header a.c{color:var(--blue)!important}
 section{background:rgba(20,20,28,.92)!important;border:1px solid var(--line)!important;border-radius:16px!important;box-shadow:0 10px 30px rgba(0,0,0,.35)}
 h2{color:#A5B4FC!important}
 button{background:var(--panel2);color:var(--text);border:1px solid #3A3A46;border-radius:999px;padding:6px 14px;font-family:var(--font)}
 button:hover{border-color:var(--blue)} #stopall{background:#7F1D1D!important;border-color:#B91C1C!important;border-radius:999px!important}
 .task{color:var(--soft)} .task:hover{background:#1E1E24!important} .task.sel{border-color:var(--blue)!important;background:rgba(37,99,235,.15)!important}
 .st{background:#2A2A35!important;color:var(--soft)} .st.running,.st.queued,.st.cancelling{background:rgba(0,212,255,.15)!important;color:var(--blue)}
 .st.done{background:rgba(34,197,94,.15)!important;color:var(--ok)}
 .st.error,.st.cancelled,.st.stopped,.st.interrupted,.st.denied,.st.expired{background:rgba(248,113,113,.15)!important;color:var(--bad)}
 .agent{background:#101018!important;border-left:3px solid var(--purple2)!important;border-radius:8px;box-shadow:0 0 12px rgba(157,0,255,.18)}
 .agent small,.muted{color:var(--muted)!important} .ev{border-bottom:1px solid #1F1F29!important} .ev b{color:var(--blue)!important}
 .ap{background:var(--panel2)!important;border:1px solid #3A3A46!important;border-radius:16px!important;box-shadow:0 12px 30px rgba(0,0,0,.45)}
 .ap button{border-radius:999px} .ap button.ok,.ap button:first-of-type{background:var(--blue2);border-color:var(--blue2)}
 td,th{border-bottom:1px solid #1F1F29!important;color:var(--soft)} tr.conv td{background:#1A1A24!important;color:var(--text)}
 .sched{border-color:var(--line)!important;border-radius:12px!important}
 pre{color:var(--soft)}
"""

# /connect page.
CONNECT_CSS = r"""
 header{background:rgba(20,20,28,.85)!important;border-bottom:1px solid var(--line)} header h1{color:var(--text)}
 section{background:rgba(20,20,28,.92)!important;border:1px solid var(--line)!important;border-radius:20px!important;box-shadow:0 10px 30px rgba(0,0,0,.35)}
 h2{color:var(--text)} .muted{color:var(--muted)!important}
 button,.btn{background:var(--blue2)!important;color:#fff;border-radius:999px!important;font-family:var(--font)!important;box-shadow:0 0 18px rgba(37,99,235,.35)}
 button.lite{background:#374151!important;color:#fff!important;box-shadow:none} button.danger{background:#7F1D1D!important;color:#FECACA!important;box-shadow:none}
 #qr svg{background:#fff;padding:6px;box-shadow:0 0 28px rgba(0,212,255,.35)}
 #qrurl{background:#0D0D14!important;color:var(--soft)} code{background:#1E1E24!important;color:var(--soft)}
 .ok{color:var(--ok)!important} .err{color:var(--bad)!important} .warn{background:rgba(245,158,11,.12)!important;color:#FCD34D}
 header a{color:var(--blue)!important}
 #lang button{background:transparent!important;box-shadow:none!important;width:auto;margin:0;padding:4px 9px;border-radius:0!important;font:600 11px var(--font)!important}
 #lang button.on{background:linear-gradient(90deg,var(--blue2),var(--purple))!important}
"""

# Shared by the chat and the dashboard: a human question for an approval, and its reason, translated.
APPROVAL_JS = r"""
function askText(a){
  const g=a.args||{}, cut=(s,n)=>{ s=String(s==null?"":s); return s.length>n ? s.slice(0,n)+"…" : s; };
  const host=u=>{ try{ return new URL(u).host; }catch(e){ return cut(u,40); } };
  const m={write_file:["ask.write",{path:cut(g.path,60)}], edit_file:["ask.edit",{path:cut(g.path,60)}],
    shell:["ask.shell",{cmd:cut(g.command,80)}], web_fetch:["ask.fetch",{host:host(g.url)}], web_search:["ask.search",{q:cut(g.query,60)}],
    github_write:["ask.github",{path:cut(g.path||g.repo||"",60)}], spawn_agent:["ask.spawn",{}],
    spawn_agents:["ask.spawnMany",{n:Array.isArray(g.tasks)?g.tasks.length:1}], memory_write:["ask.memory",{}], memory_forget:["ask.forget",{}]}[a.tool];
  return m ? t(m[0],m[1]) : t("ask.generic",{tool:a.tool,category:tr("cat",a.category)});
}
function reasonText(r){
  r=String(r||""); let m;
  const tail=s=>!s ? "" : (/--yolo ignored/.test(s) ? t("reason.yolo") : (/upgraded by --yolo/.test(s) ? t("reason.upgraded") : ""));
  if((m=/^category default '([\w-]+): (\w+)'(;.*)?$/.exec(r))) return t("reason.category",{category:tr("cat",m[1]),mode:tr("mode",m[2])})+tail(m[3]);
  if((m=/^tool rule '([\w-]+): (\w+)'(;.*)?$/.exec(r))) return t("reason.tool",{tool:m[1],mode:tr("mode",m[2])})+tail(m[3]);
  return r;
}
"""
