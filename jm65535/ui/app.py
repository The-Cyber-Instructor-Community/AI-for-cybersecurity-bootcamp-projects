"""
AI SOC Co-pilot — live dashboard (decoupled UI service).

The pipeline POSTs stage events here (common.ui_report); the browser streams them
live via Server-Sent Events. Case notes render in an in-page side panel (no
external markdown app). Optional per-case "View in Wazuh" link (WAZUH_DASHBOARD_URL).

Run:  .venv/bin/python ui/app.py   (then open http://localhost:5001)
"""

from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path

from flask import Flask, Response, request, jsonify, render_template_string

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "cases"
import sys as _sys
_sys.path.insert(0, str(ROOT))
from common import TECHNIQUE_NAMES  # noqa: E402
WAZUH_DASHBOARD_URL = os.environ.get("WAZUH_DASHBOARD_URL", "")  # e.g. https://<host>

app = Flask(__name__)
_subscribers: list[queue.Queue] = []
_events: list[dict] = []
_lock = threading.Lock()


def _publish(ev: dict) -> None:
    with _lock:
        _events.append(ev)
        for q in list(_subscribers):
            q.put(ev)


@app.post("/event")
def event():
    _publish(request.get_json(force=True))
    return {"ok": True}


@app.get("/stream")
def stream():
    q: queue.Queue = queue.Queue()
    with _lock:
        backlog = list(_events)
        _subscribers.append(q)

    def gen():
        try:
            for ev in backlog:
                yield f"data: {json.dumps(ev)}\n\n"
            while True:
                yield f"data: {json.dumps(q.get())}\n\n"
        finally:
            with _lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/note/<case_id>")
def note(case_id: str):
    """Render a case note as HTML for the in-page side panel."""
    matches = list(CASES.glob(f"*{case_id}.md"))
    if not matches:
        return "<p class='mut'>note not found yet</p>"
    md = matches[0].read_text(encoding="utf-8")
    try:
        import markdown as _md
        return _md.markdown(md, extensions=["fenced_code", "tables"])
    except Exception:
        return "<pre>" + md.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"


@app.get("/cases")
def cases():
    out = []
    for f in sorted(CASES.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:15]:
        try:
            c = json.loads(f.read_text())
        except Exception:
            continue
        t = c.get("triage") or {}
        r = c.get("response") or {}
        out.append({
            "case_id": c.get("case_id"), "created": c.get("created_at", "")[:19],
            "rule_id": c.get("alert", {}).get("rule", {}).get("id"),
            "alert_id": c.get("alert", {}).get("id"),
            "timestamp": c.get("alert", {}).get("timestamp"),
            "file_path": c.get("alert", {}).get("syscheck", {}).get("path"),
            "description": c.get("alert", {}).get("rule", {}).get("description", ""),
            "techniques": c.get("techniques", []),
            "verdict": t.get("verdict"), "confidence": t.get("confidence"),
            "actions": r.get("proposed_actions", []), "note_path": c.get("note_path"),
        })
    return jsonify(out)


@app.get("/")
def index():
    return render_template_string(PAGE, wazuh_url=WAZUH_DASHBOARD_URL,
                                  names=json.dumps(TECHNIQUE_NAMES))


PAGE = r"""
<!doctype html><html><head><meta charset="utf-8"><title>AI SOC Co-pilot</title>
<style>
  :root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--fg:#e6edf3;--mut:#8b949e;
        --mal:#f85149;--amb:#d29922;--ben:#3fb950;--acc:#58a6ff}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
  a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
  header{padding:16px 24px;border-bottom:1px solid var(--bd);display:flex;
     align-items:center;gap:12px;position:sticky;top:0;background:var(--bg);z-index:2}
  header h1{font-size:18px;margin:0} .dot{width:9px;height:9px;border-radius:50%;
     background:var(--ben);box-shadow:0 0 8px var(--ben)}
  .mut{color:var(--mut)} #wrap{max-width:900px;margin:0 auto;padding:20px}
  .case{background:var(--card);border:1px solid var(--bd);border-radius:10px;
     padding:16px;margin-bottom:16px;animation:in .3s ease}
  @keyframes in{from{opacity:0;transform:translateY(-6px)}to{opacity:1}}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .tech{font:12px ui-monospace,monospace;background:#21262d;border:1px solid var(--bd);
     padding:1px 7px;border-radius:20px;color:var(--acc)}
  .badge{font-weight:700;text-transform:uppercase;font-size:12px;padding:3px 10px;border-radius:6px}
  .malicious{background:rgba(248,81,73,.15);color:var(--mal)}
  .ambiguous{background:rgba(210,153,34,.15);color:var(--amb)}
  .benign{background:rgba(63,185,80,.15);color:var(--ben)}
  .stage{margin-top:12px;padding-top:12px;border-top:1px dashed var(--bd)}
  .stage h4{margin:0 0 6px;font-size:12px;letter-spacing:.06em;color:var(--mut);text-transform:uppercase}
  .act{display:flex;gap:8px;align-items:center;margin:4px 0;font-size:13px}
  .pill{font-size:11px;padding:1px 8px;border-radius:20px;font-weight:600}
  .ok{background:rgba(63,185,80,.15);color:var(--ben)}
  .no{background:rgba(248,81,73,.15);color:var(--mal)}
  .wait{background:rgba(210,153,34,.15);color:var(--amb)}
  .links{margin-top:8px;font-size:13px;display:flex;gap:16px}
  code{font:12px ui-monospace,monospace;color:#c9d1d9;background:#0d1117;padding:1px 5px;border-radius:4px;border:1px solid var(--bd)}
  .empty{color:var(--mut);text-align:center;padding:60px}
  /* side panel */
  #panel{position:fixed;top:0;right:0;height:100%;width:min(560px,90vw);background:var(--card);
     border-left:1px solid var(--bd);transform:translateX(100%);transition:transform .25s ease;
     z-index:5;display:flex;flex-direction:column;box-shadow:-12px 0 30px rgba(0,0,0,.4)}
  #panel.open{transform:translateX(0)}
  #panelhead{padding:14px 18px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}
  #panelclose{cursor:pointer;color:var(--mut);font-size:18px} #panelclose:hover{color:var(--fg)}
  #panelbody{padding:18px;overflow:auto} #panelbody h1{font-size:20px} #panelbody h2{font-size:16px;color:var(--acc)}
  #panelbody pre{background:#0d1117;border:1px solid var(--bd);border-radius:6px;padding:10px;overflow:auto;font-size:12px}
  #panelbody code{font-size:12px} #panelbody table{border-collapse:collapse} #panelbody td,#panelbody th{border:1px solid var(--bd);padding:4px 8px}
</style></head><body>
<header><span class="dot"></span><h1>AI SOC Co-pilot</h1>
  <span class="mut">live triage → response → notes</span></header>
<div id="wrap"><div class="empty" id="empty">Waiting for alerts… run the pipeline to see cases stream in.</div></div>
<div id="panel"><div id="panelhead"><b id="paneltitle">Case note</b><span id="panelclose">✕</span></div><div id="panelbody"></div></div>
<script>
const WAZUH="{{ wazuh_url }}";
const NAMES={{ names|safe }};
const wrap=document.getElementById('wrap'), empty=document.getElementById('empty');
const panel=document.getElementById('panel'), pbody=document.getElementById('panelbody'), ptitle=document.getElementById('paneltitle');
document.getElementById('panelclose').onclick=()=>panel.classList.remove('open');
document.addEventListener('click',e=>{
  const a=e.target.closest('.notelink');
  if(a){e.preventDefault(); ptitle.textContent='Case '+a.dataset.case.slice(0,8)+' — note';
    fetch('/note/'+a.dataset.case).then(r=>r.text()).then(h=>{pbody.innerHTML=h; panel.classList.add('open');});}
});
const cards={};
function card(id){ if(cards[id]) return cards[id]; empty.style.display='none';
  const el=document.createElement('div'); el.className='case'; el.id='case-'+id;
  el.innerHTML=`<div class="row"><b>Case ${id.slice(0,8)}</b>
    <span class="badge" data-verdict style="display:none"></span>
    <span class="techs row" style="gap:6px"></span></div>
    <div class="desc mut" style="margin-top:6px"></div>
    <div class="alink links" style="margin-top:6px"></div>
    <div class="s-triage"></div><div class="s-resp"></div><div class="s-note"></div>`;
  wrap.prepend(el); cards[id]=el; return el; }
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function wzLink(rid, ts){
  // Pin the ONE detection: rule.id + a ±5s window around the alert's own timestamp
  // (Wazuh keeps the alert `id` in _source but it isn't a searchable term).
  if(!WAZUH || !rid) return '';
  let g='(time:(from:now-30d,to:now))';
  const t=Date.parse((ts||'').replace(/([+-]\d{2})(\d{2})$/,'$1:$2'));
  if(!isNaN(t)){ const f=new Date(t-5000).toISOString(), to=new Date(t+5000).toISOString(); g=`(time:(from:'${f}',to:'${to}'))`; }
  const u=`${WAZUH}/app/threat-hunting#/overview/?tab=general&_g=${g}&_a=(query:(language:kuery,query:'rule.id:${rid}'))`;
  return `<a href="${u}" target="_blank">🔍 View this alert in Wazuh</a>`;
}
function render(ev){
  const el=card(ev.case_id);
  if(ev.stage==='alert'){
    el.dataset.ruleId=ev.rule_id||''; el.dataset.alertId=ev.alert_id||''; el.dataset.ts=ev.timestamp||'';
    el.querySelector('.desc').textContent=ev.description||'';
    el.querySelector('.techs').innerHTML=(ev.techniques||[]).map(t=>{
      const n=NAMES[t]; return `<span class="tech" title="${esc(t)}${n?' — '+esc(n):''}">${esc(t)}${n?' · '+esc(n):''}</span>`;
    }).join('');
    el.querySelector('.alink').innerHTML=wzLink(ev.rule_id||'', ev.timestamp||'');
  }
  if(ev.stage==='triage'){
    const b=el.querySelector('[data-verdict]'); b.style.display=''; b.className='badge '+ev.verdict; b.textContent=ev.verdict;
    el.querySelector('.s-triage').innerHTML=`<div class="stage"><h4>Triage</h4>
      <div class="row"><span>Verdict <b class="${ev.verdict}">${ev.verdict}</b> · confidence <b>${ev.confidence}</b></span>
      <span class="mut">· ${ev.tool_calls} tool calls · RAG ${ev.rag||0} cases</span></div></div>`;
  }
  if(ev.stage==='response'){
    const items=(ev.items||[]).map(it=>{
      const st=it.approved===true?'<span class="pill ok">approved</span>':it.approved===false?'<span class="pill no">rejected</span>':'<span class="pill wait">pending</span>';
      return `<div class="act">${st}<b>${esc(it.action)}</b><span class="mut">${esc(it.target_desc||'')}</span></div>`;
    }).join('')||'<div class="mut">no state-changing actions</div>';
    el.querySelector('.s-resp').innerHTML=`<div class="stage"><h4>Response
      ${ev.evidence?'· <span class="mut">evidence preserved</span>':''}
      ${ev.dry_run?'· <span class="mut">(dry-run)</span>':'· <span class="pill ok">executed</span>'}</h4>${items}</div>`;
  }
  if(ev.stage==='note'){
    el.querySelector('.s-note').innerHTML=`<div class="stage"><h4>Case note</h4>
      <div class="links"><a href="#" class="notelink" data-case="${ev.case_id}">📄 open case note</a></div></div>`;
  }
}
fetch('/cases').then(r=>r.json()).then(list=>{
  list.reverse().forEach(c=>{
    render({stage:'alert',case_id:c.case_id,rule_id:c.rule_id,alert_id:c.alert_id,timestamp:c.timestamp,description:c.description,techniques:c.techniques});
    if(c.verdict) render({stage:'triage',case_id:c.case_id,verdict:c.verdict,confidence:c.confidence,tool_calls:'—',rag:'—'});
    if(c.actions&&c.actions.length) render({stage:'response',case_id:c.case_id,items:c.actions.map(a=>({action:a,approved:null})),dry_run:true});
    if(c.note_path) render({stage:'note',case_id:c.case_id,note_path:c.note_path});
  });
});
new EventSource('/stream').onmessage=e=>render(JSON.parse(e.data));
</script></body></html>
"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5001)), threaded=True)
