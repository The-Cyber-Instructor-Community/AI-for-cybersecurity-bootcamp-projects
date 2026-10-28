// Chimera Console, Simple view (design handoff "glass", Oct 18). Plain JavaScript, no build step.
// The recruiter's view: band, score and plain-language reasons per case, and one button that runs the whole check.
// The Advanced view (app.js) keeps evidence IDs, analyst notes, the Bundle and Evidence Checks and the job log.
// Chimera never addresses the candidate (Oct 18): no questions to ask them, nothing asked of them beyond camera on.

import { BAND_WORD, bandKey, checkResult, headlineFor, liveReading, liveSource, reasonsFor, staleWhy, whyFor } from "./plain.js";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const BAND_RANK = { High: 0, Review: 1, Low: 2 };

const S = {
  cases: [], loaded: false, health: undefined, offline: false,
  page: "cases", caseId: null, tab: "summary", detail: null, detailError: null, detailLoading: false, routeToken: 0,
  runs: {},                                   // caseId -> {status: running|failed, steps, error}
  recorder: null, recCase: null, recStart: 0, recTimer: null, recChunks: 0, recStopping: false,
  live: null, liveRow: null, liveAt: 0, liveFileAt: 0, liveReplay: false, liveTimer: null, liveFile: "", liveClosed: false,
  liveFramesTimer: null, liveFramesKey: null,   // the live check's most suspicious moments (Oct 25)
};

// ------------------------------------------------------------------ server

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const text = await resp.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (!resp.ok) {
    const err = new Error((data && data.error) || `${resp.status} ${resp.statusText}`);
    err.status = resp.status;                 // 404 means "no such case", anything else is worth a retry
    err.body = data;                          // a 409 names the job that is already running
    throw err;
  }
  return data;
}

function toast(message, bad = false) {
  const el = document.createElement("div");
  el.className = "gtoast" + (bad ? " bad" : "");
  el.textContent = message;
  $("#gtoasts").appendChild(el);
  setTimeout(() => el.remove(), bad ? 8000 : 4000);
}

async function loadCases() {
  try { S.cases = await api("/api/cases"); S.offline = false; }
  catch { S.offline = true; }
  S.loaded = true;
}

// The case on screen. A failed load keeps its reason, so the page can say "not found" or offer a retry. An answer
// that arrives after the recruiter has moved to another case is dropped (it would show the old case at the new address).
async function loadDetail(caseId) {
  try {
    const d = await api(`/api/cases/${encodeURIComponent(caseId)}`);
    if (caseId !== S.caseId) return;
    S.detail = d; S.detailError = null;
  } catch (e) {
    if (caseId !== S.caseId) return;
    S.detail = null;
    // fetch itself fails (TypeError) when the server is not running; say that rather than "Failed to fetch"
    S.detailError = { status: e.status || 0, message: e instanceof TypeError ? "The console server did not answer." : e.message };
  }
}

// ------------------------------------------------------------------ health: one status line

function healthLine(h) {
  if (!h) return { kind: "bad", text: "Server unreachable" };
  if (h.agents.mode === "langflow" && h.agents.reachable === false) return { kind: "bad", text: "LangFlow unreachable" };
  if (h.detector.wired_into_pipeline && !h.detector.ready) return { kind: "warn", text: "Face check files missing" };
  if (h.agents.mode === "mock") return { kind: "warn", text: "Analysts using the mock flow" };
  return { kind: "ok", text: "All systems ready" };
}

async function loadHealth() {
  try { S.health = await api("/api/health"); } catch { S.health = null; }
  const line = healthLine(S.health);
  const el = $("#gstatus");
  el.className = `gstatus ${line.kind}`;
  el.innerHTML = `<i aria-hidden="true"></i><span>${esc(line.text)}</span>`;
  el.title = S.health ? `${line.text} · ${S.health.cases} cases · watchlist ${S.health.watchlist ? "loaded" : "none"}` : line.text;
}

// ------------------------------------------------------------------ Simple / Advanced switch (remembered per browser)

function setView(view) {
  document.body.dataset.view = view;
  document.documentElement.dataset.view = view;
  document.querySelectorAll("[data-view-btn]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.viewBtn === view)));
  try { localStorage.setItem("chimera.view", view); } catch { /* private window: the switch still works */ }
  if (view === "advanced") {
    stopLive();
    const adv = window.chimeraAdvanced;
    if (adv) adv.loadCases(false).then(() => (S.page === "case" && S.caseId ? adv.openCase(S.caseId) : null)).catch(() => {});
  } else {
    refresh();
  }
}

// ------------------------------------------------------------------ routes: #/cases, #/case/<id>[/interview], #/interviews, #/reports, #/watchlist

function parseRoute() {
  const [page, id, tab] = location.hash.replace(/^#\/?/, "").split("/");
  if (page === "case" && id) return { page: "case", caseId: decodeURIComponent(id), tab: tab === "interview" ? "interview" : "summary" };
  if (page === "interviews" || page === "reports" || page === "watchlist") return { page, caseId: null, tab: "summary" };
  return { page: "cases", caseId: null, tab: "summary" };
}

// e: the hashchange event when the recruiter moved; undefined on the first load (focus then stays where it is).
async function route(e) {
  const r = parseRoute();
  const moved = r.page !== S.page || r.caseId !== S.caseId;
  const token = ++S.routeToken;                    // a newer route() wins; this one stops after its await
  if (!(r.page === "case" && r.tab === "interview")) stopLive();
  Object.assign(S, r);
  if (S.page === "case") {
    // Another case: draw its outline at once (no stale page while it loads), then the case itself.
    if (!S.detail || S.detail.case_id !== S.caseId) { S.detail = null; S.detailLoading = true; render(); }
    await loadDetail(S.caseId);
    if (token !== S.routeToken) return;
  }
  if (S.page === "watchlist") {
    if (moved) Object.assign(WL, { q: "", status: "all", offset: 0 });
    await loadWatchlist();
    if (token !== S.routeToken) return;
  }
  S.detailLoading = false;
  render(moved && !!e);
  if (S.page === "watchlist") loadWatchlistRows();
  if (moved) window.scrollTo(0, 0);
}

async function refresh() {
  await Promise.all([loadCases(), loadHealth()]);
  if (S.page === "case" && S.caseId) await loadDetail(S.caseId);
  if (S.page === "watchlist") await loadWatchlist();
  render();
  if (S.page === "watchlist") loadWatchlistRows();
}

// ------------------------------------------------------------------ drawing

// Which control had the keyboard focus, so a redraw can put it back (a redraw replaces every element on the page).
function focusKey() {
  const a = document.activeElement;
  if (!a || !$("#simple").contains(a)) return null;
  if (a.id) return `#${CSS.escape(a.id)}`;
  if (a.dataset.act) return `[data-act="${a.dataset.act}"]`;
  const href = a.getAttribute("href");
  return href ? `#simple a[href="${CSS.escape(href)}"]` : null;
}

// moved: a new page, so the keyboard focus goes to its heading (a screen reader then reads where it is).
function render(moved = false) {
  if (document.body.dataset.view !== "simple") return;
  const nav = S.page === "case" ? "cases" : S.page;
  document.querySelectorAll(".gnav a").forEach((a) => a.setAttribute("aria-current", a.dataset.page === nav ? "page" : "false"));
  const root = $("#simple");
  const hadFocus = root.contains(document.activeElement);
  const key = moved ? null : focusKey();
  if (!S.loaded) root.innerHTML = loadingHtml(S.page === "case");
  else if (S.offline) {
    root.innerHTML = `<div class="gwrap"><h1 class="gh1" tabindex="-1">Can't reach Chimera</h1>
      <p class="gsub">Start the console server on this computer (<code>python -m chimera.api</code>), then try again.</p>
      <div><button class="gbtn" data-act="refresh">Try again</button></div></div>`;
  } else {
    root.innerHTML = S.page === "case" ? caseHtml() : S.page === "interviews" ? interviewsHtml() : S.page === "reports" ? reportsHtml()
      : S.page === "watchlist" ? watchlistHtml() : casesHtml();
  }
  root.setAttribute("aria-busy", String(!S.loaded || S.detailLoading));
  if (S.page === "case" && S.tab === "interview" && S.detail) { wireInterview(); startLive(); S.liveFramesKey = null; loadLiveFrames(); }
  if (S.page === "watchlist") wireWatchlist();
  const back = key && $(key);
  if (back && !back.disabled) back.focus({ preventScroll: true });
  else if ((moved || hadFocus) && !S.detailLoading && $("#simple .gh1")) $("#simple .gh1").focus({ preventScroll: true });
}

// The page's outline while the server answers: the same blocks as the real page, so nothing jumps when it arrives.
function loadingHtml(isCase) {
  const bar = (w, h, cls = "") => `<span class="gskel ${cls}" style="width:${w};height:${h}px"></span>`;
  if (isCase) {
    return `<div class="gwrap"><div><a class="geyebrow" href="#/cases">Cases</a>
      ${bar("min(420px, 80%)", 56)}<p class="gsub small">${bar("min(360px, 70%)", 22)}</p></div>
      <section class="gverdict gcard gload" aria-label="Loading the case"><div class="gverdict-main">${bar("min(300px, 70%)", 56)}
        ${bar("min(460px, 90%)", 26)}${bar("min(380px, 80%)", 26)}</div><div class="gdial none"><div class="gdial-in"></div></div></section>
      <p class="gnote" role="status">Loading the case…</p></div>`;
  }
  const title = { interviews: "Interviews", reports: "Reports", watchlist: "Watchlist" }[S.page] || "Cases";
  const tile = `<div class="gtile gcard gload">${bar("90px", 14)}<span>${bar("70%", 26)}${bar("85%", 16, "gskel-gap")}</span></div>`;
  return `<div class="gwrap"><div class="ghead-row"><div><h1 class="gh1">${title}</h1><p class="gsub" role="status">Loading…</p></div></div>
    <div class="gtiles">${tile}${tile}${tile}</div></div>`;
}

const bandOf = (c) => bandKey(c && c.band);
const sortByRisk = (a, b) => (BAND_RANK[a.band] ?? 9) - (BAND_RANK[b.band] ?? 9) || (b.score ?? -1) - (a.score ?? -1) || a.case_id.localeCompare(b.case_id);

function rowHtml(key, label, items, hrefFor) {
  if (!items.length) return "";
  return `<div class="grow gcard"><span class="grow-h ${key}"><i aria-hidden="true"></i>${esc(label)}</span>
    <div class="gpills">${items.map((c) => `<a class="gpill" href="${hrefFor(c)}">${esc(c.name || c.case_id)}</a>`).join("")}</div></div>`;
}

function casesHtml() {
  const all = [...S.cases].sort(sortByRisk);
  const attention = all.filter((c) => c.band === "High" || c.band === "Review");
  const checked = all.filter((c) => c.band);
  const n = all.length, k = attention.length;
  const sub = !n ? "No applications yet. Add one with New case."
    : `${count(n, "application", "applications")}. ${k ? `${k} need${k === 1 ? "s" : ""} attention.` : checked.length ? "None need attention." : "None checked yet."}`;
  const tiles = attention.map((c) => {
    const key = bandOf(c);
    // A long name stops at three lines on the tile; the link still carries the whole name for screen readers.
    return `<a class="gtile gcard" href="#/case/${encodeURIComponent(c.case_id)}" title="${esc(c.name || c.case_id)}">
      <span class="gband ${key}"><i aria-hidden="true"></i>${BAND_WORD[key]}</span>
      <span class="gtile-row"><span class="gtile-main"><span class="gtile-name">${esc(c.name || c.case_id)}</span>
        <span class="gtile-why">${esc(whyFor(c))}</span></span>
        <span class="gtile-score"><span class="gsr">Score </span>${esc(c.score)}<span class="gsr"> of 10</span></span></span></a>`;
  }).join("");
  const href = (c) => `#/case/${encodeURIComponent(c.case_id)}`;
  const empty = !n ? `<div class="grow gcard gempty"><span class="grow-h none"><i aria-hidden="true"></i>No cases</span>
    <p class="gnote">A case is one application: the applicant's details, their resume and, later, the interview recording.</p></div>` : "";
  return `<div class="gwrap">
    <div class="ghead-row"><div><h1 class="gh1" tabindex="-1">Cases</h1><p class="gsub">${esc(sub)}</p></div>
      <div class="gactions"><button class="gbtn" data-act="new">New case</button></div></div>
    ${tiles ? `<div class="gtiles">${tiles}</div>` : ""}
    <div class="grows">${empty}
      ${rowHtml("low", BAND_WORD.low, all.filter((c) => c.band === "Low"), href)}
      ${rowHtml("none", BAND_WORD.none, all.filter((c) => !c.band), href)}
    </div></div>`;
}

function interviewsHtml() {
  const all = [...S.cases].sort(sortByRisk);
  const on = all.filter((c) => c.has_recording);
  const href = (c) => `#/case/${encodeURIComponent(c.case_id)}/interview`;
  return `<div class="gwrap">
    <div><h1 class="gh1" tabindex="-1">Interviews</h1><p class="gsub">${on.length ? `${count(on.length, "recording", "recordings")} on file.` : "No recordings yet."} Record from a case's Interview tab.</p></div>
    <div class="grows">${rowHtml("low", "Recording on file", on, href)}${rowHtml("none", "No recording", all.filter((c) => !c.has_recording), href)}</div></div>`;
}

function reportsHtml() {
  const all = [...S.cases].sort(sortByRisk);
  const ready = all.filter((c) => c.has_report && !c.report_stale);
  const stale = all.filter((c) => c.has_report && c.report_stale);    // the evidence changed after it was written
  const href = (c) => `#/case/${encodeURIComponent(c.case_id)}`;
  const sub = `${ready.length ? `${count(ready.length, "report", "reports")} ready.` : stale.length ? "" : "No reports yet."}`
    + `${stale.length ? ` ${count(stale.length, "report is", "reports are")} out of date: recheck ${stale.length === 1 ? "that case" : "those cases"}.` : ""}`;
  return `<div class="gwrap">
    <div><h1 class="gh1" tabindex="-1">Reports</h1><p class="gsub">${sub.trim()} Open a case to download its report.</p></div>
    <div class="grows">${rowHtml("low", "Report ready", ready, href)}${rowHtml("review", "Out of date", stale, href)}${rowHtml("none", "No report yet", all.filter((c) => !c.has_report), href)}</div></div>`;
}

function fmtDate(iso) {
  const m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return iso || "on an unknown date";
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

function subtitle(d) {
  const loc = d.location || {};
  const where = [loc.city, loc.state].filter(Boolean).join(", ") || loc.country || "";
  return `Submitted ${fmtDate(d.submitted_at)}${where ? ` · says they are in ${where}` : ""}`;
}

const CHEVRON = `<svg width="10" height="14" viewBox="0 0 10 14" aria-hidden="true"><path d="M2 2l5 5-5 5"></path></svg>`;

function caseHtml() {
  const d = S.detail;
  if (!d && S.detailLoading) return loadingHtml(true);
  if (!d) {
    const err = S.detailError || {};
    return err.status === 404 || err.status === 400
      ? `<div class="gwrap"><div><a class="geyebrow" href="#/cases">Cases</a><h1 class="gh1" tabindex="-1">Case not found</h1>
          <p class="gsub small">There is no case called ${esc(S.caseId)} on this computer. It may have been deleted.</p></div></div>`
      : `<div class="gwrap"><div><a class="geyebrow" href="#/cases">Cases</a><h1 class="gh1" tabindex="-1">Couldn't open this case</h1>
          <p class="gsub small">${esc(err.message || "The console did not answer.")}</p></div>
          <div><button class="gbtn" data-act="refresh">Try again</button></div></div>`;
  }
  const run = S.runs[d.case_id];
  const running = run && run.status === "running";
  const failed = run && run.status === "failed";       // the card's Retry is then the one check button
  const id = encodeURIComponent(d.case_id);
  // Download report gives the PDF (Oct 25): the report, the checks and the most suspicious moments as pictures.
  const actions = d.evidence && !running
    ? `${failed ? "" : `<button class="gbtn" data-act="check">Recheck</button>`}${d.report ? `<a class="gtextbtn" href="/api/cases/${id}/report.pdf" download>Download report${CHEVRON}</a>` : ""}`
    : "";
  return `<div class="gwrap">
    <div class="ghead-row"><div><a class="geyebrow" href="#/cases">Cases</a><h1 class="gh1" tabindex="-1">${esc(d.name || d.case_id)}</h1>
      <p class="gsub small">${esc(subtitle(d))}</p></div><div class="gactions">${actions}</div></div>
    <nav class="gtabs" aria-label="Case">
      <a href="#/case/${id}" aria-current="${S.tab === "summary" ? "page" : "false"}">Summary</a>
      <a href="#/case/${id}/interview" aria-current="${S.tab === "interview" ? "page" : "false"}">Interview</a></nav>
    ${S.tab === "interview" ? interviewHtml(d) : summaryHtml(d, run)}</div>`;
}

const STEP_WORD = { done: "Done", active: "In progress", skip: "No recording", wait: "Waiting" };

function verdictHtml(d, run) {
  const ev = d.evidence;
  const running = run && run.status === "running";
  const failed = run && run.status === "failed";
  const key = running || !ev ? "none" : bandKey(ev.band);
  const word = running ? "Checking" : ev ? `${BAND_WORD[key]}.` : "Not checked";
  const head = running ? "Checking this candidate. You can leave this page; the result appears here when it is ready." : headlineFor(ev);
  const score = !running && ev ? ev.score : null;
  const steps = running ? `<ol class="gsteps">${run.steps.map((s) => `<li class="${s.state}"><i class="${s.state === "active" ? "gpulse" : ""}" aria-hidden="true"></i>
      <span class="gstep-l">${esc(s.label)}</span><span class="gstep-w">${STEP_WORD[s.state]}</span></li>`).join("")}</ol>` : "";
  // A failed recheck leaves the last finished result on screen, and says so.
  const error = failed ? `<p class="gerror">The check stopped: ${esc(run.error)}${ev ? " The result shown is from the last check that finished." : ""}</p>
    <div><button class="gbtn" data-act="check">Retry</button></div>` : "";
  const start = !ev && !running && !failed ? `<div><button class="gbtn" data-act="check">Check this candidate</button></div>` : "";
  return `<section class="gverdict gcard" aria-label="Verdict">
    <div class="gverdict-main"><div class="gword ${key}">${esc(word)}</div><p class="gheadline">${esc(head)}</p>
      ${start}${steps}${error}<p class="gsmall">Decision support only. A person makes the final call.</p></div>
    <div class="gdial ${key}" style="--deg:${score === null ? 0 : score * 36}deg" role="img" aria-label="${score === null ? "No score yet" : `Score ${score} of 10`}">
      <div class="gdial-in"><span class="gdial-n">${score === null ? "–" : esc(score)}</span><span class="gdial-of">of 10</span></div></div></section>`;
}

// What the downloadable report is and whether code checked it. (In the design this slot held model-written
// questions for the candidate; those were removed on Oct 18 because the candidate never gets any signal.)
function checkSummary(text, kind) {
  const r = checkResult(text);
  if (!r) return null;
  const extra = kind === "evidence" && r.quotes
    ? ` · <span class="gnowrap">${r.quotes.verified} of ${r.quotes.cited} quotes verified</span>` : "";
  return r.problems
    ? `<span class="bad">${count(r.problems, "problem", "problems")}</span>${extra}. The Advanced view lists them.`
    : `<span class="ok">No problems</span>${extra}.`;
}

function reportHtml(d) {
  if (!d.report) {
    // Scored but no written report yet (the analysts never ran on this case, or their run failed).
    return d.evidence ? `<section class="greport gcard" aria-label="Report"><div class="greport-h"><b>Report</b></div>
      <div class="greport-b"><p>No written report yet. Recheck runs the analysts to write one.</p></div></section>` : "";
  }
  const meta = d.flow_meta || {};
  const mock = meta.mode === "mock";
  // The mock flow's text must never pass for the agents' (UI-HANDOFF, "The mock flow"): it gets the amber banner.
  const who = mock ? `<p class="gmock">Written by the mock flow: code wrote it from the evidence lines, and the agents did not run.</p>`
    : `<p>Written by the LangFlow agents${meta.ran_at ? ` on ${esc(String(meta.ran_at).slice(0, 10))}` : ""}.</p>`;
  // Out of date (Oct 19): the evidence changed after the report was written, so its checks no longer apply.
  const stale = d.report_stale ? `<p><span class="bad">Out of date.</span> ${esc(staleWhy(d.report_stale_why))} `
    + "Its checks ran against the old evidence. Recheck to bring it up to date.</p>" : "";
  const ev = stale ? null : checkSummary(d.evidence_check, "evidence"), bc = stale ? null : checkSummary(d.bundle_check, "bundle");
  const files = `<p><a class="glink" href="/api/cases/${encodeURIComponent(d.case_id)}/report.pdf" download>Download the PDF</a>
    <span class="ghint"> or the </span><button class="glink" data-act="download">Markdown text</button></p>`;
  return `<section class="greport gcard" aria-label="Report">
    <div class="greport-h"><b>Report</b><span class="gtag">${mock ? "WRITTEN BY CODE (MOCK)" : "WRITTEN BY MODEL"}</span></div>
    <div class="greport-b">${stale}${who}${ev ? `<p>Evidence Check: ${ev}</p>` : ""}${bc ? `<p>Bundle Check: ${bc}</p>` : ""}${files}</div></section>`;
}

// ------------------------------------------------------------------ the most suspicious moments as pictures (Oct 25)

const fmtScore = (s) => (typeof s === "number" ? s.toFixed(2) : "–");

// One row of pictures: the face crop the models scored, linking to the whole frame it came from.
function momentsHtml(base, moments, live) {
  return `<div class="gframes-row">${moments.map((m) => `<figure class="gframe">
      <a href="${base}${encodeURIComponent(m.frame || m.face)}" target="_blank" rel="noopener" title="Open the whole frame">
        <img src="${base}${encodeURIComponent(m.face || m.frame)}" width="128" height="128" loading="lazy"
          alt="The face at ${esc(m.clock)}${live ? " into the call" : ""}, scored ${esc(fmtScore(m.score))}"></a>
      <figcaption><b>${esc(m.clock)}</b><span>${esc(fmtScore(m.score))}</span></figcaption></figure>`).join("")}</div>`;
}

function framesHtml(d) {
  const f = d.frames || {};
  const base = (kind) => `/api/cases/${encodeURIComponent(d.case_id)}/frames/${kind}/`;
  const rec = f.recording && (f.recording.moments || []).length ? f.recording : null;
  const live = f.live && (f.live.moments || []).length ? f.live : null;
  if (!rec && !live) return "";
  return `<section class="greport gframes gcard" aria-label="Most suspicious moments">
    <div class="greport-h"><b>Most suspicious moments</b><span class="gtag">PICTURES</span></div>
    <div class="greport-b"><p class="ghint">The faces the face check scored highest, at least two seconds apart. Select one to see the whole frame.
      They show what the score reacted to; a person decides.</p>
      ${rec ? `<div class="gframes-set"><h3>Interview recording</h3>${momentsHtml(base("recording"), rec.moments, false)}</div>` : ""}
      ${live ? `<div class="gframes-set"><h3>Live face check${live.attached_at ? `, saved ${esc(fmtDate(live.attached_at))}` : ""}</h3>${momentsHtml(base("live"), live.moments, true)}</div>` : ""}
    </div></section>`;
}

// The live check's pictures on the Interview tab: the newest session's five, rewritten as the call goes, which a
// person can save to this case (the live check does not know which case a call belongs to).
async function loadLiveFrames() {
  if (!$("#g-live-frames") || !S.detail) return;
  let r;
  try { r = await api("/api/live/frames"); } catch { return; }
  // The page may have been drawn again while the answer was on its way: fill the panel that is on screen now.
  const box = $("#g-live-frames");
  if (!box || !S.detail) return;
  const m = r.manifest, saved = S.detail.frames && S.detail.frames.live;
  // Redraw when the moments themselves change (two changes can share one second of 'updated').
  const key = JSON.stringify([r.log, ((m && m.moments) || []).map((x) => [x.t, x.score]), saved && saved.attached_at]);
  if (key === S.liveFramesKey) return;
  S.liveFramesKey = key;
  const moments = (m && m.moments) || [];
  const savedLine = saved ? `<p class="ghint">Saved to this case: ${esc(count((saved.moments || []).length, "picture", "pictures"))} from ${esc(saved.from_log || "a live session")}.
    <button class="glink" data-act="live-remove">Remove them</button></p>` : "";
  const started = m && m.created ? new Date(m.created).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
  box.innerHTML = moments.length
    ? `<h3>Most suspicious moments</h3>${momentsHtml(`/api/live/frames/${encodeURIComponent(r.log)}/`, moments, true)}
       <p class="ghint">The five faces the live check scored highest${started ? ` in the session that started ${esc(started)}` : ""} (log ${esc(r.log)}).</p>
       <div class="gbtns"><button class="gbtn ghost" data-act="live-save" data-log="${esc(r.log)}">${saved ? "Replace the saved pictures" : "Save to this case"}</button></div>
       <p class="ghint">Saved pictures go in this case's PDF report.</p>${savedLine}`
    : savedLine;
}

async function saveLiveFrames(log) {
  const d = S.detail;
  try {
    const m = await api(`/api/cases/${encodeURIComponent(d.case_id)}/live-frames`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ log }) });
    toast(`Saved ${count((m.moments || []).length, "picture", "pictures")} to this case. They are in its PDF report.`);
  } catch (e) { toast(`The pictures weren't saved: ${e.message}`, true); }
  await loadDetail(d.case_id);
  S.liveFramesKey = null;
  loadLiveFrames();
}

async function removeLiveFrames() {
  const d = S.detail;
  try { await api(`/api/cases/${encodeURIComponent(d.case_id)}/live-frames`, { method: "DELETE" }); toast("Removed the live check pictures from this case."); }
  catch (e) { toast(e.message, true); }
  await loadDetail(d.case_id);
  S.liveFramesKey = null;
  loadLiveFrames();
}

function summaryHtml(d, run) {
  const running = run && run.status === "running";
  const reasons = d.evidence && !running ? reasonsFor(d.evidence) : [];
  return `${verdictHtml(d, run)}
    ${reasons.length ? `<section class="greasons${reasons.length === 4 ? " two-by-two" : ""}" aria-label="Reasons">${reasons.map((r) => `<article class="greason gcard">
      <span class="glabel ${esc(r.key)}"><i aria-hidden="true"></i>${esc(r.label)}</span><p>${esc(r.text)}</p></article>`).join("")}</section>` : ""}
    ${running ? "" : framesHtml(d)}
    ${running ? "" : reportHtml(d)}
    <p class="gadv">Evidence lines, analyst notes and checks are in <button class="glink" data-act="advanced">Advanced view</button>.</p>`;
}

// ------------------------------------------------------------------ the check: collect evidence, then the analysts

async function waitJob(id) {
  for (;;) {
    const job = await api(`/api/jobs/${id}`);
    if (job.status !== "running") return job;
    await sleep(1000);
  }
}

// Start a job and return its id. The server runs one job at a time and answers 409 with the one that is running.
// follow: a kind of job that does our work too. Another Recheck already collecting evidence ("run") covers the whole
// batch, so this check follows that job; any other job is waited out, then ours starts.
async function startJob(path, follow = null) {
  try { return (await api(path, { method: "POST" })).id; }
  catch (e) {
    const running = e.status === 409 && e.body && e.body.running;
    if (!running) throw e;
    if (follow && running.kind === follow) return running.id;
    await waitJob(running.id);
    return (await api(path, { method: "POST" })).id;
  }
}

// The last non-empty line of a failed job's log, so the card says what went wrong.
function lastLine(job) {
  const line = ((job && job.log) || []).map((l) => String(l).trim()).filter(Boolean).pop() || "no log";
  return line.length > 180 ? line.slice(0, 177) + "…" : line;
}

async function runCheck(caseId) {
  if (S.runs[caseId] && S.runs[caseId].status === "running") return;
  const summary = S.cases.find((c) => c.case_id === caseId) || S.detail || {};
  const run = {
    status: "running", error: null, steps: [
      { label: "Resume", state: "active" }, { label: "Application & OSINT", state: "active" },
      { label: "Interview recording", state: summary.has_recording ? "active" : "skip" },
      { label: "Written summary", state: "wait" }],
  };
  S.runs[caseId] = run;
  render();
  try {
    // Evidence is collected for every case in one batch, so template reuse can compare resumes across the batch.
    let job = await waitJob(await startJob("/api/run", "run"));
    if (job.status !== "done") throw new Error(`collecting the evidence failed (${lastLine(job)}).`);
    run.steps.forEach((s) => { if (s.state === "active") s.state = "done"; });
    run.steps[3].state = "active";
    if (S.page === "case" && S.caseId === caseId) render();
    job = await waitJob(await startJob(`/api/cases/${encodeURIComponent(caseId)}/analyze`));   // another case's analysis is not ours
    if (job.status !== "done") throw new Error(`writing the summary failed (${lastLine(job)}).`);
    delete S.runs[caseId];
    toast(job.result && job.result.mode === "mock" ? "Check finished. The report was written by the mock flow." : "Check finished.");
  } catch (e) {
    S.runs[caseId] = { ...run, status: "failed", error: e instanceof TypeError ? "the console server did not answer." : e.message };
  }
  await loadCases();
  if (S.page === "case" && S.caseId === caseId) await loadDetail(caseId);
  render();
  loadHealth();
}

function downloadReport() {
  const d = S.detail;
  if (!d || !d.report) return;
  // A report that is out of date says so in the file too, since the file travels without this page.
  // So does a mock-flow report: the note goes at the top, where the reader starts.
  const note = (d.flow_meta && d.flow_meta.mode === "mock"
    ? "> Mock flow: code wrote this report from the evidence lines; the LangFlow agents did not run.\n\n" : "")
    + (d.report_stale ? `> Out of date: ${staleWhy(d.report_stale_why)} Recheck the case before relying on this report.\n\n` : "");
  const url = URL.createObjectURL(new Blob([note + d.report], { type: "text/markdown;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `${d.case_id}_report.md` });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ------------------------------------------------------------------ interview: recording and the live face check

const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function interviewHtml(d) {
  const recording = S.recorder && S.recCase === d.case_id;
  const iv = (d.application && d.application.interview) || {};
  const file = `/api/cases/${encodeURIComponent(d.case_id)}/files/${encodeURIComponent(iv.recording || "interview.webm")}`;
  const strip = recording && S.recStopping ? `<div class="gstrip" id="g-strip"><i class="gpulse" aria-hidden="true"></i><b>Saving the recording…</b></div>`
    : recording ? `<div class="gstrip rec" id="g-strip"><i class="gpulse" aria-hidden="true"></i><b>Recording</b>
        <span class="gtimer"><span id="g-timer">${mmss((Date.now() - S.recStart) / 1000)}</span><span class="gchunks" id="g-chunks">${recChunks()}</span></span></div>`
    : d.has_recording ? `<div class="gstrip saved" id="g-strip"><i aria-hidden="true"></i><b>Saved. The recording is on file.</b></div>`
    : `<div class="gstrip" id="g-strip"><i aria-hidden="true"></i><b>Not recording</b></div>`;
  return `<div class="ginterview">
    <section class="gpanel gcard" aria-label="Recording"><h2>Recording</h2>
      <label class="gcheck"><input type="checkbox" id="g-consent" ${recording ? "checked disabled" : ""}> The candidate agreed to be recorded</label>
      ${recording ? "" : `<p class="ghint" id="g-consent-hint">Tick this first: it unlocks recording and adding a recording file.</p>`}
      ${strip}
      <div class="gbtns">${recording ? `<button class="gbtn" id="g-stop" ${S.recStopping ? "disabled" : ""}>Stop and save</button>`
        : `<button class="gbtn" id="g-start" disabled>Record meeting tab</button>`}</div>
      <p class="ghint">When the browser asks, choose the meeting tab and tick Share tab audio. Nothing is asked of the candidate beyond camera on.</p>
      ${recording ? "" : `<div class="gupload">
        <p class="ghint">Recorded in Zoom instead? Add the video file and, if Zoom saved one, the candidate's own audio track (in the recording's Audio Record folder).</p>
        <label class="gfile">Video <input type="file" id="g-up-video" accept=".mp4,.mkv,.webm,.mov,.m4v" disabled></label>
        <label class="gfile">Candidate's audio, optional <input type="file" id="g-up-audio" accept=".m4a,.wav,.mp3,.opus,.ogg,.flac,.aac" disabled></label>
        <div class="gbtns"><button class="gbtn" id="g-up-send" disabled>Add recording</button><span class="ghint" id="g-up-status" role="status"></span></div></div>`}
      ${d.has_recording && !recording ? `<p class="ghint">A recording is on file: <a href="${file}" target="_blank" rel="noopener">play it</a>${iv.audio ? ", with the candidate's own audio track" : ""}. Recheck scores it with the face-swap and voice-clone checks.</p>` : ""}
      ${iv.camera_refused ? `<p class="ghint">Noted in the case: the candidate kept the camera off or said it was broken.</p>` : ""}</section>
    <section class="gpanel gcard" aria-label="Live face check"><h2>Live face check</h2>
      <span class="gread wait" id="g-live-word" role="status">Waiting</span>
      <div class="gmeter" id="g-meter" role="img" aria-label="No reading yet"><b id="g-live-cut" hidden></b><i id="g-live-mark" hidden></i></div>
      <div class="gmeter-l" aria-hidden="true"><span>Looks real</span><span>Likely fake</span></div>
      <p class="gsay" id="g-live-say"></p>
      <p class="ghint" id="g-live-file"></p>
      <div id="g-live-again" hidden><button class="gbtn ghost" data-act="live-again">Follow the live check again</button></div>
      <div class="glive-frames" id="g-live-frames"></div></section></div>`;
}

const recChunks = () => (S.recChunks ? `${S.recChunks} ${S.recChunks === 1 ? "part" : "parts"} saved` : "");

// POST a meeting recording's files with progress; resolves with the case's interview settings.
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

function wireInterview() {
  const d = S.detail;
  const consent = $("#g-consent"), start = $("#g-start"), stop = $("#g-stop");
  const upVideo = $("#g-up-video"), upAudio = $("#g-up-audio"), upSend = $("#g-up-send"), upStatus = $("#g-up-status");
  const upReady = () => { if (upSend) upSend.disabled = !(consent && consent.checked) || !(upVideo.files.length || upAudio.files.length); };
  // Every capture control waits for the consent box (the handoff's Interview card), the file pickers included.
  if (consent && start) consent.addEventListener("change", () => {
    start.disabled = !consent.checked;
    [upVideo, upAudio].forEach((el) => { if (el) el.disabled = !consent.checked; });
    $("#g-consent-hint").hidden = consent.checked;
  });
  if (upSend) {
    [consent, upVideo, upAudio].forEach((el) => el.addEventListener("change", upReady));
    upSend.addEventListener("click", async () => {
      upSend.disabled = true;
      try {
        await uploadRecording(d.case_id, upVideo.files[0], upAudio.files[0], (pct) => { upStatus.textContent = `Uploading, ${pct}%`; });
        toast("Recording added. Recheck to score it.");
        await loadCases();
        if (S.caseId === d.case_id) await loadDetail(d.case_id);
        render();
      } catch (e) { upStatus.textContent = ""; toast(e.message, true); upReady(); }
    });
  }
  if (start) start.addEventListener("click", () => startRecording(d.case_id));
  if (stop) stop.addEventListener("click", () => {
    if (S.recorder && S.recorder.state !== "inactive") S.recorder.stop();
    S.recStopping = true;                            // the last parts are still uploading; onstop redraws when done
    render();
    const strip = $("#g-strip");                     // the (now disabled) button can't keep the keyboard focus
    if (strip) { strip.tabIndex = -1; strip.focus({ preventScroll: true }); }
  });
  updateLive();
}

async function startRecording(caseId) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { toast("Recording a meeting tab needs Chrome or Edge on this computer.", true); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30 }, audio: true }); }
  catch (e) { toast("Recording cancelled or blocked: " + e.message, true); return; }
  const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  let seq = 0, chain = Promise.resolve();
  rec.ondataavailable = (e) => {
    if (!e.data.size) return;
    const n = seq++;
    chain = chain.then(() => fetch(`/api/cases/${encodeURIComponent(caseId)}/recording?seq=${n}`, { method: "POST", body: e.data }))
      .then((resp) => {
        if (!resp.ok) throw new Error(`the console answered ${resp.status}`);
        S.recChunks = n + 1;
        const c = $("#g-chunks");
        if (c) c.textContent = recChunks();
      })
      .catch((err) => toast("Saving part of the recording failed: " + err.message, true));
  };
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(S.recTimer);
    await chain;
    try {
      await api(`/api/cases/${encodeURIComponent(caseId)}/interview`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recording_saved: true, consent: true }) });   // the Start button needs the consent box
      toast("Recording saved to the case. Recheck to score it.");
    } catch (e) { toast("The recording was saved, but the case wasn't updated: " + e.message, true); }
    S.recorder = null; S.recCase = null; S.recStopping = false; S.recChunks = 0;
    await loadCases();
    if (S.caseId === caseId) await loadDetail(caseId);
    render();
  };
  stream.getVideoTracks()[0].addEventListener("ended", () => { if (rec.state !== "inactive") rec.stop(); });
  S.recorder = rec; S.recCase = caseId; S.recStart = Date.now(); S.recChunks = 0; S.recStopping = false;
  rec.start(2000);                                   // a 2-second chunk at a time, appended on the server
  S.recTimer = setInterval(() => { const t = $("#g-timer"); if (t) t.textContent = mmss((Date.now() - S.recStart) / 1000); }, 1000);
  render();
}

// The live meter follows scripts/live_check.py's newest score log. Its wording is in plain.js; the cut-off is whatever
// the newest row says, so the meter shows no split until a row arrives. The session's pictures (its five most
// suspicious moments, Oct 25) are fetched beside it every few seconds by loadLiveFrames.
const pct = (x) => `${Math.min(100, Math.max(0, x * 100))}%`;
const STALE_MS = 5000;   // the live check writes two rows a second; five seconds without one means it has stopped

function updateLive() {
  const word = $("#g-live-word");
  if (!word) return;
  const stale = !!S.liveRow && (S.liveReplay || Date.now() - S.liveAt > STALE_MS);
  const r = liveReading(S.liveRow, S.liveClosed, stale);
  word.className = `gread ${r.key}`;
  // the reading is a live region: change its text only when the word changes, or screen readers repeat it every row
  if (word.textContent !== r.word) word.textContent = r.word;
  $("#g-live-say").textContent = r.say;
  $("#g-live-file").textContent = liveSource(S.liveFile, S.liveRow && S.liveRow.cutoff);
  $("#g-live-again").hidden = !S.liveClosed;
  const meter = $("#g-meter"), mark = $("#g-live-mark"), tick = $("#g-live-cut");
  const avg = S.liveRow && !stale ? parseFloat(S.liveRow.average) : NaN;      // no marker for an old reading
  const cut = S.liveRow ? parseFloat(S.liveRow.cutoff) : NaN;     // the live check writes its cut-off on every row
  meter.classList.toggle("known", Number.isFinite(cut));
  meter.classList.toggle("reading", Number.isFinite(avg));
  if (Number.isFinite(cut)) meter.style.setProperty("--cut", pct(cut));
  tick.hidden = !Number.isFinite(cut);
  mark.hidden = !Number.isFinite(avg);
  if (Number.isFinite(avg)) mark.style.left = pct(avg);
  meter.setAttribute("aria-label", Number.isFinite(avg) && Number.isFinite(cut)
    ? `Reading ${avg.toFixed(2)} against a cut-off of ${cut.toFixed(2)}` : "No reading yet");
}

function startLive() {
  if (S.live) return;
  S.liveClosed = false; S.liveRow = null; S.liveFile = "";
  const es = new EventSource("/api/live/events");
  S.live = es;
  // On connecting, the server sends the newest log's old rows in one burst, then new rows as live_check.py writes them
  // (two a second). Rows that arrive with the burst are history, so they never show as a reading of the call now.
  es.addEventListener("file", (e) => { S.liveFile = JSON.parse(e.data).file; S.liveRow = null; S.liveFileAt = Date.now(); updateLive(); });
  es.addEventListener("waiting", () => { if (S.liveRow || S.liveFile) { S.liveFile = ""; S.liveRow = null; updateLive(); } });   // no log yet
  es.onmessage = (e) => {
    S.liveRow = JSON.parse(e.data);
    S.liveAt = Date.now();
    S.liveReplay = S.liveAt - S.liveFileAt < 400;
    updateLive();
  };
  // A closed feed shows no reading at all (its last row would pass for the call now).
  es.onerror = () => { es.close(); S.live = null; S.liveClosed = true; S.liveRow = null; updateLive(); };
  clearInterval(S.liveTimer);
  S.liveTimer = setInterval(updateLive, 1000);     // notices a log that has stopped growing
  clearInterval(S.liveFramesTimer);
  S.liveFramesTimer = setInterval(loadLiveFrames, 4000);
  updateLive();
}

// Leaving the Interview tab: close the feed and forget its state, so coming back starts clean.
function stopLive() {
  if (S.live) S.live.close();
  clearInterval(S.liveTimer);
  clearInterval(S.liveFramesTimer);
  Object.assign(S, { live: null, liveTimer: null, liveRow: null, liveFile: "", liveClosed: false, liveReplay: false,
    liveFramesTimer: null, liveFramesKey: null });
}

// ------------------------------------------------------------------ watchlist admin (#/watchlist, Oct 25)
// The threat-actor list every application is matched against (chimera/watchlist_admin.py). The first change makes an
// editable copy, so the configured file is never changed; rows are retired, never deleted, because reports quote
// their row IDs; every change is logged with its reason.

const WL = { summary: null, error: null, page: null, rowsError: null, q: "", status: "all", offset: 0, limit: 50,
  audit: [], dlg: null, typing: null, rechecking: false };
const ACTION_WORD = { copy: "Editable copy made", add: "Added", edit: "Edited", retire: "Retired", restore: "Restored",
  import: "Imported", "use original": "Back to the original file" };
const attrKey = (a) => ({ High: "high", Medium: "review", Low: "low" }[a] || "none");
const cellHtml = (s) => (s ? esc(s).replace(/\n/g, "<br>") : "–");      // escaped first, then line breaks
const jsonPost = (body, method = "POST") => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function fmtWhen(iso) {
  const m = String(iso || "").match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  return m ? `${fmtDate(m[1])}, ${m[2]}:${m[3]}` : (iso || "");
}

async function loadWatchlist() {
  try {
    const [summary, audit] = await Promise.all([api("/api/watchlist"), api("/api/watchlist/audit?limit=15")]);
    Object.assign(WL, { summary, audit: audit.entries, error: null });
  } catch (e) {
    Object.assign(WL, { summary: null, error: e instanceof TypeError ? "The console server did not answer." : e.message });
  }
}

async function loadWatchlistRows() {
  if (!WL.summary) return;
  const p = new URLSearchParams({ q: WL.q, status: WL.status, offset: String(WL.offset), limit: String(WL.limit) });
  try { WL.page = await api(`/api/watchlist/rows?${p}`); WL.rowsError = null; }
  catch (e) { WL.page = null; WL.rowsError = e instanceof TypeError ? "The console server did not answer." : e.message; }
  // The last row of the last page left the filter (retired, say): show the page before instead of an empty one.
  if (WL.page && !WL.page.rows.length && WL.page.total && WL.offset) {
    WL.offset = Math.floor((WL.page.total - 1) / WL.limit) * WL.limit;
    return loadWatchlistRows();
  }
  const box = $("#gwl-table");
  if (!box) return;
  // Redrawing the table replaces its buttons: put the keyboard focus back on the same one, or on the table.
  const had = box.contains(document.activeElement) ? document.activeElement : null;
  const again = had && (had.dataset.row ? `[data-act="${had.dataset.act}"][data-row="${had.dataset.row}"]`
    : had.dataset.act ? `[data-act="${had.dataset.act}"]${had.dataset.dir ? `[data-dir="${had.dataset.dir}"]` : ""}` : null);
  box.innerHTML = watchlistTableHtml();
  if (had) {
    const found = again && box.querySelector(again);
    const dest = found && !found.disabled ? found : box;    // Next on the last page comes back disabled
    if (dest === box) box.setAttribute("tabindex", "-1");
    dest.focus({ preventScroll: true });
  }
}

function watchlistHtml() {
  const s = WL.summary;
  if (!s) {
    return `<div class="gwrap"><div><h1 class="gh1" tabindex="-1">Watchlist</h1>
      <p class="gsub small">${esc(WL.error || "Loading the watchlist…")}</p></div>
      ${WL.error ? `<div><button class="gbtn" data-act="refresh">Try again</button></div>` : ""}</div>`;
  }
  // Changed after evidence was last collected (going back to the original file counts): the cases still carry
  // matches from the list as it was.
  const behind = !!(s.last_change_at && s.evidence_collected_at && s.last_change_at > s.evidence_collected_at);
  const file = s.managed
    ? `Matching uses an editable copy of <b>${esc(s.source_name)}</b>, made ${esc(fmtWhen(s.copied_at))}. The original file is unchanged, every change is in the log below, and the list as it was before each change is kept as a backup.`
    : `Matching uses <b>${esc(s.source_name)}</b>. The first change makes an editable copy beside it, so the original file is never changed.`;
  const filters = [["all", "All"], ["active", "Active"], ["retired", "Retired"]].map(([k, label]) =>
    `<button type="button" data-act="wl-status" data-status="${k}" aria-pressed="${WL.status === k}">${label}</button>`).join("");
  return `<div class="gwrap">
    <div class="ghead-row"><div><span class="gtag gwl-tag">ADMIN</span><h1 class="gh1" tabindex="-1">Watchlist</h1>
      <p class="gsub">${esc(count(s.active_rows, "person", "people"))} in ${esc(count(s.rings, "ring", "rings"))}${s.retired ? `, ${esc(s.retired)} retired` : ""}. Every application is matched against this list.</p></div>
      <div class="gactions"><button class="gbtn" data-act="wl-add">Add person</button></div></div>
    ${behind ? `<section class="gwl-banner gcard" role="status"><p>The list changed after evidence was last collected, so the cases still show matches against the old list.</p>
      <button class="gbtn" data-act="wl-recheck" ${WL.rechecking ? "disabled" : ""}>${WL.rechecking ? "Collecting…" : "Collect evidence again"}</button></section>` : ""}
    <section class="gpanel gcard" aria-label="List file"><h2>List file</h2><p class="ghint">${file}</p>
      <p class="ghint">Chimera matches this list in code: emails, phones, profiles and IPs after normalizing, names by close spelling, and rings from shared identifiers. Rows are never deleted, because reports quote their row IDs; retire a row to stop it matching.</p>
      <div class="gbtns"><button class="gbtn ghost" data-act="wl-import">Import from a file</button>
        <a class="gbtn ghost" href="/api/watchlist/export" download>Export CSV</a>
        ${s.managed ? `<button class="gbtn ghost" data-act="wl-original">Use the original file</button>` : ""}</div></section>
    <section class="gwl-list gcard" aria-label="People on the watchlist">
      <div class="gwl-tools"><input type="search" id="gwl-q" class="gwl-search" value="${esc(WL.q)}" autocomplete="off"
          placeholder="Search names, emails, phones, rings, row IDs" aria-label="Search the watchlist">
        <div class="gtabs" role="group" aria-label="Show">${filters}</div></div>
      <div id="gwl-table">${watchlistTableHtml()}</div></section>
    <section class="gpanel gcard" aria-label="Change log"><h2>Change log</h2>${auditHtml()}</section></div>`;
}

function watchlistTableHtml() {
  if (WL.rowsError) return `<p class="gerror">${esc(WL.rowsError)}</p>`;
  const p = WL.page;
  if (!p) return `<p class="ghint">Loading rows…</p>`;
  if (!p.total) return `<p class="ghint">${WL.q ? "No row matches that search." : WL.status === "retired" ? "No retired rows." : "No rows."}</p>`;
  const rows = p.rows.map((r) => {
    const v = r.values, id = esc(r.row_id);
    return `<tr${r.retired ? ' class="retired"' : ""}><td class="gmono">${id}</td><td>${esc(v.Name || "–")}</td>
      <td>${v.Attribution ? `<span class="glabel ${attrKey(v.Attribution)}"><i aria-hidden="true"></i>${esc(v.Attribution)}</span>` : "–"}</td>
      <td class="gwl-id">${cellHtml(v.Email)}</td><td class="gwl-id">${cellHtml(v.Phone)}</td>
      <td class="gnowrap">${r.ring ? `${esc(r.ring)} <span class="ghint">(${esc(r.ring_size)})</span>` : "–"}</td>
      <td>${r.retired ? `<span class="gwl-retired">Retired</span>` : "Active"}</td>
      <td class="gwl-acts"><button class="glink" data-act="wl-edit" data-row="${id}">Edit<span class="gsr"> ${id}</span></button>
        <button class="glink" data-act="${r.retired ? "wl-restore" : "wl-retire"}" data-row="${id}">${r.retired ? "Restore" : "Retire"}<span class="gsr"> ${id}</span></button></td></tr>`;
  }).join("");
  const from = p.offset + 1, to = p.offset + p.rows.length;
  return `<div class="gwl-scroll"><table class="gtable"><thead><tr><th scope="col">Row</th><th scope="col">Name</th>
      <th scope="col">Attribution</th><th scope="col">Email</th><th scope="col">Phone</th><th scope="col">Ring</th>
      <th scope="col">Status</th><th scope="col"><span class="gsr">Actions</span></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="gwl-pager"><span class="ghint" role="status">${from}–${to} of ${p.total}</span>
      <button class="gbtn ghost" data-act="wl-page" data-dir="-1" ${p.offset === 0 ? "disabled" : ""}>Previous</button>
      <button class="gbtn ghost" data-act="wl-page" data-dir="1" ${to >= p.total ? "disabled" : ""}>Next</button></div>`;
}

function auditHtml() {
  if (!WL.audit.length) return `<p class="ghint">No changes yet.</p>`;
  return `<ol class="gwl-log">${WL.audit.map((e) => {
    const changes = Object.entries(e.changes || {}).map(([k, c]) => `${esc(k)}: ${esc(c.before || "–")} → ${esc(c.after || "–")}`).join("; ");
    return `<li><span class="gwl-when">${esc(fmtWhen(e.at))}</span> <b>${esc(ACTION_WORD[e.action] || e.action)}</b>${e.row ? ` <span class="gmono">${esc(e.row)}</span>` : ""}${e.note ? ` · ${esc(e.note)}` : ""}${changes ? `<div class="ghint">${changes}</div>` : ""}</li>`;
  }).join("")}</ol>`;
}

// The search box redraws only the table, so the box keeps the keyboard focus while typing.
function wireWatchlist() {
  const q = $("#gwl-q");
  if (!q) return;
  q.addEventListener("input", () => {
    clearTimeout(WL.typing);
    WL.typing = setTimeout(() => { WL.q = q.value; WL.offset = 0; loadWatchlistRows(); }, 250);
  });
}

async function refreshWatchlist() {
  await loadWatchlist();
  render();
  await loadWatchlistRows();
}

async function watchlistAction(what, el) {
  const row = el.dataset.row && WL.page ? WL.page.rows.find((r) => r.row_id === el.dataset.row) : null;
  if (what === "wl-status") {
    WL.status = el.dataset.status; WL.offset = 0;
    document.querySelectorAll('[data-act="wl-status"]').forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.status === WL.status)));
    loadWatchlistRows();
  } else if (what === "wl-page") {
    WL.offset = Math.max(0, WL.offset + Number(el.dataset.dir) * WL.limit);
    loadWatchlistRows();
  } else if (what === "wl-recheck") {
    WL.rechecking = true; render();
    try {
      const job = await waitJob(await startJob("/api/run", "run"));
      if (job.status === "done") toast("Evidence collected again: every case is now matched against this list. A case whose evidence changed shows its report as out of date until it is rechecked.");
      else toast(`Collecting evidence failed (${lastLine(job)}).`, true);
    } catch (e) { toast(e instanceof TypeError ? "The console server did not answer." : e.message, true); }
    WL.rechecking = false;
    await loadCases();
    await refreshWatchlist();
  } else if (what === "wl-cancel") $("#gwl-dlg").close();
  else if (what === "wl-add") openWatchlistDialog("add");
  else if (what === "wl-edit" && row) openWatchlistDialog("edit", row);
  else if (what === "wl-retire" && row) openWatchlistDialog("retire", row);
  else if (what === "wl-restore" && row) openWatchlistDialog("restore", row);
  else if (what === "wl-import") openWatchlistDialog("import");
  else if (what === "wl-original") openWatchlistDialog("original");
}

// A cell can hold several values on separate lines (chimera/normalize.py split_cell), so the fields are text areas: a
// one-line input would join the lines and the edit would save the joined text (Oct 26 review). An attribution the
// list spells another way stays as it is unless the admin picks one of the four.
function fieldHtml(col, value) {
  if (col === "Attribution") {
    const options = ["", "High", "Medium", "Low"];
    const own = value && !options.includes(value) ? `<option value="${esc(value)}" selected>${esc(value)} (as in the list)</option>` : "";
    return `<label class="gfield">Attribution<select name="Attribution">${own}${options.map((a) =>
      `<option value="${a}"${a === value ? " selected" : ""}>${a || "Not rated"}</option>`).join("")}</select></label>`;
  }
  const lines = Math.min(4, Math.max(1, String(value || "").split("\n").length));
  // The HTML parser drops one newline right after <textarea>: give it one, so a cell's own leading newline stays.
  return `<label class="gfield">${esc(col)}<textarea name="${esc(col)}" rows="${lines}" maxlength="500" autocomplete="off">\n${esc(value)}</textarea></label>`;
}

const sameText = (a) => String(a ?? "").replace(/\r\n?/g, "\n");   // a form sends a text area's lines as CRLF

const noteField = (label, required) => `<label class="gfield gwide">${label}<input name="__note" maxlength="500" autocomplete="off"${required ? " required" : ""}></label>`;

function openWatchlistDialog(kind, row = null) {
  const s = WL.summary, form = $("#gwl-form");
  if (!s) return;
  WL.dlg = { kind, row, preview: null };
  const foot = (label) => `<div class="gdlg-f"><p class="gdlg-err" id="gwl-err" role="alert"></p>
    <button type="button" class="gbtn ghost" data-act="wl-cancel">Cancel</button><button type="submit" class="gbtn" id="gwl-submit">${label}</button></div>`;
  if (kind === "add" || kind === "edit") {
    const v = (row && row.values) || {};
    // The form's fields first; editing also offers the sheet's other columns, so nothing in a row is out of reach.
    const cols = [...s.form_columns, ...(kind === "edit" ? s.columns.filter((c) => !s.form_columns.includes(c)) : [])];
    form.innerHTML = `<h2 id="gwl-dlg-title">${kind === "add" ? "Add a person" : `Edit ${esc(row.row_id)}`}</h2>
      <p class="gdlg-sub">${kind === "add" ? "The new row goes at the end of the list." : "Only the fields you change are saved."} Put several values in one field with a semicolon between them.</p>
      <div class="gdlg-b gmore">${cols.map((c) => fieldHtml(c, v[c] || "")).join("")}${noteField("Why (kept in the change log)", false)}</div>
      ${foot(kind === "add" ? "Add" : "Save")}`;
  } else if (kind === "retire" || kind === "restore") {
    form.innerHTML = `<h2 id="gwl-dlg-title">${kind === "retire" ? "Retire" : "Restore"} ${esc(row.row_id)}</h2>
      <p class="gdlg-sub">${esc(row.values.Name || row.row_id)}. ${kind === "retire"
        ? "A retired row stays in the list, so its row ID still means the same person, but it matches nothing."
        : "The row matches applications again."} It counts at the next evidence collection.</p>
      <div class="gdlg-b">${noteField("Why (required; kept in the change log)", true)}</div>${foot(kind === "retire" ? "Retire" : "Restore")}`;
  } else if (kind === "import") {
    form.innerHTML = `<h2 id="gwl-dlg-title">Import from a file</h2>
      <p class="gdlg-sub">A CSV or Excel file with an Email and a Phone column, like the list itself. Rows the list already holds (the same name and identifiers) are skipped; new rows go at the end.</p>
      <div class="gdlg-b"><label class="gfield">File<input type="file" name="file" accept=".csv,.xlsx,.xlsm,.xls"></label>
        <div id="gwl-preview"></div></div>${foot("Preview")}`;
  } else if (kind === "original") {
    form.innerHTML = `<h2 id="gwl-dlg-title">Use the original file</h2>
      <p class="gdlg-sub">Matching goes back to ${esc(s.source_name)}. The editable copy, with its ${esc(count(s.changes, "logged change", "logged changes"))}, moves to the backups folder; nothing is deleted.</p>
      <div class="gdlg-b">${noteField("Why (kept in the change log)", false)}</div>${foot("Use the original file")}`;
  }
  $("#gwl-dlg").showModal();
  const first = form.querySelector("input, select, textarea");
  if (first) first.focus();
}

function showImportPreview() {
  const box = $("#gwl-preview"), submit = $("#gwl-submit"), p = WL.dlg && WL.dlg.preview;
  if (!box || !submit) return;
  if (!p) { box.innerHTML = ""; submit.textContent = "Preview"; submit.disabled = false; return; }
  const extra = p.columns_added.length ? ` New columns: ${p.columns_added.map(esc).join(", ")}.` : "";
  box.innerHTML = `<p class="gwl-preview" role="status">${esc(count(p.rows_in_file, "row", "rows"))} in ${esc(p.file)}: <b>${esc(count(p.new, "new row", "new rows"))}</b> to add,
    ${esc(count(p.duplicates, "duplicate", "duplicates"))} skipped${p.problem_count ? `, ${esc(count(p.problem_count, "row", "rows"))} skipped for a problem` : ""}.${extra}</p>
    ${p.problems.length ? `<ul class="ghint">${p.problems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}`;
  submit.textContent = p.new ? `Add ${count(p.new, "row", "rows")}` : "Nothing to add";
  submit.disabled = !p.new;
}

async function submitWatchlistDialog(e) {
  e.preventDefault();
  const dlg = WL.dlg;
  if (!dlg) return;
  const form = $("#gwl-form"), err = $("#gwl-err"), submit = $("#gwl-submit");
  const fd = new FormData(form);
  const note = String(fd.get("__note") || "").trim();
  err.textContent = "";
  submit.disabled = true;
  try {
    if (dlg.kind === "add" || dlg.kind === "edit") {
      const values = {};
      for (const [k, v] of fd.entries()) {
        if (k === "__note") continue;
        const text = sameText(v);
        if (dlg.kind === "add" ? text.trim() : text !== sameText(dlg.row.values[k])) values[k] = text;
      }
      if (!Object.keys(values).length) { err.textContent = dlg.kind === "add" ? "Fill in a name or an identifier." : "Nothing changed."; return; }
      const r = dlg.kind === "add"
        ? await api("/api/watchlist/rows", jsonPost({ values, note }))
        : await api(`/api/watchlist/rows/${encodeURIComponent(dlg.row.row_id)}`, jsonPost({ values, note }, "PATCH"));
      toast(`${dlg.kind === "add" ? "Added" : "Saved"} ${r.row_id}. It counts at the next evidence collection.`);
    } else if (dlg.kind === "retire" || dlg.kind === "restore") {
      if (!note) { err.textContent = "Say why: the reason is kept with the change."; return; }
      const r = await api(`/api/watchlist/rows/${encodeURIComponent(dlg.row.row_id)}/${dlg.kind}`, jsonPost({ note }));
      toast(`${dlg.kind === "retire" ? "Retired" : "Restored"} ${r.row_id}.`);
    } else if (dlg.kind === "import") {
      const file = form.elements.file.files[0];
      if (!file) { err.textContent = "Choose a CSV or Excel file."; return; }
      const send = new FormData();
      send.set("file", file);
      send.set("apply", dlg.preview ? "true" : "false");
      const r = await api("/api/watchlist/import", { method: "POST", body: send });
      if (!dlg.preview) { dlg.preview = r; return; }
      toast(r.applied ? `Imported ${count(r.new, "row", "rows")} (${r.row_ids.join(" to ")}).` : "Nothing was imported.");
    } else if (dlg.kind === "original") {
      await api("/api/watchlist/use-original", jsonPost({ note }));
      toast("Matching uses the original file again. The editable copy is in the backups folder.");
    }
    $("#gwl-dlg").close();
    WL.dlg = null;
    await refreshWatchlist();
  } catch (x) {
    err.textContent = x instanceof TypeError ? "The console server did not answer." : x.message;
  } finally {
    submit.disabled = false;
    if (dlg.kind === "import" && WL.dlg === dlg) showImportPreview();   // the preview decides the button
  }
}

// ------------------------------------------------------------------ New case (short form)

function wireDialog() {
  const dlg = $("#gdlg-new"), form = $("#gform-new"), file = $("#gf-resume"), drop = $("#gf-drop");
  const more = $("#gf-more"), moreBtn = $("#gf-more-btn"), nameField = $("#gf-name"), nameErr = $("#gf-name-err");
  const formErr = $("#gf-err"), submit = form.querySelector('button[type="submit"]');
  const setDrop = () => { drop.textContent = file.files.length ? `Resume: ${file.files[0].name}` : "Drop resume PDF or choose a file"; };
  const showError = (msg) => {
    nameField.classList.toggle("err", !!msg);
    nameErr.textContent = msg;
    form.elements.name.setAttribute("aria-invalid", String(!!msg));
  };

  document.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]");
    if (!act) return;
    const what = act.dataset.act;
    if (what === "new") {
      form.reset(); setDrop(); showError(""); formErr.textContent = "";
      more.hidden = true; moreBtn.setAttribute("aria-expanded", "false");
      dlg.showModal(); form.elements.name.focus();
    }
    else if (what === "check" && S.detail) runCheck(S.detail.case_id);
    else if (what === "download") downloadReport();
    else if (what === "advanced") setView("advanced");
    else if (what === "refresh") refresh();
    else if (what === "live-again") { startLive(); updateLive(); }
    else if (what === "live-save" && S.detail) saveLiveFrames(act.dataset.log);
    else if (what === "live-remove" && S.detail) removeLiveFrames();
    else if (what.startsWith("wl-")) watchlistAction(what, act);
  });
  $("#gf-cancel").addEventListener("click", () => dlg.close());
  moreBtn.addEventListener("click", () => { more.hidden = !more.hidden; moreBtn.setAttribute("aria-expanded", String(!more.hidden)); });
  drop.addEventListener("click", () => file.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } });
  file.addEventListener("change", setDrop);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files.length) { const dt = new DataTransfer(); dt.items.add(e.dataTransfer.files[0]); file.files = dt.files; setDrop(); }
  });
  form.elements.name.addEventListener("input", () => { if (form.elements.name.value.trim()) showError(""); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!form.elements.name.value.trim()) { showError("Name is required."); form.elements.name.focus(); return; }
    const fd = new FormData(form);
    if (!fd.get("camera_refused")) fd.set("camera_refused", "false");
    if (!fd.get("identity_consent")) fd.set("identity_consent", "false");
    if (file.files.length === 0) fd.delete("resume");
    if (!fd.get("id_face_consent")) fd.set("id_face_consent", "false");
    if (!form.elements.id_document.files.length) fd.delete("id_document");
    // While it saves, the button says so; a refusal is shown inside the dialog (a toast would sit behind it).
    formErr.textContent = "";
    submit.disabled = true;
    submit.textContent = "Creating…";
    try {
      const created = await api("/api/cases", { method: "POST", body: fd });
      dlg.close();
      toast(`Created ${created.name || created.case_id}.`);
      await loadCases();
      location.hash = `#/case/${encodeURIComponent(created.case_id)}`;
    } catch (err) {
      formErr.textContent = `The case wasn't created: ${err.message}`;
    } finally {
      submit.disabled = false;
      submit.textContent = "Create case";
    }
  });
}

// ------------------------------------------------------------------ start

async function boot() {
  const view = document.body.dataset.view === "advanced" ? "advanced" : "simple";
  document.querySelectorAll("[data-view-btn]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.viewBtn === view));
    b.addEventListener("click", () => setView(b.dataset.viewBtn));
  });
  wireDialog();
  $("#gwl-form").addEventListener("submit", submitWatchlistDialog);
  $("#gwl-form").addEventListener("change", (e) => {          // another file after a preview: preview it again
    if (e.target.name === "file" && WL.dlg) { WL.dlg.preview = null; showImportPreview(); }
  });
  window.addEventListener("hashchange", route);
  Object.assign(S, parseRoute());
  render();                                          // the page's outline at once, then the data
  await Promise.all([loadCases(), loadHealth()]);
  await route();
  setInterval(loadHealth, 60000);
}

boot().catch((e) => toast(e.message, true));
