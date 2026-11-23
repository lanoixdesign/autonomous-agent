"""The /connect page: sign in with the token or a one-time pairing code (QR), and show a pairing QR code
for a phone. Plain HTML + JS, no external resources, EN/FR."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH
from .theme import BASE_CSS, CONNECT_CSS, MENU_BTN, NAV_CSS, NAV_HTML, NAV_JS, THEME_BTN, TIP_CSS, TIP_JS, sidebar

CONNECT_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="connect.pageTitle">autonomous-agent · connect</title>
<style>
 *{box-sizing:border-box} body{margin:0;font:16px/1.5 system-ui,sans-serif;background:#f4f5f7;color:#1d2127}
 header{background:var(--panel2);color:var(--strong);padding:12px 16px;padding-top:max(12px,env(safe-area-inset-top));display:flex;gap:10px;align-items:center}
 header h1{font-size:17px;margin:0} header a{color:#9fb4ff;font-size:14px}
 main{max-width:560px;margin:0 auto;padding:16px}
 section{background:#fff;border:1px solid #dde1e6;border-radius:12px;padding:16px;margin-bottom:14px}
 h2{font-size:16px;margin:0 0 8px} p{margin:6px 0} .muted{color:#5a6270;font-size:14px}
 input{width:100%;font-size:16px;padding:12px;border:1px solid #cfd4da;border-radius:10px}
 button,.btn{display:inline-block;width:100%;margin-top:10px;padding:13px;font:600 16px system-ui;border:0;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer;text-align:center;text-decoration:none}
 button.lite{background:#e7ecfa;color:#2f4aa0} button.danger{background:#f7d4d4;color:#9a1d14}
 #qr svg{width:100%;max-width:300px;height:auto;display:block;margin:10px auto;border-radius:8px}
 #qrurl{word-break:break-all;font:13px ui-monospace,monospace;background:#f6f7f9;padding:8px;border-radius:8px}
 .ok{color:#1f7a45;font-weight:600} .err{color:#b3261e;font-weight:600} .warn{background:#fff6e0;border-radius:8px;padding:8px;font-size:14px}
 .apil{border:1px solid #dde1e6;border-radius:10px;padding:10px 12px;margin:8px 0} .apil b{font-size:15px} .apil .u{font:13px ui-monospace,monospace;word-break:break-all}
 .apil .bdg{display:inline-block;font-size:12px;background:#eef1f6;border-radius:999px;padding:1px 8px;margin:4px 4px 0 0}
 .apil .acts{display:flex;gap:8px} .apil .acts button{width:auto;padding:8px 14px;font-size:14px;margin-top:8px}
 #apiadd>summary{cursor:pointer;font-weight:600;margin:10px 0 4px} details.adv>summary{cursor:pointer;margin:10px 0 4px}
 label.f{display:block;font-weight:600;font-size:14px;margin:10px 0 4px} label.ck{display:flex;gap:8px;align-items:flex-start;margin:10px 0;font-size:15px} label.ck input{width:auto;margin-top:4px}
 #apimsg.ok,#apimsg.err{margin-top:8px}
 .presets{display:flex;gap:8px;flex-wrap:wrap} .presets button{width:auto;flex:1 1 140px;margin-top:4px} p.f{font-weight:600;font-size:14px;margin:14px 0 4px}
 .apil{border-color:var(--line,#dde1e6)!important}
 .mcps .top{display:flex;justify-content:space-between;gap:8px;align-items:baseline} .mcps .st{font-size:13px;white-space:nowrap}
 .mcps .st::before{content:"\25CF\00a0"} .st-connected{color:var(--ok,#1f7a45)} .st-error{color:var(--bad,#b3261e)} .st-off,.st-untested{color:var(--muted,#5a6270)}
 .mcps .st-off::before,.mcps .st-untested::before{content:"\25CB\00a0"} .mcps .why{margin:6px 0 0;font-size:14px} .small{font-size:13px!important;word-break:break-all}
 .mcps details.can>summary{cursor:pointer;font-size:14px;margin-top:6px} .mcps ul{margin:4px 0 0;padding-left:20px;font-size:14px}
 .mcps .acts{flex-wrap:wrap;align-items:center} label.sw{margin:8px 0 0 auto;font-size:14px}
 textarea{width:100%;font:14px ui-monospace,monospace;padding:10px;border:1px solid #cfd4da;border-radius:10px}
 code{font-size:13px;background:#f0f2f5;padding:1px 4px;border-radius:4px} ol{padding-left:20px;margin:6px 0}
/*LANG_CSS*/
/*THEME*/
</style></head><body data-page="connect">
/*SIDEBAR*/
<header class="apphead">/*MENU_BTN*/<h1 data-i18n="connect.heading"></h1></header>
<main>
 <section id="signin" hidden><h2 data-i18n="connect.signin"></h2>
  <p class="muted" data-i18n="connect.signinHelp"></p>
  <input id="tok" type="password" autocomplete="current-password" data-i18n-placeholder="connect.tokenPh">
  <button id="login" data-i18n="connect.loginBtn"></button>
  <p id="msg" aria-live="polite"></p></section>
 <section id="signed" hidden><h2 data-i18n="connect.signedIn"></h2><p id="via" class="muted"></p>
  <a class="btn mobonly" href="/" data-i18n="connect.openChat"></a></section>
 <section id="pairing" hidden><h2 data-i18n="connect.pairTitle"></h2>
  <p class="muted" data-i18n="connect.pairHelp"></p>
  <button id="newqr" data-i18n="connect.showQr"></button>
  <div id="qr"></div><p id="qrurl" hidden></p><p id="qrexp" class="muted"></p><p id="qrwarn" class="warn" hidden></p>
  <button id="revoke" class="danger" data-i18n="connect.revokeAll"></button>
  <button id="logout" class="lite" data-i18n="connect.logout"></button></section>
 <section id="mcp" hidden><h2><span data-i18n="mcp.title"></span><button class="tip" data-tip="mcp.tip"></button></h2>
  <p class="muted" data-i18n="mcp.help"></p>
  <div id="mcplist"></div>
  <div id="mcpadd"><p class="f" data-i18n="mcp.addTitle"></p>
   <div class="presets"><button type="button" class="lite" data-preset="files" data-i18n="mcp.p.files"></button><button type="button" class="lite" data-preset="github" data-i18n="mcp.p.github"></button><button type="button" class="lite" data-preset="web" data-i18n="mcp.p.web"></button></div>
   <form id="mcpform" hidden autocomplete="off">
    <p id="mcpintro" class="muted"></p>
    <p id="mcpneeds" class="warn" hidden></p>
    <div data-f="folder"><label class="f" for="mfolder" data-i18n="mcp.folder"></label><input id="mfolder" maxlength="300"><p class="muted" data-i18n="mcp.folderHelp"></p></div>
    <div data-f="url"><label class="f" for="murl" data-i18n="mcp.url"></label><input id="murl" type="url" maxlength="300" data-i18n-placeholder="mcp.urlPh"></div>
    <div data-f="command"><label class="f" for="mcmd" data-i18n="mcp.command"></label><input id="mcmd" maxlength="500" data-i18n-placeholder="mcp.commandPh"></div>
    <div data-f="token"><label class="f" for="mtoken" data-i18n="mcp.token"></label><input id="mtoken" type="password" autocomplete="new-password"><p class="muted"><span id="mtokenhelp"></span> <a id="mtokenlink" target="_blank" rel="noopener" hidden data-i18n="mcp.tokenLink"></a></p></div>
    <div data-f="env"><label class="f" for="menv" data-i18n="mcp.env"></label><textarea id="menv" rows="2" data-i18n-placeholder="mcp.envPh"></textarea></div>
    <div data-f="name"><label class="f" for="mname" data-i18n="mcp.name"></label><input id="mname" maxlength="40" data-i18n-placeholder="mcp.namePh"></div>
    <button id="mcpsave" type="submit" data-i18n="mcp.addTest"></button><button id="mcpcancel" type="button" class="lite" data-i18n="mcp.cancel"></button>
   </form>
   <details class="adv"><summary data-i18n="mcp.advanced"></summary><p class="muted" data-i18n="mcp.advancedHelp"></p>
    <button type="button" class="lite" data-preset="custom" data-i18n="mcp.p.custom"></button></details>
  </div>
  <p id="mcpmsg" aria-live="polite"></p></section>
 <section id="apis" hidden><h2><span data-i18n="apis.title"></span><button class="tip" data-tip="apis.help"></button></h2>
  <div id="apilist"></div>
  <details id="apiadd"><summary data-i18n="apis.addTitle"></summary>
  <form id="apiform" autocomplete="off">
   <label class="f" for="apiname" data-i18n="apis.name"></label><input id="apiname" required maxlength="40" data-i18n-placeholder="apis.namePh">
   <label class="f" for="apibase" data-i18n="apis.base"></label><input id="apibase" type="url" required data-i18n-placeholder="apis.basePh">
   <label class="f" for="apival" data-i18n="apis.value"></label><input id="apival" type="password" autocomplete="new-password" data-i18n-placeholder="apis.valuePh">
   <details class="adv"><summary data-i18n="ui.advanced"></summary>
   <label class="f" for="apihdr" data-i18n="apis.header"></label><input id="apihdr" value="Authorization">
   <label class="f" for="apispec" data-i18n="apis.spec"></label><input id="apispec" type="url" data-i18n-placeholder="apis.specPh">
   <label class="f" for="apidesc" data-i18n="apis.desc"></label><input id="apidesc" maxlength="300"></details>
   <label class="ck"><input type="checkbox" id="apiauto"><span data-i18n="apis.autoGet"></span></label>
   <label class="ck"><input type="checkbox" id="apispend"><span data-i18n="apis.spends"></span></label>
   <button id="apisave" type="submit" data-i18n="apis.add"></button><button id="apicancel" type="button" class="lite" hidden data-i18n="apis.cancel"></button>
   <p id="apimsg" aria-live="polite"></p></form></details>
  <details class="adv"><summary data-i18n="ui.advanced"></summary><p class="muted" data-i18n="apis.how"></p></details></section>
 <section id="how"><details><summary><h2 style="display:inline" data-i18n="connect.howTitle"></h2></summary>
  <ol><li data-i18n="connect.how1"></li><li data-i18n="connect.how2"></li><li data-i18n="connect.how3"></li></ol>
  <p class="muted" data-i18n="connect.howMore"></p></details></section>
</main>
<script>
/*I18N_JS*/
/*NAV_JS*/
/*TIP_JS*/
const $ = id => document.getElementById(id);
async function api(method, path, body){
  const r = await fetch(path, {method, headers: {"Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({})); if(!r.ok){ const e = new Error(j.error || ("HTTP " + r.status)); e.status = r.status; throw e; } return j;
}
let status = {}, timer = null;
async function refresh(){
  try{ status = await api("GET", "/auth/status"); }catch(e){ status = {}; }
  const authed = !!status.authenticated;
  $("signin").hidden = authed; $("signed").hidden = !authed;
  $("pairing").hidden = !(authed && status.required);
  $("via").textContent = authed ? tr("connect.via", status.via) : "";
}
async function login(body){
  $("msg").className = ""; $("msg").textContent = t("connect.signingIn");
  try{ await api("POST", "/auth/login", body); $("msg").className = "ok"; $("msg").textContent = t("connect.success");
    setTimeout(() => location.replace("/"), 900); }
  catch(e){ $("msg").className = "err"; $("msg").textContent = e.status === 429 ? t("connect.tooMany") : t("connect.failed"); }
  await refresh();
}
$("login").onclick = () => { const v = $("tok").value.trim(); if(v) login({token: v}); };
$("tok").addEventListener("keydown", e => { if(e.key === "Enter") $("login").click(); });
$("newqr").onclick = async () => {
  try{ const r = await api("POST", "/auth/pair", {});
    $("qr").innerHTML = r.svg; $("qrurl").hidden = false; $("qrurl").textContent = r.url;
    const local = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])/.test(r.url);
    $("qrwarn").hidden = !local; $("qrwarn").textContent = t("connect.localOnly");
    let left = r.expires_in; clearInterval(timer);
    const tick = () => { $("qrexp").textContent = left > 0 ? t("connect.expires", {m: Math.floor(left/60), s: String(left%60).padStart(2,"0")}) : t("connect.expired"); left--; if(left < -1) clearInterval(timer); };
    tick(); timer = setInterval(tick, 1000);
  }catch(e){ $("qrexp").textContent = e.message; }
};
$("revoke").onclick = async () => { if(!confirm(t("connect.revokeConfirm"))) return; try{ const r = await api("POST", "/auth/revoke-all", {}); alert(t("connect.revoked", {n: r.sessions})); }catch(e){} refresh(); };
$("logout").onclick = async () => { try{ await api("POST", "/auth/logout", {}); }catch(e){} refresh(); };
// ---- business APIs (v0.9): the secret is sent once and only shown masked afterwards
let CSRF = "", APIS = [], editing = null;
async function capi(method, path, body){
  const h = {"Content-Type": "application/json"}; if(CSRF) h["X-CSRF-Token"] = CSRF;
  const r = await fetch(path, {method, headers: h, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({})); if(!r.ok){ const e = new Error(j.error || ("HTTP " + r.status)); e.status = r.status; e.code = j.code; throw e; } return j;
}
function mk(tag, cls, txt){ const e = document.createElement(tag); if(cls) e.className = cls; if(txt != null) e.textContent = txt; return e; }
function apiMsg(txt, bad){ $("apimsg").className = bad ? "err" : "ok"; $("apimsg").textContent = txt; }
function drawApis(){ const box = $("apilist"); box.replaceChildren();
  if(!APIS.length) box.append(mk("p", "muted", t("apis.none")));
  APIS.forEach(a => { const d = mk("div", "apil"); d.append(mk("b", null, a.name), mk("div", "u", a.base_url));
    if(a.description) d.append(mk("div", "muted", a.description));
    const b = mk("div"); [t(a.auto_get ? "apis.reads.auto" : "apis.reads.ask"), a.spends ? t("apis.spendsBadge") : null,
      a.auth_set ? t("apis.secret", {mask: a.auth_mask}) : t("apis.noSecret"), a.endpoints ? t("apis.endpoints", {n: a.endpoints}) : null]
      .filter(Boolean).forEach(x => b.append(mk("span", "bdg", x))); d.append(b);
    const acts = mk("div", "acts"), ed = mk("button", "lite", t("apis.edit")), del = mk("button", "danger", t("apis.delete"));
    ed.type = del.type = "button"; ed.onclick = () => edit(a);
    del.onclick = async () => { if(!confirm(t("apis.deleteConfirm", {name: a.name}))) return;
      try{ await capi("POST", "/app/apis/" + a.id + "/delete", {}); apiMsg(t("apis.deleted")); await loadApis(); }catch(e){ apiMsg(e.message, true); } };
    acts.append(ed, del); d.append(acts); box.append(d); });
}
function edit(a){ editing = a ? a.id : null;
  $("apiname").value = a ? a.name : ""; $("apibase").value = a ? a.base_url : ""; $("apihdr").value = a ? (a.auth_header || "Authorization") : "Authorization";
  $("apival").value = ""; $("apival").placeholder = a && a.auth_set ? t("apis.valueKeep") : t("apis.valuePh");
  $("apispec").value = a ? (a.openapi_url || "") : ""; $("apidesc").value = a ? (a.description || "") : "";
  $("apiauto").checked = !!(a && a.auto_get); $("apispend").checked = !!(a && a.spends);
  $("apisave").textContent = t(a ? "apis.save" : "apis.add"); $("apicancel").hidden = !a; if(a){ $("apiadd").open = true; $("apiname").focus(); } }
async function loadApis(){
  try{ const st = await capi("GET", "/app/status"); CSRF = st.csrf || ""; const r = await capi("GET", "/app/apis"); APIS = r.apis || []; $("apis").hidden = false; drawApis(); if(!APIS.length) $("apiadd").open = true;
    if(st.editable === false){ $("apiform").hidden = true; apiMsg(t("apis.locked"), true); }
  }catch(e){ $("apis").hidden = true; }
}
$("apiform").onsubmit = async ev => { ev.preventDefault();
  const body = {name: $("apiname").value.trim(), base_url: $("apibase").value.trim(), auth_header: $("apihdr").value.trim(),
    openapi_url: $("apispec").value.trim(), description: $("apidesc").value.trim(), auto_get: $("apiauto").checked, spends: $("apispend").checked};
  if($("apival").value) body.auth_value = $("apival").value;
  try{ await capi("POST", "/app/apis" + (editing ? "/" + editing : ""), body); $("apival").value = "";
    apiMsg(t(editing ? "apis.saved" : "apis.added")); edit(null); await loadApis(); }
  catch(e){ apiMsg(e.status === 403 && e.code === "locked" ? t("apis.locked") : e.message, true); } };
// ---- connected services (MCP, v0.9.8): presets need one field at most; secrets only shown masked
let MCPS = [], PRESETS = [], mform = null, mediting = null, mopen = {};
function mcpMsg(txt, bad){ $("mcpmsg").className = bad ? "err" : "ok"; $("mcpmsg").textContent = txt || ""; }
function mcpWhy(err){ if(!err) return ""; const p = err.params || {};
  const k = "mcp.why." + err.code; const s = t(k, p); return s === k ? t("mcp.why.other") : s; }
function linkTo(href, txt){ const a = mk("a", null, txt); a.href = href; a.target = "_blank"; a.rel = "noopener"; return a; }
function drawMcp(){
  const box = $("mcplist"); box.replaceChildren();
  if(!MCPS.length) box.append(mk("p", "muted", t("mcp.none")));
  MCPS.forEach(s => {
    const card = mk("div", "apil mcps"), top = mk("div", "top");
    const st = s.status === "ready" ? "connected" : s.status;
    top.append(mk("b", null, s.name), mk("span", "st st-" + st, tr("mcp.st", st)));
    card.append(top);
    if(s.status === "error"){ const w = mk("p", "why", mcpWhy(s.error));
      if(s.error && s.error.params && s.error.params.link){ w.append(" "); w.append(linkTo(s.error.params.link, t("mcp.install", {program: s.error.params.program}))); }
      card.append(w);
      if(s.error && s.error.params && s.error.params.detail) card.append(mk("p", "muted small", s.error.params.detail)); }
    const n = (s.tools || []).length, ro = (s.tools || []).filter(x => x.read_only).length;
    card.append(mk("p", "muted small", s.where + (n ? " · " + t("mcp.can", {n, ro}) : "")));
    if(n){ const d = mk("details", "can"); d.open = !!mopen[s.id]; d.ontoggle = () => { mopen[s.id] = d.open; };
      d.append(mk("summary", null, t("mcp.whatCan")));
      const ul = mk("ul");
      s.tools.slice(0, 30).forEach(x => { const li = mk("li", null, x.title + " "); li.title = x.description || "";
        li.append(mk("span", "muted", x.read_only ? t("mcp.readOnly") : t("mcp.asks"))); ul.append(li); });
      d.append(ul); card.append(d); }
    const acts = mk("div", "acts"), test = mk("button", "lite", t("mcp.test")), ed = mk("button", "lite", t("mcp.edit")),
          del = mk("button", "danger", t("mcp.delete")), sw = mk("label", "ck sw"), cb = mk("input");
    cb.type = "checkbox"; cb.checked = s.enabled; sw.append(cb, mk("span", null, t("mcp.on")));
    test.onclick = async () => { test.disabled = true; test.textContent = t("mcp.testing"); mcpMsg("");
      try{ const r = await capi("POST", "/app/mcp/" + s.id + "/test", {}); mopen[s.id] = r.status !== "error";
        mcpMsg(r.status === "error" ? t("mcp.testBad", {name: s.name}) : t("mcp.testOk", {name: s.name, n: (r.tools || []).length}), r.status === "error"); }
      catch(e){ mcpMsg(e.message, true); } await loadMcp(); };
    cb.onchange = async () => { try{ await capi("POST", "/app/mcp/" + s.id + "/enable", {enabled: cb.checked});
      mcpMsg(t(cb.checked ? "mcp.enabled" : "mcp.disabled", {name: s.name})); }catch(e){ mcpMsg(e.message, true); } await loadMcp(); };
    ed.onclick = () => openForm(s.preset || "custom", s);
    del.onclick = async () => { if(!confirm(t("mcp.deleteConfirm", {name: s.name}))) return;
      try{ await capi("POST", "/app/mcp/" + s.id + "/delete", {}); mcpMsg(t("mcp.deleted", {name: s.name})); }catch(e){ mcpMsg(e.message, true); } await loadMcp(); };
    acts.append(test, ed, del, sw); card.append(acts); box.append(card);
  });
}
const MF = {files: ["folder"], github: ["token"], web: ["url", "token", "name"], custom: ["command", "env", "name"]};
function openForm(preset, s){
  mform = preset; mediting = s ? s.id : null;
  if(!preset){ $("mcpform").hidden = true; return; }
  const p = PRESETS.find(x => x.id === preset) || {};
  $("mcpform").hidden = false;
  document.querySelectorAll("#mcpform [data-f]").forEach(d => { d.hidden = !MF[preset].includes(d.dataset.f); });
  $("mcpintro").textContent = tr("mcp.intro", preset);
  const miss = p.program && !p.installed;
  $("mcpneeds").hidden = !miss; $("mcpneeds").replaceChildren();
  if(miss){ $("mcpneeds").append(t("mcp.needs", {program: p.program}) + " ", linkTo(p.link, t("mcp.install", {program: p.program}))); }
  $("mfolder").value = s && s.preset === "files" ? s.where : (p.default_folder || "");
  $("murl").value = s && s.transport === "http" && preset !== "github" ? s.where : "";
  $("mcmd").value = s && preset === "custom" ? s.where : ""; $("menv").value = "";
  $("mname").value = s && preset !== "files" && preset !== "github" ? s.name : "";
  $("mtoken").value = ""; $("mtoken").placeholder = s && s.token_set ? t("mcp.tokenKeep", {mask: s.token_mask}) : (preset === "github" ? "github_pat_…" : t("mcp.tokenOpt"));
  $("mtokenhelp").textContent = t(preset === "github" ? "mcp.tokenGithub" : "mcp.tokenHelp");
  $("mtokenlink").hidden = !p.token_link; if(p.token_link) $("mtokenlink").href = p.token_link;
  $("mcpsave").textContent = t(s ? "mcp.save" : "mcp.addTest");
  const first = MF[preset][0]; setTimeout(() => { const el = {folder: "mfolder", url: "murl", command: "mcmd", token: "mtoken"}[first]; if(el) $(el).focus(); }, 0);
}
document.querySelectorAll("[data-preset]").forEach(b => { b.onclick = () => { mcpMsg(""); openForm(b.dataset.preset, null); }; });
$("mcpcancel").onclick = () => openForm(null);
$("mcpform").onsubmit = async ev => { ev.preventDefault();
  const body = {preset: mform, lang: LANG};
  const f = MF[mform];
  if(f.includes("folder")) body.folder = $("mfolder").value.trim();
  if(f.includes("url")) body.url = $("murl").value.trim();
  if(f.includes("command")) body.command = $("mcmd").value.trim();
  if(f.includes("name") && $("mname").value.trim()) body.name = $("mname").value.trim();
  if(f.includes("env") && $("menv").value.trim()) body.env = $("menv").value;
  if(f.includes("token") && $("mtoken").value.trim()) body.token = $("mtoken").value.trim();
  if(mform === "web" && !body.name){ try{ body.name = new URL(body.url).hostname.replace(/^www\.|^mcp\./, "").split(".")[0] || "Service"; }catch(e){} }
  if(mform === "custom" && !body.name) body.name = (body.command || "").split(/\s+/).pop().split("/").pop().replace(/^@/, "").slice(0, 40) || "Service";
  const btn = $("mcpsave"); btn.disabled = true; btn.textContent = t("mcp.testing"); mcpMsg("");
  try{ const r = await capi("POST", "/app/mcp" + (mediting ? "/" + mediting : ""), body); $("mtoken").value = "";
    mopen[r.id] = r.status !== "error"; openForm(null);
    mcpMsg(r.status === "error" ? t("mcp.addedBad", {name: r.name}) : t(mediting ? "mcp.saved" : "mcp.added", {name: r.name, n: (r.tools || []).length}), r.status === "error"); }
  catch(e){ const k = "mcp.err." + e.code, m = t(k, e.params || {}); mcpMsg(m === k ? e.message : m, true); }
  btn.disabled = false; btn.textContent = t(mediting ? "mcp.save" : "mcp.addTest"); await loadMcp(); };
async function loadMcp(){
  try{ if(!CSRF){ const st = await capi("GET", "/app/status"); CSRF = st.csrf || ""; if(st.editable === false){ $("mcpadd").hidden = true; } }
    const r = await capi("GET", "/app/mcp"); MCPS = r.servers || []; PRESETS = r.presets || []; $("mcp").hidden = false; drawMcp(); }
  catch(e){ $("mcp").hidden = true; }
}
$("apicancel").onclick = () => edit(null);
onLang = () => { refresh(); drawApis(); drawMcp(); if(mform) openForm(mform, MCPS.find(x => x.id === mediting) || null); edit(APIS.find(a => a.id === editing) || null); };
(async () => {
  const pair = new URLSearchParams(location.search).get("pair");
  if(pair){ history.replaceState(null, "", location.pathname); await login({pair}); } else await refresh();
  if(status.authenticated || !status.required){ await loadApis(); loadMcp(); } edit(null);
})();
</script></body></html>
"""
CONNECT_PAGE = CONNECT_PAGE.replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", THEME_BTN + LANG_SWITCH).replace("/*I18N_JS*/", I18N_JS)
CONNECT_PAGE = CONNECT_PAGE.replace("/*THEME*/", BASE_CSS + CONNECT_CSS + NAV_CSS + TIP_CSS)
CONNECT_PAGE = CONNECT_PAGE.replace("/*SIDEBAR*/", sidebar()).replace("/*MENU_BTN*/", MENU_BTN).replace("/*NAV*/", NAV_HTML).replace("/*NAV_JS*/", NAV_JS).replace("/*TIP_JS*/", TIP_JS)
