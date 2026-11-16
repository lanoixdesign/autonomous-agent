"""v0.8.1: "tokens left per minute" counter (chat status bar + dashboard key pool) and the plain
key switch / pause messages. Keys arrive MASKED from the server (GET /keys/rate); never the secret.
Needs t(), el(), api(), LANG and $ from the page."""

RATE_CSS = r"""
 #ratebar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;padding:5px 16px;border-bottom:1px solid var(--line);
  background:var(--card2);font-size:12px;color:var(--soft)}
 #ratebar[hidden]{display:none}
 #ratebar .rnote{flex:1 1 100%;color:var(--warn);font-weight:600}
 #ratebar .rnote:empty{display:none}
 .rate{display:flex;flex-direction:column;gap:2px;min-width:0}
 .rate .rtop{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
 .rate .rtop b{font:600 11.5px ui-monospace,monospace;color:var(--strong)}
 .rate .rest{font-size:10.5px;padding:0 6px;border-radius:9px;border:1px dashed var(--line2,#999);color:var(--muted)}
 .rate .rpause{font-size:10.5px;padding:0 6px;border-radius:9px;background:rgba(245,158,11,.15);color:var(--warn)}
 .rate .rline{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .rate .rbar{height:5px;border-radius:4px;background:var(--sunk,#e5e7eb);overflow:hidden;min-width:120px;max-width:260px}
 .rate .rbar i{display:block;height:100%;background:var(--ok,#22C55E);transition:width .5s}
 .rate .rbar i.mid{background:var(--warn,#F59E0B)} .rate .rbar i.lo{background:var(--bad,#F87171)}
 .rate.compact{flex:0 1 auto} .rate:not(.compact) .rline{white-space:normal} .rate:not(.compact){margin-bottom:6px}
 .sys.keys{color:var(--warn)} .sys.keys.bad{color:var(--bad)} .sys.keys.okk{color:var(--ok)}
 @media (max-width:760px){ #ratebar{padding:4px 10px;font-size:11.5px;gap:4px 10px} .rate .rbar{min-width:90px} .rate .rline{white-space:normal} }
"""

RATE_JS = r"""
// ---- v0.8.1: tokens left per minute (per key, masked) + plain key switch / pause messages
function mk(m){ m=String(m||"?"); return /REDACTED/.test(m) ? "••••" : m.replace("…","••••"); }   // same look as Settings; restored history stays hidden
function rateN(v){ return Math.round(v||0).toLocaleString(LANG); }
function rateBox(k, compact){
  const r=k.rate||{}, d=el("div","rate"+(compact?" compact":"")), top=el("div","rtop");
  top.append(el("b",null,"🔑 "+(compact?"":k.name+" · ")+mk(k.key)));
  if(r.source==="estimate"){ const s=el("span","rest",t("rate.estimated")); s.title=t("rate.estimatedTitle"); top.append(s); }
  else if(r.source==="provider") top.title=t("rate.providerTitle");
  if(k.refused) top.append(el("span","rpause",t("rate.refused")));
  else if(k.cooldown_s) top.append(el("span","rpause",t("rate.paused",{s:k.cooldown_s})));
  d.append(top);
  const when=s=>" · "+(s>0?t("rate.resetIn",{s}):t("rate.full"));
  if(r.tokens_limit){
    const left=Math.max(0,r.tokens_left), pct=Math.max(0,Math.min(100,100*left/r.tokens_limit));
    d.append(el("div","rline",t("rate.tokens",{left:rateN(left),limit:rateN(r.tokens_limit)})+when(r.tokens_reset_s)));
    const b=el("div","rbar"), i=el("i",pct<20?"lo":(pct<50?"mid":"")); i.style.width=pct+"%"; b.append(i);
    b.setAttribute("role","progressbar"); b.setAttribute("aria-valuemin","0"); b.setAttribute("aria-valuemax",String(r.tokens_limit)); b.setAttribute("aria-valuenow",String(left));
    d.append(b);
  } else if(r.tokens_used!=null) d.append(el("div","rline",t("rate.tokensUsed",{n:rateN(r.tokens_used)})));
  if(r.requests_limit && !compact) d.append(el("div","rline",t("rate.requests",{left:rateN(r.requests_left),limit:rateN(r.requests_limit)})+(r.requests_reset_s!=null?when(r.requests_reset_s):"")));
  return d;
}
async function rateFetch(){ try{ return await api("GET","/keys/rate"); }catch(e){ return null; } }
// one plain sentence for a key event ({kind:"keys", action, key_mask, to_mask, seconds, status, backup_kind})
function keysText(e){
  const a=e.action, from=e.from_mask||e.key_mask;
  if(a==="switch") return t(e.status===429||e.status==null?"kw.switch":"kw.switchErr",{from:mk(from),to:mk(e.to_mask),status:e.status})
                          +(e.backup_kind==="same"||!e.backup_kind?"":t("kw.otherUse"));
  if(a==="wait" && e.reason==="network") return t("kw.waitNet",{key:mk(from),s:Math.ceil(e.seconds||0)});
  if(a==="shrink") return t("kw.shrink");
  if(a==="switch" && e.status==null) return t("kw.switchErr",{from:mk(from),to:mk(e.to_mask),status:t("kw.net")});
  if(a==="wait") return from ? t("kw.waitKey",{key:mk(from),s:Math.ceil(e.seconds||0)}) : t("kw.wait",{s:Math.ceil(e.seconds||0)});
  if(a==="resume") return t("kw.resume",{key:mk(from)});
  if(a==="refused") return t("kw.refused");
  if(a==="exhausted") return t("kw.exhausted");
  return null;
}
"""
