"""Language handling shared by the harness pages (inserted where the page says /*I18N_JS*/).

Language: ?lang=fr|en (and remembered), else localStorage, else navigator.language (fr* -> fr, else en).
Static text: data-i18n (textContent), data-i18n-title, data-i18n-placeholder. Dynamic text: t(key, {vars}).
"""

I18N_JS = r"""
const I18N = /*I18N_DATA*/{};
const LANGS = Object.keys(I18N), LANG_KEY = "harnessLang";
function pickLang(){
  const q = (new URLSearchParams(location.search).get("lang") || "").toLowerCase().slice(0,2);
  if(LANGS.includes(q)){ try{ localStorage.setItem(LANG_KEY,q); }catch(e){} return q; }
  let s=null; try{ s=localStorage.getItem(LANG_KEY); }catch(e){}
  if(LANGS.includes(s)) return s;
  return (navigator.language||"").toLowerCase().startsWith("fr") ? "fr" : "en";
}
let LANG = pickLang();
function t(k, v){
  let s = (I18N[LANG] && I18N[LANG][k] != null) ? I18N[LANG][k] : (I18N.en[k] != null ? I18N.en[k] : k);
  return v ? s.replace(/\{(\w+)\}/g, (m,n) => (n in v ? String(v[n]) : m)) : s;
}
function tr(prefix, val){ const k = prefix+"."+val; return (I18N.en[k] != null) ? t(k) : String(val == null ? "" : val); }
function applyStatic(){
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-i18n]").forEach(e => { e.textContent = t(e.dataset.i18n); });
  document.querySelectorAll("[data-i18n-title]").forEach(e => { e.title = t(e.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(e => { e.placeholder = t(e.dataset.i18nPlaceholder); });
  const ti = document.querySelector("title[data-i18n-doc]"); if(ti) document.title = t(ti.dataset.i18nDoc);
  document.querySelectorAll("#lang button").forEach(b => b.classList.toggle("on", b.dataset.lang === LANG));
}
let onLang = () => {};
function setLang(l){ if(!LANGS.includes(l)) return; LANG=l; try{ localStorage.setItem(LANG_KEY,l); }catch(e){} applyStatic(); onLang(); }
document.querySelectorAll("#lang button").forEach(b => b.onclick = () => setLang(b.dataset.lang));
applyStatic();
"""

LANG_SWITCH = ('<span id="lang" role="group" data-i18n-title="lang.label">'
               '<button type="button" data-lang="en">EN</button><button type="button" data-lang="fr">FR</button></span>')
LANG_CSS = (" #lang{display:inline-flex;border:1px solid #9aa3b0;border-radius:6px;overflow:hidden}"
            " #lang button{border:0;background:transparent;color:inherit;padding:3px 8px;font:600 11px system-ui,sans-serif;cursor:pointer}"
            " #lang button.on{background:#4062bb;color:#fff}")
