// Chimera Console. Plain JavaScript, no build step. Talks to chimera/api.py on the same origin.

import { checkResult, staleWhy } from "./plain.js";

const state = { cases: [], listLoaded: false, listError: null, current: null, tab: "signals", filter: "", recorder: null, live: null,
  busy: false, faceLabel: null, voiceLabel: null };
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ API helpers

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const text = await resp.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (!resp.ok) throw new Error((data && data.error) || `${resp.status} ${resp.statusText}`);
  return data;
}

function toast(message, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), bad ? 7000 : 3500);
}

// ------------------------------------------------------------------ health and case list

async function loadHealth() {
  try {
    const h = await api("/api/health");
    const agents = h.agents.mode === "mock"
      ? `<span class="pill warn" title="No LangFlow configured: the report is written by code from the evidence lines">Agents: mock flow</span>`
      : `<span class="pill ${h.agents.reachable ? "ok" : "bad"}" title="${esc(h.agents.url)}">Agents: LangFlow ${h.agents.reachable ? "reachable" : "unreachable"}</span>`;
    const detector = h.detector.wired_into_pipeline && h.detector.ready
      ? `<span class="pill ok" title="${esc(h.detector.models)}">Video detector: on</span>`
      : h.detector.wired_into_pipeline
        ? `<span class="pill warn" title="Missing: ${esc((h.detector.missing || []).join(", "))}">Video detector: files missing</span>`
        : `<span class="pill ${h.detector.adapter_present ? "warn" : "bad"}" title="video.run_detector() is not wired yet">Video detector: ${h.detector.adapter_present ? "adapter found, not wired" : "not configured"}</span>`;
    const v = h.voice || {};
    // The model names come from the server (/api/health), never from this file.
    state.voiceLabel = v.label || null;
    state.faceLabel = h.detector.label || null;
    const voicePill = !v.on ? `<span class="pill warn" title="CHIMERA_VOICE=off">Voice check: off</span>`
      : !v.label ? `<span class="pill bad" title="CHIMERA_VOICE_MODEL=${esc(v.model)}">Voice check: unknown model</span>`
      : v.reference ? `<span class="pill ok" title="Cut-offs from real recordings through the meeting app, scored with this model">Voice: ${esc(v.label)}</span>`
      : `<span class="pill warn" title="No reference recordings for this model yet, so its scores carry no points">Voice: ${esc(v.label)}, no cut-off</span>`;
    $("#health").innerHTML = `
      <span class="pill ok">Pipeline: ${h.cases} cases</span>
      <span class="pill ${h.watchlist ? "ok" : "warn"}" title="${esc(h.watchlist || "")}">Watchlist: ${h.watchlist ? "loaded" : "none"}</span>
      ${agents}${detector}${voicePill}`;
  } catch (e) {
    $("#health").innerHTML = `<span class="pill bad">Server unreachable</span>`;
  }
}

// The case list. A failed load says so in the list, with a Retry, instead of leaving it empty.
async function loadCases(keepSelection = true) {
  try {
    state.cases = await api("/api/cases");
    state.listError = null;
  } catch (e) {
    // fetch itself fails (TypeError) when the server is not running; say that rather than "Failed to fetch"
    state.listError = e instanceof TypeError ? "the console server did not answer. Is python -m chimera.api running?" : e.message;
  }
  state.listLoaded = true;
  renderCaseList();
  if (!state.listError && keepSelection && state.current) {
    const still = state.cases.find((c) => c.case_id === state.current.case_id);
    if (still) await openCase(state.current.case_id, false).catch((e) => toast(e.message, true));
  }
}

function renderCaseList() {
  const list = $("#case-list");
  list.setAttribute("aria-busy", String(!state.listLoaded));
  if (state.listError) {
    list.innerHTML = `<li class="hint list-msg">Couldn't load the cases: ${esc(state.listError)}
      <button class="btn small" id="list-retry">Retry</button></li>`;
    $("#list-retry").addEventListener("click", () => { loadCases(true); loadHealth(); });
    return;
  }
  const q = state.filter.toLowerCase();
  const items = state.cases.filter((c) => !q || c.case_id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q) || (c.band || "").toLowerCase().includes(q));
  const none = !state.cases.length ? "No cases yet. Use New case to add one." : "No cases match.";
  list.innerHTML = items.map((c) => `
    <li data-id="${esc(c.case_id)}" tabindex="0" class="${state.current && state.current.case_id === c.case_id ? "active" : ""}"${state.current && state.current.case_id === c.case_id ? ' aria-current="true"' : ""}>
      <span class="id">${esc(c.case_id)}</span>
      <span class="score">${c.score === null ? "—" : c.score + "/10"}</span>
      <span class="name">${esc(c.name || "(no name)")}</span>
      <span class="flags">${c.band ? `<span class="band ${esc(c.band)}">${esc(c.band)}</span>` : "not scored"}${c.has_report ? (c.report_stale ? " · report out of date" : " · report") : ""}${c.has_recording ? " · recording" : ""}</span>
    </li>`).join("") || `<li class="hint list-msg">${none}</li>`;
}

// ------------------------------------------------------------------ case view

// A case picked from the list. Keyboard picks keep focus on the (re-drawn) list item; on narrow screens the case opens
// below the list, so a tap scrolls it into view.
async function pickCase(caseId, fromKeyboard = false) {
  try { await openCase(caseId); }
  catch (e) { showCaseError(caseId, e instanceof TypeError ? "The console server did not answer." : e.message); return; }
  if (fromKeyboard) {
    const li = document.querySelector(`#case-list li[data-id="${CSS.escape(caseId)}"]`);
    if (li) li.focus();
  } else if (matchMedia("(max-width: 860px)").matches) {
    $("#main").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }
}

async function openCase(caseId, resetTab = true) {
  state.current = await api(`/api/cases/${encodeURIComponent(caseId)}`);
  if (resetTab) state.tab = state.current.evidence ? state.tab : "signals";
  renderCaseList();
  renderCase();
}

// A case that would not open: say why, with a Retry (the list stays usable).
function showCaseError(caseId, message) {
  $("#main").innerHTML = `<section class="empty"><h1>Couldn't open ${esc(caseId)}</h1><p>${esc(message)}</p>
    <div class="actions"><button class="btn primary" id="case-retry">Retry</button></div></section>`;
  $("#case-retry").addEventListener("click", () => pickCase(caseId));
}

// The Simple view's score dial (glass.css .gdial), coloured by band rather than by score, so a case the rules cap at
// Review shows amber even at 6 or more.
function dial(score, band) {
  const key = { High: "high", Review: "review", Low: "low" }[band] || "none";
  const label = score === null ? "Score not computed" : `Score ${score} of 10, ${band}`;
  return `<div class="gdial sm ${key}" style="--deg:${score === null ? 0 : score * 36}deg" role="img" aria-label="${esc(label)}">
    <div class="gdial-in"><span class="gdial-n">${score === null ? "–" : esc(score)}</span><span class="gdial-of">of 10</span></div></div>`;
}

const TABS = [["signals", "Signals"], ["evidence", "Evidence"], ["analysts", "Analysts"], ["report", "Report"], ["interview", "Interview"]];

function renderCase() {
  const c = state.current;
  const ev = c.evidence;
  const loc = c.location || {};
  const where = [loc.city, loc.state, loc.country].filter(Boolean).join(", ");
  $("#main").innerHTML = `
    <div class="case-head">
      <div>
        <h1>${esc(c.name || c.case_id)}</h1>
        <div class="meta"><span class="mono">${esc(c.case_id)}</span> · submitted ${esc(c.submitted_at || "?")}${where ? " · " + esc(where) : ""}${c.has_resume ? " · resume" : " · no resume"}${c.has_recording ? " · recording" : " · no recording"}</div>
        ${ev ? `<div class="critical"><b>MOST CRITICAL FINDING</b>${esc(ev.critical_line.replace(/^MOST CRITICAL FINDING:\s*/, ""))}</div>` : `<div class="critical"><b>NOT SCORED</b>Collect evidence to score this case.</div>`}
      </div>
      <div class="scorebox">${dial(ev ? ev.score : null, ev ? ev.band : null)}<span class="band ${ev ? esc(ev.band) : "none"}">${ev ? esc(ev.band) : "no score"}</span></div>
    </div>
    <div class="actions">
      <button class="btn primary" id="act-run" ${state.busy ? "disabled" : ""}>Collect evidence</button>
      <button class="btn" id="act-analyze" ${ev && !state.busy ? "" : "disabled"} ${ev ? "" : 'title="Collect evidence first"'}>Run analysts</button>
      <a class="btn" href="/api/cases/${encodeURIComponent(c.case_id)}/files/application.json" target="_blank">application.json</a>
      ${c.has_resume ? `<a class="btn" href="/api/cases/${encodeURIComponent(c.case_id)}/files/${c.files.includes("resume.pdf") ? "resume.pdf" : "resume.txt"}" target="_blank">resume</a>` : ""}
      <button class="btn danger" id="act-delete">Delete case</button>
    </div>
    <div class="tabs" role="tablist" aria-label="Case details">${TABS.map(([id, label]) => `<button class="tab" role="tab" id="tab-${id}" data-tab="${id}"
      aria-controls="panel-${id}" aria-selected="${state.tab === id}" tabindex="${state.tab === id ? 0 : -1}">${label}</button>`).join("")}</div>
    <section class="panel" id="panel-signals" role="tabpanel" aria-labelledby="tab-signals" ${state.tab === "signals" ? "" : "hidden"}>${renderSignals(ev)}</section>
    <section class="panel" id="panel-evidence" role="tabpanel" aria-labelledby="tab-evidence" ${state.tab === "evidence" ? "" : "hidden"}>${c.evidence_md ? `<div class="doc">${markdown(c.evidence_md)}</div>` : `<p class="hint">No evidence yet. Collect evidence to write it.</p>`}</section>
    <section class="panel" id="panel-analysts" role="tabpanel" aria-labelledby="tab-analysts" ${state.tab === "analysts" ? "" : "hidden"}>${renderAnalysts(c)}</section>
    <section class="panel" id="panel-report" role="tabpanel" aria-labelledby="tab-report" ${state.tab === "report" ? "" : "hidden"}>${renderReport(c)}</section>
    <section class="panel" id="panel-interview" role="tabpanel" aria-labelledby="tab-interview" ${state.tab === "interview" ? "" : "hidden"}>${renderInterview(c)}</section>`;

  $("#act-run").addEventListener("click", runPipeline);
  $("#act-analyze").addEventListener("click", () => runAnalysts(c.case_id));
  $("#act-delete").addEventListener("click", async () => {
    const del = $("#act-delete");
    if (!del.dataset.armed) { del.dataset.armed = "1"; del.textContent = "Click again to delete"; return; }
    try {
      await api(`/api/cases/${encodeURIComponent(c.case_id)}`, { method: "DELETE" });
    } catch (e) { toast(e.message, true); return; }
    state.current = null; toast(`Deleted ${c.case_id}`);
    $("#main").innerHTML = `<section class="empty"><h1>Pick a case</h1></section>`;
    loadCases(false); loadHealth();
  });
  // Tabs switch in place (no redraw), so the keyboard focus and a playing video stay where they are. Arrow keys,
  // Home and End move between tabs, as in any tab strip.
  const tabs = [...document.querySelectorAll(".tab")];
  tabs.forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));
  $(".tabs").addEventListener("keydown", (e) => {
    const i = tabs.findIndex((t) => t.dataset.tab === state.tab);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const t = tabs[(next + tabs.length) % tabs.length];
    selectTab(t.dataset.tab);
    t.focus();
  });
  wireInterview(c);
}

function selectTab(id) {
  state.tab = id;
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.tab === id;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll(".panel").forEach((p) => { p.hidden = p.id !== `panel-${id}`; });
}

function renderSignals(ev) {
  if (!ev) return `<p class="hint">Collect evidence to see the signals each collector found, with their evidence IDs.</p>`;
  const families = { A1: "Video", A2: "Resume", A3: "Application & OSINT" };
  return `<div class="families">${Object.entries(families).map(([fam, label]) => {
    const sigs = ev.signals.filter((s) => s.family === fam);
    return `<div class="family"><h3>${fam} ${label}<span class="pts">${ev.family_points[fam]} pts</span></h3>
      ${sigs.length ? sigs.map((s) => `<div class="signal">
        <div class="top"><span class="eid">${esc(s.evidence_id)}</span><span class="st ${esc(s.strength)}">${esc(s.strength)}${s.points ? ` · ${s.points}` : ""}</span><span class="mono code">${esc(s.code)}</span></div>
        <div>${esc(s.text)}</div>
        ${s.data && Object.keys(s.data).length ? `<details><summary>details</summary><pre class="block">${esc(JSON.stringify(s.data, null, 2))}</pre></details>` : ""}
      </div>`).join("") : `<p class="hint">No evidence lines.</p>`}</div>`;
  }).join("")}</div>
  <p class="hint score-line">${esc(ev.score_line)}</p>`;
}

function flowBanner(c) {
  const m = c.flow_meta;
  if (!m) return "";
  if (m.mode === "mock") return `<div class="banner">Mock flow: this text was written by code from the evidence lines on ${esc(m.ran_at)}. The LangFlow agents did not run.</div>`;
  return `<div class="banner ok">LangFlow run on ${esc(m.ran_at)} (${esc(m.langflow_url)}, flow ${esc(m.flow_id)}).</div>`;
}

// Oct 19: the API says when the evidence on file is not the evidence the analysts were given (report_freshness).
function staleBanner(c) {
  if (!c.report_stale) return "";
  return `<div class="banner bad">Out of date. ${esc(staleWhy(c.report_stale_why))} This text and its check describe the old evidence. Run analysts again.</div>`;
}

function checkBanner(text, label, stale) {
  if (!text) return "";
  if (stale) return `<div class="banner">${label}: ran against the old evidence, so its result no longer applies</div>`;
  const clean = checkResult(text).problems === 0;     // the same reading of the check as the Simple view's (plain.js)
  return `<div class="banner ${clean ? "ok" : "bad"}">${label}: ${clean ? "no problems" : "problems found, read the check"}</div>`;
}

function renderAnalysts(c) {
  if (!c.analysts) return `<p class="hint">${c.evidence ? "Run the analysts to see each analyst's notes and the Bundle Check." : "Collect evidence first, then run the analysts to see their notes and the Bundle Check."}</p>`;
  return `${flowBanner(c)}${staleBanner(c)}<div class="two"><div><h3>Analysts' notes and orchestrator</h3><pre class="block">${esc(c.analysts)}</pre></div>
    <div>${checkBanner(c.bundle_check, "Bundle Check", c.report_stale)}<pre class="block">${esc(c.bundle_check || "")}</pre></div></div>`;
}

function renderReport(c) {
  if (!c.report) return `<p class="hint">${c.evidence ? "Run the analysts to produce the report." : "Collect evidence first, then run the analysts to produce the report."}</p>`;
  // Oct 25: the same report as a PDF, with the checks and the most suspicious moments as pictures.
  const pdf = `<p class="hint"><a href="/api/cases/${encodeURIComponent(c.case_id)}/report.pdf" download>Download the report as a PDF</a>, with what code checked and the most suspicious moments as pictures.</p>`;
  return `${flowBanner(c)}${staleBanner(c)}${pdf}<div class="two"><div class="doc">${markdown(c.report)}</div>
    <div>${checkBanner(c.evidence_check, "Evidence Check", c.report_stale)}<pre class="block">${esc(c.evidence_check || "")}</pre></div></div>`;
}

// Accepted recording files (chimera/api.py VIDEO_TYPES and AUDIO_TYPES).
const VIDEO_ACCEPT = ".mp4,.mkv,.webm,.mov,.m4v";
const AUDIO_ACCEPT = ".m4a,.wav,.mp3,.opus,.ogg,.flac,.aac";

function renderInterview(c) {
  const iv = (c.application && c.application.interview) || {};
  const fileUrl = (name) => `/api/cases/${encodeURIComponent(c.case_id)}/files/${encodeURIComponent(name)}`;
  const voiceInput = iv.audio ? "the candidate's own audio track" : "the recording's mixed audio";
  // Model names from /api/health; until it answers, the checks are named by what they do.
  const face = state.faceLabel ? `the face-swap check (${esc(state.faceLabel)})` : "the face-swap check";
  const voice = state.voiceLabel ? `the voice-clone check (${esc(state.voiceLabel)})` : "the voice-clone check";
  return `<div class="capture">
    <div class="card">
      <h3>Recording on file</h3>
      ${c.has_recording ? `<video controls src="${fileUrl(iv.recording)}"></video>
        ${iv.audio ? `<p class="hint">Candidate's own audio track: <a href="${fileUrl(iv.audio)}" target="_blank" rel="noopener">${esc(iv.audio)}</a></p>` : ""}
        <p class="hint">Collect evidence scores this recording: ${face} on the video and ${voice} on ${voiceInput}.</p>
        <div class="row"><button class="btn small danger" id="rec-clear">Remove recording</button></div>`
        : `<p class="hint">No recording yet. ${iv.camera_refused ? "The candidate refused the camera." : ""}</p>`}
    </div>
    <div class="card">
      <h3>Add a recording file</h3>
      <p class="hint">For a meeting recorded in Zoom or Teams: the video file and, if the app saved one, the candidate's own audio track (Zoom: "Record a separate audio file for each participant"; it is in the recording's Audio Record folder).</p>
      <label class="check"><input type="checkbox" id="up-consent"> The candidate has given written consent to record and analyze this interview.</label>
      <div class="row file-row"><label class="hint" for="up-video">Video</label><input type="file" id="up-video" accept="${VIDEO_ACCEPT}"></div>
      <div class="row file-row"><label class="hint" for="up-audio">Candidate's audio track (optional)</label><input type="file" id="up-audio" accept="${AUDIO_ACCEPT}"></div>
      <div class="row"><button class="btn primary" id="up-send" disabled>Add to case</button><span id="up-status" class="hint" role="status"></span></div>
    </div>
    <div class="card">
      <h3>Capture the interview</h3>
      <label class="check"><input type="checkbox" id="consent"> The candidate has given written consent to record and analyze this interview.</label>
      <div class="row">
        <button class="btn primary" id="rec-start" disabled>Record meeting tab</button>
        <button class="btn" id="rec-stop" disabled>Stop and save</button>
        <span id="rec-status" class="hint" role="status"></span>
      </div>
      <p class="hint">Chrome asks which tab or window to share; pick the meeting. Audio is included when you tick "share tab audio". Nothing is asked of the candidate beyond camera on.</p>
    </div>
    <div class="card">
      <h3>Live face check</h3>
      <div class="row"><button class="btn" id="live-start">Follow live_check.py</button><button class="btn" id="live-stop" disabled>Stop</button><span id="live-file" class="hint"></span></div>
      <canvas id="live-strip" class="live-strip" width="600" height="90" role="img" aria-label="Face scores over time against the live check's cut-off"></canvas>
      <div class="row"><span class="verdict wait" id="live-verdict" role="status">waiting for scores</span><span class="hint" id="live-last"></span></div>
      <p class="hint">Run <code>python scripts\\live_check.py</code> (or <code>1</code> for the OBS camera) in a terminal; this panel follows its score log. The live check also saves its five most suspicious moments as pictures beside the log; the Simple view's Interview tab shows them and can save them to the case. The dashed line is the cut-off the log says it used.</p>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ jobs

// One job at a time (the server refuses a second one): while it runs, the buttons that start jobs are disabled.
function setBusy(on) {
  state.busy = on;
  $("#btn-run-all").disabled = on;
  const run = $("#act-run"), analyze = $("#act-analyze");
  if (run) run.disabled = on;
  if (analyze) analyze.disabled = on || !(state.current && state.current.evidence);
}

function showDrawer(title) {
  const d = $("#drawer");
  d.hidden = false;
  $("#drawer-title").textContent = title;
  $("#drawer-status").textContent = "running";
  $("#drawer-status").className = "pill warn";
  $("#drawer-log").textContent = "";
}

function followJob(job, title, onDone) {
  showDrawer(title);
  setBusy(true);
  const es = new EventSource(`/api/jobs/${job.id}/events`);
  const log = $("#drawer-log");
  es.onmessage = (e) => { log.textContent += JSON.parse(e.data).line + "\n"; log.scrollTop = log.scrollHeight; };
  es.addEventListener("status", (e) => {
    const j = JSON.parse(e.data);
    $("#drawer-status").textContent = j.status;
    $("#drawer-status").className = "pill " + (j.status === "done" ? "ok" : "bad");
    es.close();
    setBusy(false);
    onDone && onDone(j);
  });
  es.onerror = () => {
    es.close();
    setBusy(false);
    $("#drawer-status").textContent = "connection lost";
    $("#drawer-status").className = "pill bad";
  };
}

async function runPipeline() {
  try {
    const job = await api("/api/run", { method: "POST" });
    followJob(job, "Collect evidence: python -m chimera run", async (j) => {
      toast(j.status === "done" ? "Evidence collected for every case" : "Pipeline failed, see the log", j.status !== "done");
      await loadCases(true); loadHealth();
    });
  } catch (e) { toast(e.message, true); }
}

async function runAnalysts(caseId) {
  try {
    const job = await api(`/api/cases/${encodeURIComponent(caseId)}/analyze`, { method: "POST" });
    followJob(job, `Run analysts: ${caseId}`, async (j) => {
      if (j.status === "done") { toast(`Report ready (${j.result.mode})`); state.tab = "report"; }
      else toast("Analysts failed, see the log", true);
      await openCase(caseId, false).catch((e) => toast(e.message, true));
      loadCases(false);
    });
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ interview capture (browser APIs, localhost only)

// POST the files with progress (fetch has no upload progress); resolves with the case's interview settings.
function uploadRecording(caseId, video, audio, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("consent", "true");
    if (video) form.append("video", video);
    if (audio) form.append("audio", audio);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/cases/${encodeURIComponent(caseId)}/recording/file`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((100 * e.loaded) / e.total)); };
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error((body && (body.error || body.detail)) || `upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("upload failed: the console did not answer"));
    xhr.send(form);
  });
}

function wireInterview(c) {
  const consent = $("#consent"), start = $("#rec-start"), stop = $("#rec-stop"), status = $("#rec-status");
  if (!consent) return;
  consent.addEventListener("change", () => { start.disabled = !consent.checked || !!state.recorder; });
  const clear = $("#rec-clear");
  if (clear) clear.addEventListener("click", async () => {
    try {
      await api(`/api/cases/${encodeURIComponent(c.case_id)}/interview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clear_recording: true }) });
    } catch (e) { toast(e.message, true); return; }
    toast("Recording removed"); await openCase(c.case_id, false); loadCases(false);
  });

  // a recording file from the meeting app
  const upConsent = $("#up-consent"), upVideo = $("#up-video"), upAudio = $("#up-audio"), upSend = $("#up-send"), upStatus = $("#up-status");
  const upReady = () => { upSend.disabled = !upConsent.checked || !(upVideo.files.length || upAudio.files.length); };
  [upConsent, upVideo, upAudio].forEach((el) => el.addEventListener("change", upReady));
  upSend.addEventListener("click", async () => {
    upSend.disabled = true;
    try {
      await uploadRecording(c.case_id, upVideo.files[0], upAudio.files[0], (pct) => { upStatus.textContent = `uploading ${pct}%`; });
      toast("Recording added to the case. Collect evidence to score it.");
      await openCase(c.case_id, false); loadCases(false);
    } catch (e) { upStatus.textContent = ""; toast(e.message, true); upReady(); }
  });

  let seq = 0, startedAt = 0, chain = Promise.resolve();
  start.addEventListener("click", async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { toast("Tab capture needs Chrome or Edge on localhost", true); return; }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30 }, audio: true });
      const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      state.recorder = rec; seq = 0; startedAt = Date.now();
      rec.ondataavailable = (e) => {
        if (!e.data.size) return;
        const n = seq++;
        chain = chain.then(() => fetch(`/api/cases/${encodeURIComponent(c.case_id)}/recording?seq=${n}`, { method: "POST", body: e.data }))
          .then(() => { status.innerHTML = `<span class="rec"></span> recording, ${((Date.now() - startedAt) / 1000).toFixed(0)} s, ${n + 1} chunks saved`; })
          .catch((err) => toast("Chunk upload failed: " + err.message, true));
      };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        await chain;
        try {
          await api(`/api/cases/${encodeURIComponent(c.case_id)}/interview`, { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ recording_saved: true, consent: true }) });   // the Start button needs the consent box
          toast("Recording saved to the case folder");
        } catch (e) { toast("The recording was saved, but the case wasn't updated: " + e.message, true); }
        state.recorder = null;
        await openCase(c.case_id, false).catch((e) => toast(e.message, true)); loadCases(false);
      };
      stream.getVideoTracks()[0].addEventListener("ended", () => { if (rec.state !== "inactive") rec.stop(); });
      rec.start(2000);
      start.disabled = true; stop.disabled = false;
      status.innerHTML = `<span class="rec"></span> recording`;
    } catch (e) { toast("Capture cancelled or blocked: " + e.message, true); }
  });
  stop.addEventListener("click", () => {
    if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
    stop.disabled = true;
    status.textContent = "saving the recording…";
  });

  // live feed from scripts/live_check.py
  const liveStart = $("#live-start"), liveStop = $("#live-stop"), canvas = $("#live-strip"), verdict = $("#live-verdict"), last = $("#live-last");
  const points = [];
  let cutoff = null;                        // unknown until a log row says which cut-off the live check used
  function draw() {
    const ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
    const css = getComputedStyle(document.documentElement);
    ctx.clearRect(0, 0, w, h);
    if (cutoff !== null) {
      ctx.strokeStyle = css.getPropertyValue("--line-strong").trim(); ctx.lineWidth = 1;
      const cut = h - cutoff * (h - 10) - 5;
      ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(0, cut); ctx.lineTo(w, cut); ctx.stroke(); ctx.setLineDash([]);
    }
    if (!points.length) return;
    const step = Math.max(1, w / 120);
    ctx.strokeStyle = css.getPropertyValue("--accent").trim(); ctx.lineWidth = 2; ctx.beginPath();
    points.slice(-120).forEach((p, i) => { const y = h - 5 - p * (h - 10); i ? ctx.lineTo(i * step, y) : ctx.moveTo(0, y); });
    ctx.stroke();
  }
  // The verdict is a live region: its text changes only when the verdict does, or screen readers repeat it every row.
  const say = (text, kind) => { if (verdict.textContent !== text) verdict.textContent = text; verdict.className = "verdict " + kind; };
  let lastAt = 0;
  const stopFollowing = () => { clearInterval(state.liveTimer); if (state.live) state.live.close(); state.live = null; liveStart.disabled = false; liveStop.disabled = true; };
  stopFollowing();                          // a case redrawn (or another case opened) starts with no feed and no timer
  liveStart.addEventListener("click", () => {
    if (state.live) state.live.close();
    points.length = 0; draw();
    const es = new EventSource("/api/live/events");
    state.live = es; liveStart.disabled = true; liveStop.disabled = false; say("waiting for scores", "wait");
    let fileAt = 0;
    es.addEventListener("file", (e) => { $("#live-file").textContent = "following " + JSON.parse(e.data).file; points.length = 0; fileAt = Date.now(); });
    es.onmessage = (e) => {
      const row = JSON.parse(e.data);
      lastAt = Date.now();
      const replay = lastAt - fileAt < 400;   // the old rows the server sends in one burst on connecting
      const avg = parseFloat(row.average), face = parseFloat(row.face_score), cut = parseFloat(row.cutoff);
      if (!Number.isNaN(cut)) cutoff = cut;
      if (!Number.isNaN(face)) points.push(face);
      draw();
      const v = row.verdict || "";
      if (replay) say(`earlier in the log: ${v}`, "wait");
      else say(v, v.includes("FAKE") ? "fake" : v.includes("real") ? "real" : "wait");
      last.textContent = `${row.seconds} s · face ${Number.isNaN(face) ? "–" : face.toFixed(2)} · average ${Number.isNaN(avg) ? "–" : avg.toFixed(2)}${cutoff === null ? "" : ` · cut-off ${cutoff.toFixed(2)}`}`;
    };
    es.onerror = () => { stopFollowing(); say("feed closed", "wait"); last.textContent = "Follow live_check.py to try again"; };
    // The server replays the newest log from its start even when live_check.py has stopped (it writes two rows a
    // second): five seconds without a row means the last verdict is history, not the call now.
    clearInterval(state.liveTimer);
    state.liveTimer = setInterval(() => { if (lastAt && Date.now() - lastAt > 5000) say("no new readings: is live_check.py running?", "wait"); }, 1000);
  });
  liveStop.addEventListener("click", stopFollowing);
  draw();
}

// ------------------------------------------------------------------ tiny markdown renderer (headings, lists, bold, code)

function inline(s) {
  return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
}

function markdown(md) {
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of md.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { close(); continue; }
    let m;
    if ((m = line.match(/^(#{1,3}) (.*)/))) { close(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); }
    else if ((m = line.match(/^\s*- (.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+\. (.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (list && /^\s{2,}\S/.test(line)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, `<div class="ev">${inline(line.trim())}</div></li>`); }
    else { close(); out.push(`<p>${inline(line)}</p>`); }
  }
  close();
  return out.join("\n");
}

// ------------------------------------------------------------------ new case dialog and boot

function wireDialog() {
  const dlg = $("#dlg-new"), form = $("#form-new"), err = $("#dlg-err"), submit = form.querySelector('button[type="submit"]');
  $("#btn-new").addEventListener("click", () => { form.reset(); err.textContent = ""; dlg.showModal(); });
  $("#dlg-cancel").addEventListener("click", () => dlg.close());
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    if (!fd.get("camera_refused")) fd.set("camera_refused", "false");
    if (!fd.get("identity_consent")) fd.set("identity_consent", "false");
    if (!fd.get("id_face_consent")) fd.set("id_face_consent", "false");
    if (!form.elements.id_document.files.length) fd.delete("id_document");
    // A refusal is shown inside the dialog (a toast would sit behind it); the button says it is saving.
    err.textContent = "";
    submit.disabled = true; submit.textContent = "Creating…";
    try {
      const created = await api("/api/cases", { method: "POST", body: fd });
      dlg.close(); toast(`Created ${created.case_id}`);
      await loadCases(false); loadHealth(); await openCase(created.case_id).catch((e2) => toast(e2.message, true));
    } catch (e2) {
      err.textContent = `The case wasn't created: ${e2.message}`;
    } finally {
      submit.disabled = false; submit.textContent = "Create case";
    }
  });
}

async function boot() {
  wireDialog();
  $("#search").addEventListener("input", (e) => { state.filter = e.target.value; renderCaseList(); });
  $("#case-list").addEventListener("click", (e) => { const li = e.target.closest("li[data-id]"); if (li) pickCase(li.dataset.id); });
  $("#case-list").addEventListener("keydown", (e) => {
    const li = e.target.closest("li[data-id]");
    if (li && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pickCase(li.dataset.id, true); }
  });
  $("#btn-run-all").addEventListener("click", runPipeline);
  // The watchlist admin is a page of the Simple view (simple.js, #/watchlist): go there.
  $("#btn-watchlist").addEventListener("click", () => {
    location.hash = "#/watchlist";
    document.querySelector('[data-view-btn="simple"]').click();
  });
  $("#drawer-close").addEventListener("click", () => { $("#drawer").hidden = true; });
  await loadHealth();
  await loadCases(false);
  const first = location.hash.replace("#", "");
  if (first && state.cases.some((c) => c.case_id === first)) pickCase(first);
}

// The Simple view (simple.js) opens a case here when the recruiter switches to Advanced.
window.chimeraAdvanced = { openCase, loadCases, loadHealth };

boot().catch((e) => toast(e.message, true));
