"""The Help page (/help): how the app works in 4 steps, a sample approval card, plain-language FAQ, display
options (larger text) and a link back to the guided tour. Plain HTML + JS, no external resources, EN/FR."""
from .i18n_js import I18N_JS, LANG_CSS, LANG_SWITCH
from .theme import BASE_CSS, MENU_BTN, NAV_CSS, NAV_HTML, NAV_JS, THEME_BTN, TIP_CSS, TIP_JS, sidebar

HELP_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title data-i18n-doc="help.pageTitle">autonomous-agent · help</title>
<style>
/*THEME*/
 *{box-sizing:border-box} body{margin:0;font-size:15px;line-height:1.55;min-height:100vh}
 main{max-width:880px;margin:0 auto;padding:22px 18px 48px}
 h1{color:var(--text);font-size:28px;margin:6px 0 8px} h2{color:var(--text);font-size:19px;margin:26px 0 10px}
 .intro{font-size:16px;color:var(--soft);max-width:680px}
 .steps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:16px}
 .step{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:0 10px 30px rgba(0,0,0,.3)}
 .step b{display:block;color:var(--strong);font-size:17px;margin-bottom:4px} .step .ic{display:none} .step .ic::before{content:attr(data-ic)}
 .sample{max-width:420px;background:var(--panel2);border:1px solid var(--line2);border-radius:16px;padding:16px 18px;text-align:center;margin:8px 0}
 .sample .q{font-size:17px;font-weight:700;color:var(--strong)} .sample .q2{font-size:13px;color:var(--soft)}
 .sample .btns{display:flex;gap:10px;margin-top:12px} .sample span.b{flex:1;padding:12px;border-radius:999px;font-weight:700;color:#fff}
 .sample .ok{background:#16A34A} .sample .no{background:#4B5563}
 details{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin:8px 0}
 details summary{cursor:pointer;color:var(--text);font-weight:700} details p{margin:8px 0 2px;color:var(--soft)}
 .row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
 .btn{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:999px;border:1px solid var(--line2);background:var(--panel2);color:var(--text)!important;
  font:600 14px var(--font);text-decoration:none;cursor:pointer;min-height:42px}
 .btn.primary{background:var(--accent);border-color:transparent}
 .switch{display:inline-flex;align-items:center;gap:10px;cursor:pointer;font-weight:600;color:var(--text)}
 .switch input{appearance:none;width:42px;height:24px;border-radius:999px;background:var(--chip);border:1px solid var(--line2);position:relative;cursor:pointer;margin:0}
 .switch input::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#D1D5DB;transition:left .2s}
 .switch input:checked{background:var(--accent);border-color:transparent} .switch input:checked::after{left:20px;background:#fff}
 .muted{color:var(--muted)}
 @media (max-width:760px){ .steps{grid-template-columns:1fr} main{padding:14px 12px 40px} h1{font-size:24px} }
/*TIP_CSS*/
/*NAV_CSS*/
/*LANG_CSS*/
</style></head><body data-page="help">
/*SIDEBAR*/
<header class="apphead mob">/*MENU_BTN*/<h1 data-i18n="nav.help"></h1></header>
<main>
 <h1 data-i18n="help.title"></h1>
 <p class="intro" data-i18n="help.intro"></p>
 <div class="steps">
  <div class="step"><div class="ic" aria-hidden="true" data-ic="💬"></div><b data-i18n="help.s1.t"></b><span data-i18n="help.s1.d"></span></div>
  <div class="step"><div class="ic" aria-hidden="true" data-ic="🛡️"></div><b data-i18n="help.s2.t"></b><span data-i18n="help.s2.d"></span>
   <div class="sample" aria-hidden="true"><div class="q" id="sampleq"></div><div class="q2" data-i18n="card.question"></div>
    <div class="btns"><span class="b ok" data-i18n="card.allow"></span><span class="b no" data-i18n="card.refuse"></span></div></div></div>
  <div class="step"><div class="ic" aria-hidden="true" data-ic="📁"></div><b data-i18n="help.s3.t"></b><span data-i18n="help.s3.d"></span></div>
  <div class="step"><div class="ic" aria-hidden="true" data-ic="⏹️"></div><b data-i18n="help.s4.t"></b><span data-i18n="help.s4.d"></span></div>
 </div>
 <div class="row" style="margin-top:16px"><a class="btn primary" href="/?tour=1" data-i18n="help.tour"></a><a class="btn" href="/" data-i18n="wiz.open"></a></div>
 <h2 data-i18n="help.faq"></h2>
 <details><summary data-i18n="help.q1"></summary><p data-i18n="help.a1"></p></details>
 <details><summary data-i18n="help.q2"></summary><p data-i18n="help.a2"></p></details>
 <details><summary data-i18n="help.q3"></summary><p data-i18n="help.a3"></p></details>
 <details><summary data-i18n="help.q4"></summary><p data-i18n="help.a4"></p></details>
 <details><summary data-i18n="help.q5"></summary><p data-i18n="help.a5"></p></details>
 <h2 data-i18n="help.display"></h2>
 <label class="switch"><input type="checkbox" id="big"><span data-i18n="help.big"></span></label>
 <p class="muted"><span data-i18n="help.mode"></span> <a href="/settings#general" data-i18n="nav.settings"></a></p>
 <p class="muted"><a href="https://github.com/lanoixdesign/autonomous-agent#readme" target="_blank" rel="noopener noreferrer" data-i18n="help.more"></a></p>
</main>
<script>
/*I18N_JS*/
/*NAV_JS*/
/*TIP_JS*/
const $ = id => document.getElementById(id);
$("big").checked = document.documentElement.classList.contains("big");
$("big").onchange = e => setBig(e.target.checked);
function sample(){ $("sampleq").textContent = tr("human","write",{who:t("who.agent"),path:"report.md"}); }
onLang = sample; sample();
</script></body></html>
"""
HELP_PAGE = HELP_PAGE.replace("/*THEME*/", BASE_CSS).replace("/*TIP_CSS*/", TIP_CSS).replace("/*NAV_CSS*/", NAV_CSS)
HELP_PAGE = HELP_PAGE.replace("/*SIDEBAR*/", sidebar()).replace("/*MENU_BTN*/", MENU_BTN).replace("/*NAV*/", NAV_HTML).replace("/*LANG_CSS*/", LANG_CSS).replace("/*LANG_SWITCH*/", THEME_BTN + LANG_SWITCH)
HELP_PAGE = HELP_PAGE.replace("/*I18N_JS*/", I18N_JS).replace("/*NAV_JS*/", NAV_JS).replace("/*TIP_JS*/", TIP_JS)
