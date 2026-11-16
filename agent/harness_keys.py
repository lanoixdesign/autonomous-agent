"""Shared widgets of the Settings page and the wizard (v0.7): paste many API keys at once, and
"who does what?" (task types per key). Pasted keys are kept in page memory and only ever DISPLAYED
masked (first / last 4 characters); they are sent once to the server, which never sends them back."""

KEYS_CSS = r"""
 .bulk,.jobs{text-align:left}
 .bulk .bwhy,.jobs .bwhy,.bwhy{font-weight:700;color:var(--strong);margin:4px 0 2px}
 .bpaste{width:100%;min-height:92px;padding:10px 12px;font:13px var(--mono);border-radius:12px;resize:vertical;-webkit-text-security:disc;
  background:var(--sunk);color:var(--text);border:1px solid var(--line2)}
 .bpaste:focus{outline:2px solid var(--blue);outline-offset:1px}
 .blist,.bres{list-style:none;padding:0;margin:8px 0;display:flex;flex-direction:column;gap:6px;text-align:left}
 .blist li,.bres li{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:7px 10px;border:1px solid var(--line);border-radius:10px;background:var(--sunk);font-size:13px}
 .blist li b{color:var(--strong)} .blist code,.bres code,.jcard code{font:12px var(--mono);color:var(--soft);background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:1px 7px}
 .blist .linkish{margin-left:auto;font-size:12.5px}
 .bres li.ok{border-color:rgba(var(--ok-rgb),0.27)} .bres li.ok span{color:var(--ok);font-weight:600}
 .bres li.bad{border-color:rgba(var(--bad-rgb),0.27)} .bres li.bad span{color:var(--bad);font-weight:600}
 .brows{display:flex;flex-direction:column;gap:6px;margin:6px 0}
 .brow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr) auto;gap:6px;align-items:center}
 .brow input{width:100%;padding:9px 11px;min-height:38px}
 .bacts{margin-top:10px} .bout{margin-top:8px;font-size:13px;text-align:left} .bout.bad{color:var(--bad)}
 .bsum{font-weight:700;color:var(--strong)} .bsum.ok{color:var(--ok)}
 .spin.sm{display:inline-block;width:14px;height:14px;border-width:2px;vertical-align:-2px}
 .jobs{text-align:left}
 .jcard{border:1px solid var(--line2);border-radius:14px;padding:10px 12px;margin:8px 0;background:var(--sunk)}
 .jcard .ptop{display:flex;gap:8px;align-items:center;flex-wrap:wrap} .jcard .pname{color:var(--strong);font-weight:700}
 .jwhy{font-size:13px;color:var(--soft);margin:4px 0 6px}
 .jchip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid var(--line2);border-radius:999px;cursor:pointer;font-size:13px;background:var(--panel)}
 .jchip:has(input:checked){border-color:var(--blue);background:rgba(var(--accent-rgb),0.072);color:var(--strong)}
 .jchip input{accent-color:var(--blue);margin:0;width:16px;height:16px}
 .jmodel summary{font-size:12.5px;margin:6px 0 2px} .jmodel input{max-width:340px}
 .poolbox{border:1px dashed var(--line2);border-radius:14px;padding:10px 14px;margin:10px 0;background:var(--sunk)}
 .poolbox select{width:auto;min-width:220px;margin-left:6px}
 .subp{border:1px solid rgba(var(--accent-rgb),0.24);border-radius:16px;padding:12px 14px;margin-top:12px;background:var(--sunk)}
 .subp[hidden]{display:none}
 @media (max-width:560px){ .brow{grid-template-columns:1fr auto} .brow input[type=text]{grid-column:1 / span 2} .poolbox select{min-width:0;width:100%;margin:6px 0 0} }
"""

KEYS_JS = r"""
// ---- several keys at once. Pasted keys stay in page memory and are only displayed MASKED.
const KTASKS=["research","writing","code","analysis","vision","general"];
function kmask(s){ s=String(s||""); return s.length<=12?"••••":s.slice(0,4)+"••••"+s.slice(-4); }
function kprov(s,prefixes){ s=String(s||"").trim(); for(const [p,v] of (prefixes||[])) if(s.startsWith(p)) return v; return null; }
function ksplit(line){ line=String(line).trim().replace(/^export\s+/i,""); const m=line.match(/^(.*?)[\s:=]*['"]?([^\s'":=]{8,})['"]?[,;]?$/);
  return m ? {label:m[1].replace(/[:=\-–—'"\s]+$/,"").trim().slice(0,60), key:m[2]} : {label:"", key:line}; }
function khint(label){ const l=String(label||"").toLowerCase(); for(const p of ["openrouter","groq","openai","ollama"]) if(l.includes(p)) return p; return null; }
function bulkText(x,pname){ const k=I18N.en["bulkc."+x.code]!=null ? x.code : "error";
  return tr("bulkc",k,{name:x.name||"",prov:x.provider?pname(x.provider):"?",http:x.http_status||"?"}); }
function makeBulk(root,opts){
  const items=[]; root.replaceChildren(); root.classList.add("bulk");
  const ta=el("textarea","bpaste"); ta.rows=4; ta.spellcheck=false; ta.setAttribute("autocomplete","off"); ta.setAttribute("autocapitalize","off");
  ta.placeholder=t("bulk.ph"); ta.setAttribute("aria-label",t("bulk.title"));
  const list=el("ul","blist"), rows=el("div","brows"), add=el("button","linkish",t("bulk.addRow")), go=el("button","primary",t("bulk.go")), cnt=el("span","muted bcount"), out=el("div","bout");
  add.type=go.type="button"; list.setAttribute("aria-live","polite"); out.setAttribute("aria-live","polite");
  const acts=el("div","row bacts"); acts.append(go,cnt);
  root.append(el("p","bwhy",t("bulk.why")), el("p","muted",t("bulk.help")), ta, list, rows, add, el("p","muted",t("bulk.hidden")), acts, out);
  function take(text){ String(text||"").split(/\r?\n/).forEach(l=>{ const s=l.trim(); if(!s || s.startsWith("#")) return; items.push(ksplit(s)); }); draw(); }
  function flush(){ if(ta.value.trim()){ const v=ta.value; ta.value=""; take(v); } else ta.value=""; }
  ta.addEventListener("paste",e=>{ const d=e.clipboardData||window.clipboardData; if(!d) return; e.preventDefault(); take(d.getData("text")); });
  ta.addEventListener("input",()=>{ if(/\n/.test(ta.value)) flush(); });
  ta.addEventListener("keydown",e=>{ if(e.key==="Enter"){ e.preventDefault(); flush(); } });
  ta.addEventListener("blur",flush);
  function rowItems(){ return [...rows.querySelectorAll(".brow")].map(r=>({label:r.querySelector("input[type=text]").value.trim(), key:r.querySelector("input[type=password]").value.trim()})).filter(x=>x.key); }
  function count(){ const n=items.length+rowItems().length; cnt.textContent=n?t("bulk.count",{n}):""; }
  function draw(){ list.replaceChildren();
    items.forEach((it,i)=>{ const li=el("li"), p=kprov(it.key,opts.prefixes())||khint(it.label);
      li.append(el("b",null,it.label||(p?opts.pname(p):"?")), el("code",null,kmask(it.key)), el("span","pill "+(p?"blue":"bad"),p?opts.pname(p):t("bulk.unknownProv")));
      const x=el("button","linkish",t("bulk.remove")); x.type="button"; x.onclick=()=>{ items.splice(i,1); draw(); }; li.append(x); list.append(li); });
    count(); }
  function newRow(){ const r=el("div","brow"), a=el("input"), b=el("input"), x=el("button","ibtn","✕");
    a.type="text"; a.maxLength=60; a.placeholder=t("bulk.rowLabel"); a.setAttribute("aria-label",t("bulk.rowLabel"));
    b.type="password"; b.autocomplete="new-password"; b.spellcheck=false; b.placeholder=t("bulk.rowKey"); b.setAttribute("aria-label",t("bulk.rowKey"));
    x.type="button"; x.title=t("bulk.remove"); x.setAttribute("aria-label",t("bulk.remove")); x.onclick=()=>{ r.remove(); if(!rows.children.length) newRow(); count(); };
    b.addEventListener("input",count); r.append(a,b,x); rows.append(r); return b; }
  add.onclick=()=>newRow().focus(); newRow();
  go.onclick=async()=>{ flush(); const all=items.concat(rowItems());
    if(!all.length){ out.className="bout bad"; out.textContent=t("bulk.none"); return; }
    const text=all.map(x=>(x.label?x.label.replace(/[:=\r\n]/g," ").trim()+": ":"")+x.key).join("\n");
    go.disabled=true; out.className="bout"; out.replaceChildren(el("span","spin sm"), document.createTextNode(" "+t("bulk.testing",{n:all.length})));
    let r; try{ r=await api("POST","/app/providers/bulk",{text}); }catch(e){ go.disabled=false; out.textContent=""; return fail(e); }
    go.disabled=false; items.length=0; rows.replaceChildren(); newRow(); draw();
    const ul=el("ul","bres"); r.results.forEach(x=>{ const li=el("li",x.ok?"ok":"bad"); li.append(el("code",null,x.key||"—"), el("span",null,bulkText(x,opts.pname))); ul.append(li); });
    out.replaceChildren(el("div","bsum"+(r.failed?"":" ok"),t("bulk.result",{ok:r.saved,bad:r.failed})), ul);
    if(opts.onSaved) opts.onSaved(r); };
  return {take};
}
// ---- who does what: task types per key (proposal from the server, the user accepts or adjusts)
function makeJobs(root,prop,onDone,noTitle){ root.replaceChildren(); root.hidden=false; root.classList.add("jobs");
  if(!noTitle) root.append(el("h3",null,t("jobs.title")));
  root.append(el("p","bwhy",t("jobs.proposed")), el("p","muted",t("jobs.help")));
  (prop||[]).forEach(p=>{ const c=el("div","jcard"); c.dataset.id=p.id;
    const top=el("div","ptop"); top.append(el("span","pname",p.name)); if(p.key) top.append(el("code",null,p.key)); if(p.model) top.append(el("span","pill blue",p.model));
    const ch=el("div","chips"); KTASKS.forEach(k=>{ const l=el("label","jchip"), i=el("input"); i.type="checkbox"; i.value=k; i.checked=(p.tasks||[]).includes(k); l.append(i, el("span",null,tr("task",k))); ch.append(l); });
    const md=el("details","jmodel"), mi=el("input"); md.append(el("summary",null,t("jobs.model"))); mi.type="text"; mi.value=p.model||""; mi.setAttribute("aria-label",t("jobs.model")+" · "+p.name); md.append(mi);
    c.append(top, el("p","jwhy",tr("jobs.why",p.why)+((p.tasks||[]).includes("vision")?" "+t("jobs.vision"):"")), ch, md); root.append(c); });
  const acts=el("div","row"), ok=el("button","primary",t("jobs.accept")), sk=el("button","grey",t("jobs.skip")); ok.type=sk.type="button";
  ok.onclick=async()=>{ const assign={}; root.querySelectorAll(".jcard").forEach(c=>{ const pp=(prop||[]).find(x=>x.id===c.dataset.id)||{}, m=c.querySelector(".jmodel input").value.trim();
      assign[c.dataset.id]={tasks:[...c.querySelectorAll("input:checked")].map(i=>i.value)}; if(m && m!==(pp.model||"")) assign[c.dataset.id].model=m; });
    ok.disabled=true; try{ await api("POST","/app/providers/tasks",{assign}); toast(t("jobs.saved")); if(onDone) onDone(true); }catch(e){ fail(e); } ok.disabled=false; };
  sk.onclick=()=>{ if(onDone) onDone(false); }; acts.append(ok,sk); root.append(acts);
}
function taskList(tasks){ return (tasks&&tasks.length) ? tasks.map(k=>tr("task",k)).join(", ") : t("jobs.any"); }
"""
