"""The /connect page: sign in with the token or a one-time pairing code (QR), and show a pairing QR code
for a phone. Plain HTML + JS, no external resources, EN/FR."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH

CONNECT_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="connect.pageTitle">autonomous-agent · connect</title>
<style>
 *{box-sizing:border-box} body{margin:0;font:16px/1.5 system-ui,sans-serif;background:#f4f5f7;color:#1d2127}
 header{background:#1d2127;color:#fff;padding:12px 16px;padding-top:max(12px,env(safe-area-inset-top));display:flex;gap:10px;align-items:center}
 header h1{font-size:17px;margin:0;flex:1} header a{color:#9fb4ff;font-size:14px}
 main{max-width:560px;margin:0 auto;padding:16px}
 section{background:#fff;border:1px solid #dde1e6;border-radius:12px;padding:16px;margin-bottom:14px}
 h2{font-size:16px;margin:0 0 8px} p{margin:6px 0} .muted{color:#5a6270;font-size:14px}
 input{width:100%;font-size:16px;padding:12px;border:1px solid #cfd4da;border-radius:10px}
 button,.btn{display:inline-block;width:100%;margin-top:10px;padding:13px;font:600 16px system-ui;border:0;border-radius:10px;background:#4062bb;color:#fff;cursor:pointer;text-align:center;text-decoration:none}
 button.lite{background:#e7ecfa;color:#2f4aa0} button.danger{background:#f7d4d4;color:#9a1d14}
 #qr svg{width:100%;max-width:300px;height:auto;display:block;margin:10px auto;border-radius:8px}
 #qrurl{word-break:break-all;font:13px ui-monospace,monospace;background:#f6f7f9;padding:8px;border-radius:8px}
 .ok{color:#1f7a45;font-weight:600} .err{color:#b3261e;font-weight:600} .warn{background:#fff6e0;border-radius:8px;padding:8px;font-size:14px}
 code{font-size:13px;background:#f0f2f5;padding:1px 4px;border-radius:4px} ol{padding-left:20px;margin:6px 0}
/*LANG_CSS*/
</style></head><body>
<header><h1 data-i18n="connect.heading"></h1><a href="/" data-i18n="link.chat"></a>/*LANG_SWITCH*/</header>
<main>
 <section id="signin" hidden><h2 data-i18n="connect.signin"></h2>
  <p class="muted" data-i18n="connect.signinHelp"></p>
  <input id="tok" type="password" autocomplete="current-password" data-i18n-placeholder="connect.tokenPh">
  <button id="login" data-i18n="connect.loginBtn"></button>
  <p id="msg" aria-live="polite"></p></section>
 <section id="signed" hidden><h2 data-i18n="connect.signedIn"></h2><p id="via" class="muted"></p>
  <a class="btn" href="/" data-i18n="connect.openChat"></a></section>
 <section id="pairing" hidden><h2 data-i18n="connect.pairTitle"></h2>
  <p class="muted" data-i18n="connect.pairHelp"></p>
  <button id="newqr" data-i18n="connect.showQr"></button>
  <div id="qr"></div><p id="qrurl" hidden></p><p id="qrexp" class="muted"></p><p id="qrwarn" class="warn" hidden></p>
  <button id="revoke" class="danger" data-i18n="connect.revokeAll"></button>
  <button id="logout" class="lite" data-i18n="connect.logout"></button></section>
 <section><h2 data-i18n="connect.howTitle"></h2>
  <ol><li data-i18n="connect.how1"></li><li data-i18n="connect.how2"></li><li data-i18n="connect.how3"></li></ol>
  <p class="muted" data-i18n="connect.howMore"></p></section>
</main>
<script>
/*I18N_JS*/
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
onLang = () => refresh();
(async () => {
  const pair = new URLSearchParams(location.search).get("pair");
  if(pair){ history.replaceState(null, "", location.pathname); await login({pair}); } else await refresh();
})();
</script></body></html>
"""
CONNECT_PAGE = CONNECT_PAGE.replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", LANG_SWITCH).replace("/*I18N_JS*/", I18N_JS)
