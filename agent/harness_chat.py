"""The harness chat page (served at / and /chat). Plain HTML + JS, no external resources.
Dark "neon" theme (agent/theme.py), live swarm graph (GET /tasks/{id}/graph). Live updates by Server-Sent Events (/tasks/{id}/stream), falling back to polling if the stream fails.
Bilingual (EN/FR): every visible string comes from agent/i18n.py through t(); see agent/i18n_js.py."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH
from .theme import APPROVAL_JS, BASE_CSS, NAV_CSS, NAV_HTML, NAV_JS

CHAT_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="chat.pageTitle">autonomous-agent · chat</title>
<style>
/*THEME*/
 *{box-sizing:border-box} body{margin:0;font-size:14px;line-height:1.45;height:100vh;display:flex;color:var(--soft)}
 aside{width:270px;background:rgba(14,14,20,.92);border-right:1px solid var(--line);color:var(--soft);display:flex;flex-direction:column;backdrop-filter:blur(10px)}
 body.collapsed aside{display:none}
 aside h1{font-size:15px;margin:16px 16px 10px;color:var(--text);letter-spacing:.01em}
 aside button.new{margin:0 12px 12px;padding:10px;border:1px solid transparent;border-radius:999px;color:#fff;cursor:pointer;font:600 13px var(--font);
  background:linear-gradient(90deg,var(--blue2),var(--purple));box-shadow:0 0 18px rgba(37,99,235,.35)}
 #convs{flex:1;overflow:auto;padding:0 6px} .conv{padding:9px 12px;cursor:pointer;border-radius:12px;border:1px solid transparent;margin:2px 0}
 .conv:hover{background:#1A1A24} .conv.sel{background:rgba(37,99,235,.14);border-color:rgba(0,212,255,.35);box-shadow:0 0 14px rgba(0,212,255,.12)}
 .conv .t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)} .conv small{color:var(--muted)}
 #quota{max-height:38vh;overflow:auto;padding:4px 12px;font-size:11.5px;border-top:1px solid var(--line)}
 #quota h2{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:6px 0}
 .qk{margin:0 0 8px} .qk b{color:var(--text)} .qk code{color:var(--muted);font-size:11px} .qk .off{color:var(--bad)}
 .ql{display:flex;justify-content:space-between;color:var(--soft)} .bar{height:3px;background:#2A2A35;border-radius:2px;margin:1px 0 3px}
 .bar i{display:block;height:3px;background:var(--ok);border-radius:2px} .bar i.hi{background:var(--warn)} .bar i.full{background:var(--bad)}
 aside footer{padding:12px;font-size:12px;color:var(--muted);border-top:1px solid var(--line)} aside footer input{width:100%;margin-top:4px;padding:6px 8px}
 main{flex:1;display:flex;flex-direction:column;min-width:0;position:relative}
 #top{padding:10px 16px;border-bottom:1px solid var(--line);background:rgba(10,10,16,.7);backdrop-filter:blur(10px);display:flex;gap:10px;align-items:center}
 #brand{font-weight:700;color:var(--text);font-size:16px;white-space:nowrap}
 #title{flex:1;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}
 .ibtn{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border-radius:12px;border:1px solid var(--line);
  background:#14141C;color:var(--text);cursor:pointer;padding:0;font-size:18px}
 .ibtn:hover{border-color:var(--blue);box-shadow:0 0 12px rgba(0,212,255,.3)} .ibtn svg{width:20px;height:20px}
 #log{flex:1;overflow:auto;padding:18px 20px 24px}
 .row{display:flex;margin:8px 0} .row.user{justify-content:flex-end}
 .bubble{max-width:72%;padding:10px 14px;border-radius:16px;background:var(--panel);border:1px solid var(--line);white-space:pre-wrap;word-break:break-word;color:var(--soft)}
 .user .bubble{position:relative;color:var(--text);border:2px solid transparent;border-bottom-right-radius:4px;
  background:linear-gradient(#14141C,#14141C) padding-box,linear-gradient(120deg,var(--blue),var(--blue2),var(--purple),var(--purple2),var(--blue)) border-box;
  background-size:100% 100%,300% 300%;animation:flow 6s linear infinite;box-shadow:0 0 18px rgba(0,212,255,.22),0 0 26px rgba(157,0,255,.18)}
 .user .bubble::after{content:"";position:absolute;right:-9px;bottom:-2px;width:12px;height:14px;
  background:linear-gradient(135deg,var(--purple),var(--purple2));clip-path:polygon(0 0,0 100%,100% 100%)}
 @keyframes flow{0%{background-position:0 0,0% 50%}100%{background-position:0 0,300% 50%}}
 .umeta{display:flex;justify-content:flex-end;gap:6px;align-items:center;margin-top:4px;font-size:11px;color:var(--muted);white-space:nowrap}
 .ticks{color:var(--blue);letter-spacing:-3px;font-weight:700}
 .bubble.final{border-color:rgba(34,197,94,.55);box-shadow:0 0 16px rgba(34,197,94,.15)}
 .who{display:inline-block;font:600 11px var(--mono);padding:1px 7px;border-radius:8px;background:rgba(0,212,255,.12);color:var(--blue);margin-bottom:3px}
 .d1 .who{background:rgba(157,0,255,.16);color:#D8A8FF} .d2 .who{background:rgba(245,158,11,.14);color:#FCD34D} .d3 .who{background:rgba(34,197,94,.14);color:#86EFAC}
 .step{font:12px/1.4 var(--mono);color:#8B93A3;margin:3px 0 3px 8px}
 .step b{color:var(--soft)} .step.deny,.step.err{color:var(--bad)} .step.spawn{color:#C084FC} .step.merge{color:var(--ok)} .step.conflict{color:var(--bad);font-weight:600}
 .step details{display:inline} .step summary{cursor:pointer;display:inline;color:var(--blue)} .step pre{color:var(--soft)}
 .sys{text-align:center;color:var(--muted);font-size:12px;margin:10px 0}
 #thinking{display:none;align-items:center;gap:10px;padding:4px 22px 8px;color:var(--soft);font-size:13px}
 #thinking.on{display:flex} #thinking .dot{width:10px;height:10px;border-radius:50%;background:var(--blue);box-shadow:0 0 10px var(--blue);animation:pulse 1.2s ease-in-out infinite}
 @keyframes pulse{0%,100%{transform:scale(.75);opacity:.55}50%{transform:scale(1.15);opacity:1}}
 #composer{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line);background:rgba(10,10,16,.75);backdrop-filter:blur(10px)}
 #composer textarea{flex:1;resize:none;height:56px;padding:10px 12px;border-radius:14px;font:inherit;font-family:var(--font)}
 #send{padding:0 20px;border:0;border-radius:999px;color:#fff;cursor:pointer;font:600 14px var(--font);background:linear-gradient(90deg,var(--blue2),var(--purple));box-shadow:0 0 16px rgba(37,99,235,.4)}
 #send:disabled{opacity:.6}
 .tbtn{padding:7px 14px;border:1px solid #3A3A46;border-radius:999px;background:#1E1E24;color:var(--text);cursor:pointer;font:600 12px var(--font);white-space:nowrap}
 .tbtn:hover{border-color:var(--blue)} #cancel{border-color:#B91C1C;color:#FCA5A5} #stopall{background:#7F1D1D;border-color:#B91C1C;color:#fff}
 #mode{font-size:11px;color:var(--muted)}
 .badge{font-size:11px;padding:2px 8px;border-radius:9px;background:#2A2A35;color:var(--soft)}
 .badge.running,.badge.queued,.badge.cancelling{background:rgba(0,212,255,.14);color:var(--blue)} .badge.done{background:rgba(34,197,94,.15);color:var(--ok)}
 .badge.error,.badge.cancelled,.badge.stopped,.badge.interrupted{background:rgba(248,113,113,.15);color:var(--bad)}
 #err{color:var(--bad);font-size:12px;padding:0 16px} #err a{color:var(--blue);font-weight:600}
 #attach{width:46px;border-radius:14px;font-size:18px}
 #chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px} #chips:not(:empty){padding:8px 16px 0;border-top:1px solid var(--line)}
 .chip{display:inline-flex;align-items:center;gap:6px;background:#1E1E24;border:1px solid #3A3A46;border-radius:14px;padding:3px 6px 3px 10px;font-size:12px}
 .chip.bad{border-color:var(--bad)} .chip button{border:0;background:none;cursor:pointer;font-size:14px;color:var(--muted);padding:0 2px}
 .atts{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px} .att{font-size:12px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.2);border-radius:10px;padding:1px 8px}
 #drop{display:none;position:absolute;inset:0;background:rgba(0,212,255,.08);border:3px dashed var(--blue);border-radius:16px;z-index:5;
  align-items:center;justify-content:center;font-size:18px;color:var(--blue);font-weight:600;pointer-events:none}
 main.dragging #drop{display:flex}
 /* approval cards */
 #popups{position:fixed;right:18px;top:64px;width:390px;max-height:calc(100vh - 150px);overflow:auto;display:flex;flex-direction:column;gap:12px;z-index:10;padding:4px}
 .card{background:#1E1E24;border:1px solid #2F2F3A;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.02);padding:16px 18px;animation:pop .18s ease-out;color:var(--soft)}
 @keyframes pop{from{transform:translateY(10px) scale(.98);opacity:0}to{transform:none;opacity:1}}
 @media (min-width:900px){body.has-popups #log{padding-right:420px} body.has-popups #swarm{margin-right:420px}}
 .card .ctop{display:flex;align-items:center;justify-content:center;gap:8px;font-size:12px}
 .card .q{margin:10px 0 6px;font-size:17px;line-height:1.35;font-weight:700;color:#fff;text-align:center;word-break:break-word}
 .card .meta{font-size:12px;color:var(--muted);text-align:center}
 .card details{margin:8px 0 2px;font-size:12px} .card summary{cursor:pointer;color:var(--blue);text-align:center}
 .card pre{background:#0D0D14;border:1px solid var(--line);border-radius:10px;padding:8px;max-height:160px;overflow:auto;font:11.5px var(--mono);white-space:pre-wrap;word-break:break-word;color:var(--soft);text-align:left}
 .card .cat{font-weight:700;text-transform:uppercase;font-size:10.5px;padding:2px 8px;border-radius:999px;background:rgba(245,158,11,.15);color:#FCD34D;letter-spacing:.04em}
 .card .cat.send,.card .cat.spend,.card .cat.execute{background:rgba(248,113,113,.18);color:#FCA5A5}
 .card .btns{display:flex;gap:10px;margin-top:12px} .card button{flex:1;padding:11px;border:0;border-radius:999px;cursor:pointer;font:700 14px var(--font);color:#fff}
 .card .ok{background:#2563EB;box-shadow:0 0 18px rgba(37,99,235,.45)} .card .ok:hover{background:#1D4ED8} .card .no{background:#374151} .card .no:hover{background:#4B5563}
 .card button:disabled{opacity:.6}
 .card .remember{display:flex;gap:8px;margin-top:8px} .card .remember button{flex:1;padding:7px;font-weight:500;font-size:11.5px;background:transparent;color:var(--blue);border:1px solid #3A3A46}
 .card .never{font-size:11px;color:#FCA5A5;margin-top:8px;text-align:center}
 /* IDC */
 #idcbox{display:inline-flex;align-items:center;gap:5px;font:600 12px var(--font);color:#D8A8FF;background:rgba(157,0,255,.12);border:1px solid rgba(157,0,255,.4);border-radius:999px;padding:5px 10px;cursor:pointer}
 #idcbox.on{background:linear-gradient(90deg,rgba(157,0,255,.55),rgba(185,43,255,.4));color:#fff;box-shadow:0 0 14px rgba(157,0,255,.4)} #idcbox input{margin:0;accent-color:var(--purple2)}
 #idcpanel{padding:8px 18px 10px;background:rgba(157,0,255,.07);border-bottom:1px solid rgba(157,0,255,.25);font-size:12px;color:#E9D5FF}
 #idcpanel .vrow{display:flex;justify-content:space-between;gap:10px} #idcpanel .why{color:var(--bad);font-weight:600}
 .vbar{height:8px;background:#1A1A24;border-radius:4px;overflow:hidden;margin:5px 0}
 .vbar i{display:block;height:8px;background:linear-gradient(90deg,var(--purple),var(--purple2));box-shadow:0 0 10px var(--purple);transition:width .3s}
 .vbar i.low{background:var(--warn);box-shadow:0 0 10px var(--warn)} .vbar i.dead{background:var(--bad)}
 #idcpanel summary{cursor:pointer;font-weight:600} #idcpanel ol{margin:4px 0 0;padding-left:20px;max-height:22vh;overflow:auto}
 #idcpanel li{margin:2px 0} #idcpanel li .k{font-weight:600;color:#fff} #idcpanel li .u{color:var(--bad)} #idcpanel li .s{color:var(--ok)}
 .step.idc{color:#C084FC} .step.idcbad{color:var(--bad)}
 #idcdefrow{display:flex;align-items:center;gap:6px;margin-top:8px;cursor:pointer} #idcdefrow input{width:auto;margin:0;accent-color:var(--purple2)}
 #connectlink{display:block;margin-top:8px} #scrim{display:none}
 /* live swarm graph */
 #swarm{flex-shrink:0;margin:10px 16px 0;border:1px solid rgba(0,212,255,.22);border-radius:18px;background:rgba(12,12,20,.72);box-shadow:0 0 30px rgba(0,212,255,.08) inset}
 #swarm[hidden]{display:none}
 .swhead{display:flex;align-items:center;gap:10px;padding:8px 12px;cursor:pointer;border:0;background:none;color:var(--soft);width:100%;font:600 13px var(--font);text-align:left;border-radius:18px}
 .swhead .chev{transition:transform .2s;color:var(--blue)} #swarm.closed .chev{transform:rotate(-90deg)}
 .swhead .sum{color:var(--muted);font-weight:500}
 #swarm.closed .swbody,#swarm.closed .swfoot{display:none}
 .swbody{position:relative;display:grid;grid-template-columns:1fr auto 1fr;gap:18px 46px;align-items:center;padding:14px 18px 18px;min-height:190px;max-height:46vh;overflow:auto}
 .swlines{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
 .swlines path{fill:none;stroke:var(--blue);stroke-width:2;filter:drop-shadow(0 0 4px var(--blue));opacity:.85}
 .swcol{display:flex;flex-direction:column;gap:12px;position:relative;z-index:1}
 .swcenter{display:flex;flex-direction:column;align-items:center;gap:8px;position:relative;z-index:1}
 .hub{width:96px;height:96px;border-radius:50%;border:6px solid var(--blue);display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 22px var(--blue),0 0 48px rgba(0,212,255,.35),inset 0 0 18px rgba(0,212,255,.35);background:#0B0B14;animation:breathe 3.2s ease-in-out infinite}
 .hub .inner{width:66px;height:66px;border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center}
 .hub .core{width:30px;height:30px;border-radius:7px;background:var(--blue2);display:flex;align-items:center;justify-content:center;box-shadow:0 0 12px rgba(37,99,235,.8)}
 .hub .core svg{width:20px;height:20px}
 .hublabel{font:600 12px var(--font);color:var(--text);text-align:center} .hublabel small{display:block;color:var(--muted);font-weight:500}
 @keyframes breathe{0%,100%{box-shadow:0 0 18px var(--blue),0 0 36px rgba(0,212,255,.25),inset 0 0 14px rgba(0,212,255,.3)}50%{box-shadow:0 0 28px var(--blue),0 0 64px rgba(0,212,255,.45),inset 0 0 22px rgba(0,212,255,.45)}}
 .ag{position:relative;background:#101018;border:1px solid var(--purple2);border-radius:8px;padding:9px 11px;min-width:0;
  box-shadow:0 0 12px rgba(157,0,255,.35),inset 0 0 10px rgba(157,0,255,.12);animation:glow 3.4s ease-in-out infinite;transition:transform .7s cubic-bezier(.5,0,.3,1),opacity .7s}
 @keyframes glow{0%,100%{box-shadow:0 0 10px rgba(157,0,255,.3),inset 0 0 8px rgba(157,0,255,.1)}50%{box-shadow:0 0 20px rgba(185,43,255,.55),inset 0 0 12px rgba(157,0,255,.2)}}
 .ag .agtop{display:flex;justify-content:space-between;gap:8px;align-items:center}
 .ag .agname{font:700 12px var(--mono);color:#fff} .ag .agst{font-size:11px;color:var(--blue)} .ag.done .agst{color:var(--ok)} .ag.bad .agst{color:var(--bad)}
 .ag .agrole{font-size:12px;color:var(--soft);margin:3px 0 6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
 .ag .prog{height:6px;border-radius:4px;background:#1F1F2B;overflow:hidden}
 .ag .prog i{display:block;height:100%;width:0;background:linear-gradient(90deg,#00D4FF,#7DD3FC);box-shadow:0 0 10px #00D4FF;transition:width .5s ease}
 .ag .agmeta{font-size:10.5px;color:var(--muted);margin-top:4px}
 #swarm.merging .ag{transform:translate(var(--dx),var(--dy)) scale(.25);opacity:0}
 #swarm.merging .swlines{opacity:0;transition:opacity .5s}
 #swarm.merged .swcol,#swarm.merged .swlines{display:none}
 #swarm.merged.reveal .swcol{display:flex} #swarm.merged.reveal .swlines{display:block}
 #swarm.merged .swbody{grid-template-columns:1fr;min-height:0}
 .doc{display:none;position:relative;width:76px;height:92px;text-decoration:none;filter:drop-shadow(0 0 14px var(--blue));animation:scalein .55s cubic-bezier(.2,1.4,.4,1) both}
 #swarm.merged .doc{display:block} #swarm.merged .hub{display:none}
 .doc svg{width:76px;height:92px} .doc .chk{position:absolute;right:-10px;bottom:-6px;width:34px;height:34px;border-radius:50%;background:var(--ok);display:flex;align-items:center;justify-content:center;box-shadow:0 0 14px var(--ok);border:3px solid #0B0B14}
 .doc .chk svg{width:18px;height:18px}
 @keyframes scalein{from{transform:scale(.2);opacity:0}to{transform:scale(1);opacity:1}}
 .swfoot{display:none;padding:0 18px 14px;text-align:center;font-size:12.5px;color:var(--soft)}
 #swarm.merged .swfoot{display:block}
 .swfoot .files{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:6px 0}
 .swfoot a,.swfoot button{font:600 12px var(--font)} .swfoot .fl{padding:3px 10px;border-radius:999px;border:1px solid rgba(0,212,255,.4);color:var(--blue);background:rgba(0,212,255,.08);text-decoration:none;cursor:pointer}
 .swfoot .acts{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-top:4px}
 .swfoot button.linkish{background:none;border:0;color:var(--blue);cursor:pointer;text-decoration:underline;padding:0}
 .bubble.flash{box-shadow:0 0 0 2px var(--ok),0 0 26px rgba(34,197,94,.45)}
 /* collapsible work trace (tool calls, sub-agents, approvals) — the final answer stays outside */
 .trace{margin:6px 0 8px;border:1px solid rgba(0,212,255,.22);border-radius:14px;background:rgba(12,12,20,.6)}
 .trhead{display:flex;align-items:center;gap:10px;width:100%;padding:8px 12px;border:0;background:none;color:var(--soft);cursor:pointer;
  font:600 12.5px var(--font);text-align:left;border-radius:14px;min-height:38px}
 .trhead:hover{background:rgba(0,212,255,.06)} .trhead .chev{color:var(--blue);width:12px;display:inline-block;font-size:12px}
 .trhead .trtitle{color:var(--text)} .trhead .trsum{color:var(--muted);font-weight:500;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .trhead .trpend{color:#FCD34D;font-weight:700;white-space:nowrap} .trhead .trpend:empty{display:none}
 .trhead .live{width:8px;height:8px;border-radius:50%;background:var(--blue);box-shadow:0 0 8px var(--blue);animation:pulse 1.2s ease-in-out infinite;flex-shrink:0}
 .trace:not(.running) .live{display:none}
 .trbody{padding:2px 10px 10px;border-top:1px solid rgba(0,212,255,.12)} .trbody[hidden]{display:none}
 .trbody .row{margin:4px 0} .trbody .bubble{font-size:13px}
 #demobadge{font:600 11.5px var(--font);color:#E9D5FF;background:rgba(157,0,255,.16);border:1px solid rgba(157,0,255,.45);border-radius:999px;padding:4px 10px;text-decoration:none;white-space:nowrap}
 #demobadge[hidden]{display:none}
 aside nav.tabs{display:none}
 #quitlink{background:none;border:0;color:#FCA5A5;cursor:pointer;font:600 12px var(--font);padding:0}
 #quitlink[hidden]{display:none}
 /* phones and small tablets: drawer sidebar, bottom-sheet approval cards, big touch targets, vertical swarm */
 @media (max-width:760px){
  body{height:100vh;height:100dvh}
  aside{position:fixed;top:0;bottom:0;left:0;width:84vw;max-width:320px;z-index:30;transform:translateX(-102%);transition:transform .2s ease;padding-top:env(safe-area-inset-top);background:#0E0E16}
  body.collapsed aside{display:flex}
  body.nav aside{transform:none;box-shadow:0 0 40px rgba(0,0,0,.6)}
  body.nav #scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:25}
  #top{flex-wrap:wrap;padding:8px 10px;padding-top:max(8px,env(safe-area-inset-top));gap:6px}
  #brand{flex:1} #title{order:5;flex:1 1 100%;font-size:12px} #mode,#expmd,#expjson{display:none!important}
  .tbtn{padding:8px 12px;min-height:36px}
  #log{padding:10px 12px 16px} .bubble{max-width:88%} .step{margin-left:2px;font-size:11.5px;word-break:break-word}
  #popups{left:8px;right:8px;top:auto;bottom:calc(80px + env(safe-area-inset-bottom));width:auto;max-height:66vh}
  .card{border-radius:24px;padding:18px 16px} .card button{padding:13px;font-size:15px;min-height:48px} .card .remember button{min-height:40px;font-size:12.5px}
  .card pre{max-height:22vh} .card .q{font-size:18px}
  #composer{padding:8px;padding-bottom:max(8px,env(safe-area-inset-bottom))} #composer textarea{font-size:16px;height:48px}
  #send{padding:0 14px}
  #idcpanel{padding:6px 12px} #idcpanel ol{max-height:16vh}
  aside button.new{padding:12px} .conv{padding:12px 14px} #idcdefrow input{width:20px;height:20px}
  #swarm{margin:8px 10px 0}
  #top nav.tabs{display:none}
  aside nav.tabs{display:flex;flex-direction:column;border-radius:16px;margin:0 12px 12px;order:0;flex:0 0 auto;overflow:visible}
  aside nav.tabs a{text-align:left;padding:11px 14px;font-size:14px}
  #demobadge{order:4}
  .trhead{min-height:44px}
  .swbody{display:flex;flex-direction:column;align-items:stretch;gap:12px;padding:12px 12px 14px 12px;max-height:40vh}
  .swcenter{order:-1;flex-direction:row;align-items:center;gap:12px;align-self:flex-start}
  .hub{width:64px;height:64px;border-width:5px} .hub .inner{width:42px;height:42px} .hub .core{width:22px;height:22px;border-radius:5px} .hub .core svg{width:15px;height:15px}
  .hublabel{text-align:left}
  .swcol{margin-left:52px;gap:10px}
  #swarm.merged .swcenter{align-self:center;flex-direction:column} #swarm.merged.reveal .swcol{display:flex}
 }
/*NAV_CSS*/
/*LANG_CSS*/
</style></head><body data-page="chat">
<aside><h1>autonomous-agent</h1>
 /*NAV*/
 <button class="new" id="new" data-i18n="chat.new"></button>
 <div id="convs"></div>
 <div id="quota"></div>
 <footer><span data-i18n="token.label"></span><input id="token" type="password">
  <a id="connectlink" href="/connect" data-i18n="chat.connect"></a>
  <label id="idcdefrow" data-i18n-title="idc.default.title"><input type="checkbox" id="idcdef"><span data-i18n="idc.default"></span></label>
  <div style="margin-top:6px;display:flex;justify-content:space-between;align-items:center"><button id="quitlink" type="button" hidden data-i18n="nav.quit"></button>/*LANG_SWITCH*/</div></footer></aside>
<main>
 <div id="top"><button id="menu" class="ibtn" data-i18n-title="chat.sidebar" aria-controls="convs">☰</button><span id="brand" data-i18n="chat.brand"></span>/*NAV*/<a id="demobadge" href="/settings#keys" hidden data-i18n="chat.demoBadge" data-i18n-title="chat.demoTitle"></a><span id="title"></span><span id="status"></span><span id="mode"></span>
  <label id="idcbox"><input type="checkbox" id="idc"><span data-i18n="idc.label"></span></label>
  <button id="cancel" class="tbtn" style="display:none" data-i18n="chat.stop"></button>
  <button id="expmd" class="tbtn" style="display:none" data-i18n-title="chat.expmd.title">⇩ MD</button>
  <button id="expjson" class="tbtn" style="display:none" data-i18n-title="chat.expjson.title">⇩ JSON</button>
  <button id="stopall" class="tbtn" data-i18n="btn.stopall" data-i18n-title="title.stopall"></button>
  <button id="compose" class="ibtn" data-i18n-title="chat.compose"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button></div>
 <div id="idcpanel" hidden></div>
 <section id="swarm" hidden aria-live="polite"></section>
 <div id="log"></div>
 <div id="thinking" role="status"><i class="dot"></i><span id="thinktext"></span></div>
 <div id="err"></div>
 <div id="chips"></div>
 <div id="composer"><button id="attach" class="ibtn" data-i18n-title="chat.attach.title">📎</button>
  <input id="files" type="file" multiple hidden>
  <textarea id="input" data-i18n-placeholder="chat.input.placeholder"></textarea>
  <button id="send" data-i18n="chat.send"></button></div>
 <div id="drop" data-i18n="chat.drop"></div>
</main>
<div id="popups"></div>
<div id="scrim"></div>
<script>
/*I18N_JS*/
/*NAV_JS*/
/*APPROVAL_JS*/
const $ = id => document.getElementById(id);
const tok = $("token"); tok.value = sessionStorage.getItem("harnessToken") || "";
tok.onchange = () => { sessionStorage.setItem("harnessToken", tok.value); loadConfig(); };
let cur = location.hash.slice(1) || (()=>{ try{ return sessionStorage.getItem("chatCur"); }catch(e){ return null; } })() || null, tasks = [];
const cache = {};            // task id -> {since, events: []}
const answering = new Set(); // approval ids being answered
if(cur) cache[cur]={since:0,events:[]};
function pick(id, fromHistory){ const changed=id!==cur; cur=id;
  try{ if(id) sessionStorage.setItem("chatCur",id); else sessionStorage.removeItem("chatCur"); }catch(e){}
  const url=id?"#"+id:location.pathname+location.search;
  if(!fromHistory){ if(changed) history.pushState({c:id},"",url); else history.replaceState({c:id},"",url); }
  if(id) cache[id]=cache[id]||{since:0,events:[]};
  graph=null; greveal=false; drawSwarm(); render(); stream(); poll(); loadGraph(); }
// back / forward between conversations
window.addEventListener("popstate",()=>{ const id=location.hash.slice(1)||null; if(id!==cur) pick(id,true); });
if(cur && !location.hash) history.replaceState({c:cur},"","#"+cur);
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
  if(first) render(); else fresh.forEach(e=>place(log,e));
  if(atEnd) log.scrollTop=log.scrollHeight;
  if(fresh.some(e=>e.kind==="idc"||e.kind==="idc_toggle")) idcUI();
  if(fresh.some(e=>e.kind==="approval")) popups().then(thinking).catch(()=>{});
  if(fresh.some(e=>e.kind==="progress"||e.kind==="status"||(e.kind==="audit"&&["spawn","child_done","merge"].includes(e.event))||(e.kind==="audit"&&e.tool))) graphSoon();
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
$("menu").onclick=()=>{ if(narrow.matches) nav(!document.body.classList.contains("nav")); else { document.body.classList.toggle("collapsed"); requestAnimationFrame(lines); } };
$("scrim").onclick=()=>nav(false);
// first launch on this computer: welcome wizard; demo badge; Quit button (this computer only)
let APP={};
async function appStatus(){ try{ APP=await api("GET","/app/status"); }catch(e){ return; }
  if(APP.first_run && APP.editable){ location.replace("/welcome"); return; }
  $("demobadge").hidden=APP.mode!=="demo"; $("quitlink").hidden=!APP.editable; }
$("quitlink").onclick=async()=>{ if(!confirm(t("set.confirmQuit"))) return;
  try{ await fetch("/app/quit",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":APP.csrf||""},body:"{}"}); }catch(e){}
  document.body.replaceChildren(el("div","sys",t("set.stopped"))); };
// remote mode: a device that is not signed in goes to /connect
fetch("/auth/status").then(r=>r.json()).then(s=>{ if(s.required && !s.authenticated && !tok.value) location.replace("/connect"); }).catch(()=>{});
function clock(ts){ const d=new Date(String(ts||"").replace(/([+-]\d\d)(\d\d)$/,"$1:$2")); return isNaN(d) ? "" : d.toLocaleTimeString(LANG,{hour:"2-digit",minute:"2-digit"}); }
function depth(id){ return id ? id.split(".").length-1 : 0; }
function short(v,n){ const s = typeof v==="string" ? v : JSON.stringify(v); return s && s.length>n ? s.slice(0,n)+"…" : (s||""); }
function badge(s){ return el("span","badge "+s,tr("status",s)); }
function render(){
  const log=$("log"); log.replaceChildren();
  if(!cur){ log.append(el("div","sys",t("chat.intro"))); return; }
  tcur=null; for(const e of cache[cur].events) place(log,e);
  log.scrollTop = log.scrollHeight;
}
// ---- collapsible work trace: tool calls, sub-agents, approvals of one turn go in one block (closed by default);
// the user's message, the final answer and the end-of-turn line stay outside. Approval cards (#popups) never hide.
let tcur=null;
let traceOpen=(()=>{ try{ return localStorage.getItem("traceOpen")==="1"; }catch(e){ return false; } })();
function traceKind(e){
  if(e.kind==="user") return "turn";
  if(e.kind==="message") return (e.final && depth(e.agent)===0) ? "out" : "trace";
  if(e.kind==="audit" || e.kind==="approval" || e.kind==="idc") return "trace";
  return "out";
}
function traceSummary(st){ const p=[t(st.agents===1?"trace.agent1":"trace.agents",{n:st.agents}), t(st.actions===1?"trace.action1":"trace.actions",{n:st.actions})];
  return p.join(" · "); }
function traceCount(st,e){
  if(e.kind==="audit" && e.event==="spawn") st.agents++;
  if(e.kind==="audit" && e.tool) st.actions++;
  if(e.kind==="approval" && e.approval){ if(e.status==="pending") st.pending.add(e.approval); else st.pending.delete(e.approval); }
}
function newTrace(log){ const box=el("div","trace"), head=el("button","trhead"), body=el("div","trbody"), id="tr"+Math.random().toString(36).slice(2,9);
  head.type="button"; head.setAttribute("aria-controls",id); head.setAttribute("aria-expanded",String(traceOpen)); head.title=t("trace.toggle");
  head.append(el("span","chev",traceOpen?"▾":"▸"), el("span","trtitle"), el("span","trsum"), el("span","trpend"), el("i","live"));
  body.id=id; body.hidden=!traceOpen; box.append(head,body); box._st={agents:0,actions:0,pending:new Set(),ended:false};
  head.onclick=()=>{ traceOpen=!traceOpen; try{ localStorage.setItem("traceOpen",traceOpen?"1":"0"); }catch(e){} document.querySelectorAll("#log .trace").forEach(traceSet); };
  log.append(box); return box; }
function traceSet(box){ const head=box.querySelector(".trhead"); head.setAttribute("aria-expanded",String(traceOpen));
  head.querySelector(".chev").textContent=traceOpen?"▾":"▸"; box.querySelector(".trbody").hidden=!traceOpen; }
function traceHead(box){ const st=box._st, h=box.querySelector(".trhead");
  box.classList.toggle("running",!st.ended);
  h.querySelector(".trtitle").textContent=t(st.ended?"trace.titleDone":"trace.title");
  h.querySelector(".trsum").textContent=traceSummary(st);
  const n=st.ended?0:st.pending.size; h.querySelector(".trpend").textContent=n?t(n===1?"trace.pending1":"trace.pending",{n}):""; }
function place(log,e){
  const k=traceKind(e), n=node(e);
  if(k==="turn"){ if(tcur){ tcur._st.ended=true; traceHead(tcur); } tcur=null; if(n) log.append(n); return; }
  if(k==="trace"){ if(!tcur) tcur=newTrace(log); traceCount(tcur._st,e); if(n) tcur.querySelector(".trbody").append(n); traceHead(tcur); return; }
  if(e.kind==="status" && tcur){ tcur._st.ended=["done","stopped","cancelled","error","interrupted"].includes(e.status); traceHead(tcur); }
  if(n) log.append(n);
}
function node(e){
  if(e.kind==="user"){ const r=el("div","row user"), b=el("div","bubble",e.text);
    if((e.attachments||[]).length){ const a=el("div","atts");
      e.attachments.forEach(f=>{ const c=el("span","att","📎 "+f.name+" · "+size(f.bytes)); c.title=f.path; a.append(c); }); b.append(a); }
    const m=el("div","umeta"); m.append(el("span",null,clock(e.ts))); const k=el("span","ticks","✓✓"); k.setAttribute("aria-label",t("chat.sent")); m.append(k); b.append(m);
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
    if(cur && c && BUSY.includes(c.status) && !live) graphSoon();
    if(cur){ stream(); if(!live){ const k=cache[cur], r=await api("GET","/tasks/"+cur+"/events?since="+k.since); add(k, r.events); } }
    await popups(); thinking(); $("err").textContent="";
  }catch(e){ fail(e); }
}
async function popups(){
  const list=(await api("GET","/approvals")).approvals, box=$("popups"), ids=new Set(list.map(a=>a.id));
  [...box.children].forEach(c=>{ if(!ids.has(c.dataset.id) || c.dataset.lang!==LANG) c.remove(); });
  list.forEach(a=>{ if(box.querySelector('[data-id="'+a.id+'"]')) return;
    const conv=tasks.find(x=>x.id===a.task), c=el("div","card"); c.dataset.id=a.id; c.dataset.task=a.task; c.dataset.lang=LANG;
    c.setAttribute("role","alertdialog"); const q=el("div","q",askText(a)); q.id="q-"+a.id; c.setAttribute("aria-labelledby",q.id);
    const top=el("div","ctop"); top.append(el("span","who",a.agent), el("span","cat "+a.category,tr("cat",a.category)));
    const det=el("details"); det.append(el("summary",null,t("card.details")), el("pre",null,a.tool+" "+JSON.stringify(a.args,null,2)));
    c.append(top, q, el("div","meta",t("card.conversation",{name:conv?short(conv.task,60):a.task})), det, el("div","meta",reasonText(a.reason)));
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
$("new").onclick=$("compose").onclick=()=>{ nav(false); pick(null); $("input").focus(); };
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
// ---- live swarm graph: the real agent tree of the current turn (GET /tasks/{id}/graph), refreshed on events
const SVGNS="http://www.w3.org/2000/svg";
const CHECK='<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const DOC='<svg viewBox="0 0 76 92" aria-hidden="true"><defs><linearGradient id="dg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00D4FF"/><stop offset="1" stop-color="#2563EB"/></linearGradient></defs>'+
  '<path d="M8 2h40l22 22v60a6 6 0 0 1-6 6H8a6 6 0 0 1-6-6V8a6 6 0 0 1 6-6z" fill="#0B1530" stroke="url(#dg)" stroke-width="4"/><path d="M48 2v22h22" fill="none" stroke="url(#dg)" stroke-width="4"/>'+
  '<path d="M16 40h40M16 52h40M16 64h28" stroke="#7DD3FC" stroke-width="4" stroke-linecap="round"/></svg>';
let graph=null, gsig="", gmerged={}, gtimer=null, greveal=false;
let swOpen=(()=>{ try{ return localStorage.getItem("swarmOpen")!=="0"; }catch(e){ return true; } })();
const BUSY=["queued","running","cancelling"];
function graphSoon(){ if(gtimer) return; gtimer=setTimeout(()=>{ gtimer=null; loadGraph(); },120); }
async function loadGraph(){ const id=cur; if(!id){ graph=null; drawSwarm(); return; }
  try{ const g=await api("GET","/tasks/"+id+"/graph"); if(id!==cur) return; graph=g; drawSwarm(); }catch(e){} }
function svgEl(tag,attrs){ const e=document.createElementNS(SVGNS,tag); for(const k in attrs) e.setAttribute(k,attrs[k]); return e; }
function agCard(a){ const c=el("div","ag"); c.dataset.id=a.id;
  const top=el("div","agtop"); top.append(el("span","agname",a.id), el("span","agst")); c.append(top, el("div","agrole",a.task||""));
  const p=el("div","prog"), i=el("i"); p.append(i); c.append(p, el("div","agmeta")); c.title=a.task||""; return c; }
function agUpdate(c,a){ const busy=BUSY.includes(a.status);
  c.classList.toggle("done",a.status==="done"); c.classList.toggle("bad",!busy && a.status!=="done");
  c.querySelector(".agst").textContent=tr("status",a.status||"running");
  c.querySelector(".prog i").style.width=Math.round(100*(a.progress||0))+"%";
  c.querySelector(".prog").setAttribute("aria-label",Math.round(100*(a.progress||0))+"%");
  c.querySelector(".agmeta").textContent=(a.max_steps?t("swarm.steps",{s:a.steps||0,max:a.max_steps}):t("swarm.stepsNoMax",{s:a.steps||0}))
    +(a.parent && a.parent!=="root"?" · ↳ "+a.parent:"")+(a.isolated?" · "+t("swarm.isolated"):""); }
function drawSwarm(){
  const box=$("swarm"), g=graph;
  if(!g || !g.children || g.task!==cur){ box.hidden=true; box.replaceChildren(); gsig=""; return; }
  const kids=g.agents.filter(a=>a.id!=="root"), root=g.agents.find(a=>a.id==="root")||{status:g.status};
  const merged=!!g.children_done, key=g.task+":"+g.turn, running=kids.filter(a=>BUSY.includes(a.status)).length;
  const sig=key+"|"+kids.map(a=>a.id).join(",")+"|"+LANG;
  box.hidden=false;
  if(sig!==gsig){ gsig=sig; box.replaceChildren(); box.className="";
    const head=el("button","swhead"); head.type="button"; head.title=t("swarm.toggle"); head.setAttribute("aria-expanded",String(swOpen));
    head.append(el("span","chev","▾"), el("span",null,t("swarm.title")), el("span","sum"));
    head.onclick=()=>{ swOpen=!swOpen; try{ localStorage.setItem("swarmOpen",swOpen?"1":"0"); }catch(e){} box.classList.toggle("closed",!swOpen); head.setAttribute("aria-expanded",String(swOpen)); lines(); };
    const body=el("div","swbody"), svg=svgEl("svg",{class:"swlines","aria-hidden":"true"});
    const left=el("div","swcol left"), right=el("div","swcol right"), center=el("div","swcenter");
    const hub=el("div","hub"), inner=el("div","inner"), core=el("div","core"); core.innerHTML=CHECK; inner.append(core); hub.append(inner);
    const doc=el("a","doc"); doc.href="#"; doc.innerHTML=DOC; const chk=el("span","chk"); chk.innerHTML=CHECK; doc.append(chk);
    doc.title=t("swarm.answer"); doc.onclick=ev=>{ ev.preventDefault(); showAnswer(); };
    const lab=el("div","hublabel"); lab.append(el("span",null,"root"), el("small"));
    center.append(hub, doc, lab);
    kids.forEach((a,i)=>{ (narrow.matches || i%2===0 ? left : right).append(agCard(a)); });
    body.append(svg, left, center, right);
    const foot=el("div","swfoot"); box.append(head, body, foot);
    box.classList.toggle("closed",!swOpen);
    if(merged && gmerged[key]===undefined) gmerged[key]="shown";   // opened after the fact: no animation
  }
  box.querySelector(".swhead .sum").textContent=t("swarm.summary",{n:kids.length,running});
  box.querySelector(".hublabel small").textContent=t("swarm.root")+" · "+tr("status",root.status||g.status);
  kids.forEach(a=>{ const c=box.querySelector('.ag[data-id="'+CSS.escape(a.id)+'"]'); if(c) agUpdate(c,a); });
  foot(g, kids);
  if(merged && gmerged[key]!=="shown"){            // first time we see the swarm finish: merge animation
    gmerged[key]="shown"; lines(); offsets(); box.classList.add("merging");
    setTimeout(()=>{ box.classList.remove("merging"); box.classList.add("merged"); }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 750);
  } else if(merged){ box.classList.add("merged"); }
  box.classList.toggle("reveal",greveal);
  requestAnimationFrame(lines);
}
function foot(g,kids){ const f=$("swarm").querySelector(".swfoot"); f.replaceChildren();
  f.append(el("div",null,t("swarm.merged",{n:kids.length})));
  const conflicts=(g.merges||[]).reduce((n,m)=>n+(m.conflicts||[]).length,0);
  if(conflicts) f.append(el("div","step conflict",t("swarm.conflicts",{n:conflicts})));
  if((g.files||[]).length){ const fl=el("div","files"); fl.append(el("span",null,t("swarm.files")));
    g.files.forEach(p=>{ const a=el("a","fl",p); a.href="/tasks/"+g.task+"/file?path="+encodeURIComponent(p); a.target="_blank"; a.rel="noopener";
      a.title=t("swarm.fileTitle",{path:p}); a.onclick=ev=>{ if(tok.value){ ev.preventDefault(); openFile(g.task,p); } }; fl.append(a); });
    f.append(fl); }
  const acts=el("div","acts"), ans=el("button","linkish",t("swarm.answer")), exp=el("button","linkish",t("swarm.export")), rv=el("button","linkish",t(greveal?"swarm.hide":"swarm.show"));
  ans.type=exp.type=rv.type="button"; ans.onclick=showAnswer; exp.onclick=()=>download("md");
  rv.onclick=()=>{ greveal=!greveal; $("swarm").classList.toggle("reveal",greveal); rv.textContent=t(greveal?"swarm.hide":"swarm.show"); requestAnimationFrame(lines); };
  acts.append(ans, exp, rv); f.append(acts); }
async function openFile(task,p){ const h={}; if(tok.value) h.Authorization="Bearer "+tok.value;
  const r=await fetch("/tasks/"+task+"/file?path="+encodeURIComponent(p),{headers:h}); if(!r.ok){ $("err").textContent=t("err.export",{status:r.status}); return; }
  const url=URL.createObjectURL(new Blob([await r.arrayBuffer()],{type:"text/plain;charset=utf-8"})); window.open(url,"_blank","noopener"); setTimeout(()=>URL.revokeObjectURL(url),60000); }
function showAnswer(){ const b=[...document.querySelectorAll("#log .bubble.final")].pop(); if(!b) return;
  b.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"center"}); b.classList.add("flash"); setTimeout(()=>b.classList.remove("flash"),1600); }
function rel(r,base){ return {x:r.left-base.left, y:r.top-base.top, w:r.width, h:r.height}; }
function lines(){ const box=$("swarm"); if(box.hidden || box.classList.contains("closed")) return;
  const body=box.querySelector(".swbody"), svg=box.querySelector(".swlines"), hub=box.querySelector(".hub"); if(!body||!svg||!hub) return;
  svg.replaceChildren(); const B=body.getBoundingClientRect(), sx=body.scrollLeft, sy=body.scrollTop;
  svg.setAttribute("width",body.scrollWidth); svg.setAttribute("height",body.scrollHeight);
  const H=rel(hub.getBoundingClientRect(),B), cx=H.x+H.w/2+sx, cy=H.y+H.h/2+sy;
  box.querySelectorAll(".ag").forEach(c=>{ const R=rel(c.getBoundingClientRect(),B); let d;
    if(narrow.matches){ const x=R.x+sx, y=R.y+R.h/2+sy, rx=cx; d="M"+rx+","+(cy+H.h/2)+" L"+rx+","+(y-10)+" Q"+rx+","+y+" "+(rx+10)+","+y+" L"+x+","+y; }
    else { const leftSide=R.x+R.w/2<cx, x=(leftSide?R.x+R.w:R.x)+sx, y=R.y+R.h/2+sy, hx=cx+(leftSide?-H.w/2:H.w/2), mx=(x+hx)/2;
      d="M"+hx+","+cy+" C"+mx+","+cy+" "+mx+","+y+" "+x+","+y; }
    svg.append(svgEl("path",{d})); }); }
function offsets(){ const box=$("swarm"), hub=box.querySelector(".hub"); if(!hub) return; const H=hub.getBoundingClientRect();
  box.querySelectorAll(".ag").forEach(c=>{ const R=c.getBoundingClientRect();
    c.style.setProperty("--dx",(H.left+H.width/2-(R.left+R.width/2))+"px"); c.style.setProperty("--dy",(H.top+H.height/2-(R.top+R.height/2))+"px"); }); }
window.addEventListener("resize",()=>requestAnimationFrame(lines));
// ---- "Agent is thinking…" (pulsing dot) while the current conversation runs
function thinking(){ const c=curTask(), box=$("thinking"); const on=!!(c && BUSY.includes(c.status));
  const waiting=on && !!document.querySelector('#popups .card[data-task="'+cur+'"]');
  box.classList.toggle("on",on); $("thinktext").textContent=on?t(waiting?"chat.waiting":"chat.thinking"):""; }
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
onLang = () => { placeholder(); render(); mode(); poll(); quotas(); chips(); idcUI(); drawSwarm(); thinking(); };
render(); appStatus(); setInterval(appStatus,15000); loadConfig(); loadSettings(); setInterval(poll,1000); stream(); poll(); loadGraph(); setInterval(quotas,5000); quotas();
</script></body></html>
"""
CHAT_PAGE = CHAT_PAGE.replace("/*THEME*/", BASE_CSS).replace("/*APPROVAL_JS*/", APPROVAL_JS)
CHAT_PAGE = CHAT_PAGE.replace("/*NAV_CSS*/", NAV_CSS).replace("/*NAV*/", NAV_HTML).replace("/*NAV_JS*/", NAV_JS)
CHAT_PAGE = CHAT_PAGE.replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", LANG_SWITCH).replace("/*I18N_JS*/", I18N_JS)
