// Plain-language wording for the Simple view. Every sentence here is built by code from an evidence line's
// code and data, never by a model, so the Simple view says nothing the evidence lines don't. The model-written
// report stays a download, and the Advanced view keeps the evidence IDs, analyst notes and both checks.

export const BAND_WORD = { high: "High risk", review: "Review", low: "Low risk", none: "Not checked" };
export const bandKey = (band) => ({ High: "high", Review: "review", Low: "low" }[band] || "none");

const FIELD = { email: "email", phone: "phone number", linkedin: "LinkedIn profile", github: "GitHub account",
                telegram: "Telegram handle", ip: "application IP" };
const field = (d) => FIELD[(d && d.field) || ""] || "identifier";
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

let regions = null;
function country(code) {
  if (!code) return "an unknown country";
  try {
    regions = regions || new Intl.DisplayNames(["en"], { type: "region" });
    const name = regions.of(String(code).toUpperCase());
    return name === "United States" ? "the US" : name === "United Kingdom" ? "the UK" : name;
  } catch {
    return String(code);
  }
}

// "LinkedIn account created 2026-08-14 (60 days before applying)" -> "their LinkedIn account was created 60 days before applying"
function youngAccounts(d) {
  const parts = (d.young_accounts || []).map((s) => {
    const m = String(s).match(/^(\S+) account created \S+ \((\d+) days? before applying\)/);
    return m ? `their ${m[1]} account was created ${m[2]} days before applying` : null;
  }).filter(Boolean);
  return parts.length ? parts.join(" and ") : "their accounts were created recently";
}

// One entry per scored evidence code: a short tile line, a reason card sentence, and a clause for the headline.
const SCORED = {
  watchlist_match: (d) => ({
    why: `${cap(field(d))} matches a watchlist entry.`,
    reason: `The ${field(d)} matches watchlist entry ${(d.rows || [])[0] || ""}${d.ring_size > 1 ? `, which is linked to a ring of ${d.ring_size} personas` : ""}.`,
    clause: `the ${field(d)} on this application matches a known fraud watchlist entry`,
  }),
  watchlist_ip: () => ({
    why: "Application IP matches a watchlist entry.",
    reason: "The application IP matches a watchlist entry.",
    clause: "the application IP matches a known fraud watchlist entry",
  }),
  victim_profile_match: (d) => ({
    why: `${cap(field(d))} appears on the watchlist as impersonated.`,
    reason: `The ${field(d)} appears on the watchlist as a profile someone impersonated, so it counts only as weak evidence.`,
    clause: `the ${field(d)} appears on the watchlist as an impersonated profile`,
  }),
  name_similarity: () => ({
    why: "Name resembles a watchlist persona.",
    reason: "The name is similar to a persona on the watchlist. Names are weak evidence, because many people share them.",
    clause: "the name resembles a watchlist persona",
  }),
  resume_injection: (d, n) => ({
    why: "Resume hides instructions for AI screeners.",
    reason: `The resume contains hidden text with instructions aimed at AI screeners${n > 1 ? ` (${n} places)` : ""}.`,
    clause: "the resume hides instructions aimed at AI screeners",
  }),
  visible_injection: (d, n) => ({
    why: "Resume has instructions for AI screeners.",
    reason: `The resume contains visible instructions aimed at AI screeners${n > 1 ? ` (${n} places)` : ""}.`,
    clause: "the resume contains instructions aimed at AI screeners",
  }),
  hidden_text: () => ({
    why: "Resume has hidden keyword text.",
    reason: "The resume has hidden text without instructions, often keyword stuffing for applicant-tracking systems.",
    clause: "the resume has hidden keyword text",
  }),
  template_reuse: (d) => {
    const k = (d.matches || []).length || 1;
    return {
      why: `Resume shares a template with ${count(k, "other applicant", "other applicants")}.`,
      reason: `The resume wording nearly matches ${count(k, "other resume", "other resumes")} in this batch.`,
      clause: `the resume nearly matches ${k === 1 ? "another applicant's" : `${k} other applicants'`}`,
    };
  },
  country_mismatch: (d) => ({
    why: "Claimed location does not match the IP.",
    reason: `They say they are in ${country(d.claimed)}, but the application came from an IP in ${country(d.observed)}.`,
    clause: `the application came from ${country(d.observed)}, not ${country(d.claimed)} as stated`,
  }),
  hosting_ip: () => ({
    why: "Applied from a hosting or VPN network.",
    reason: "The application came from a hosting or VPN network, not a home or mobile connection.",
    clause: "the application came from a hosting or VPN network",
  }),
  voip_phone: () => ({
    why: "Phone number is a VoIP line.",
    reason: "The phone number is an online VoIP line, the kind that can be set up with little identity checking.",
    clause: "the phone number is an online VoIP line",
  }),
  young_accounts: (d) => ({
    why: "Accounts are new for the experience claimed.",
    reason: `They claim ${d.claimed_years ?? "several"} years of experience, but ${youngAccounts(d)}.`,
    clause: "their accounts are much newer than the experience they claim",
  }),
  disposable_email: () => ({
    why: "Disposable email address.",
    reason: "The email address comes from a disposable email service.",
    clause: "the email address comes from a disposable email service",
  }),
  new_email_domain: (d) => ({
    why: "Email domain registered recently.",
    reason: `The email's domain was registered${d.registered ? ` on ${d.registered}` : ""}, shortly before applying.`,
    clause: "the email domain was registered shortly before applying",
  }),
  phone_country_mismatch: () => ({
    why: "Phone country doesn't match.",
    reason: "The phone number's country doesn't match the country they gave.",
    clause: "the phone number is from a different country than stated",
  }),
  github_not_found: () => ({
    why: "Listed GitHub account not found.",
    reason: "The GitHub account they listed doesn't exist.",
    clause: "the GitHub account they listed doesn't exist",
  }),
  id_face_mismatch: () => ({
    why: "ID photo doesn't match the interview face.",
    reason: "The photo on their ID doesn't match the face in the interview video.",
    clause: "the ID photo doesn't match the interview face",
  }),
  id_mrz_check_failed: () => ({
    why: "The ID's check digits don't add up.",
    reason: "The check digits in the ID's machine-readable lines don't add up, which happens with altered or made-up documents (or a poor scan).",
    clause: "the ID's check digits don't add up",
  }),
  id_name_mismatch: () => ({
    why: "Name on the ID doesn't match.",
    reason: "The name on their ID doesn't match the name on the application.",
    clause: "the name on the ID doesn't match the application",
  }),
  camera_refused: () => ({
    why: "Camera off during the interview.",
    reason: "They kept the camera off or said it was broken during the interview.",
    clause: "the camera stayed off during the interview",
  }),
  deepfake_score: () => ({
    why: "Face check flagged the interview video.",
    reason: "The face check flagged the interview video as likely face-swapped.",
    clause: "the face check flagged the interview video",
  }),
  voice_clone_score: () => ({
    why: "Voice check flagged the interview audio.",
    reason: "The voice check flagged the interview audio as likely cloned.",
    clause: "the voice check flagged the interview audio",
  }),
};

// Info lines worth a card of their own: checks that didn't run or couldn't decide.
const GAPS = {
  no_recording: ["Not checked", "No interview recording yet. Record the next interview to check the video."],
  detector_not_configured: ["Not checked", "The face check isn't set up on this computer, so the video wasn't checked."],
  deepfake_inconclusive: ["Inconclusive", "The face check couldn't give a clear answer on this recording."],
  voice_not_configured: ["Not checked", "The voice check isn't set up on this computer, so the audio wasn't checked."],
  voice_inconclusive: ["Inconclusive", "The voice check couldn't give a clear answer: too little clear speech."],
  no_resume: ["Not checked", "No resume on file, so the resume checks didn't run."],
  watchlist_skipped: ["Not checked", "No watchlist is loaded, so the identifiers weren't compared."],
  id_mrz_unreadable: ["Not checked", "The ID's machine-readable lines couldn't be read, so its check digits and name weren't checked."],
  id_face_not_run: ["Not checked", "The ID photo wasn't compared with the interview face (no consent, no recording, or no face found)."],
  id_face_inconclusive: ["Inconclusive", "The ID photo and the interview face couldn't be compared clearly."],
};

const STRENGTH_WORD = { strong: "Strong", moderate: "Moderate", weak: "Weak" };
const FAMILY_ORDER = { A1: 0, A2: 1, A3: 2 };

function wording(signal, n = 1) {
  const make = SCORED[signal.code];
  if (make) return make(signal.data || {}, n);
  // An evidence code without plain wording yet: fall back to the evidence line's own first sentence.
  const first = String(signal.text || "").split(/(?<=\.)\s/)[0];
  return { why: first, reason: first, clause: first.replace(/\.$/, "").replace(/^./, (c) => c.toLowerCase()) };
}

// Scored evidence grouped by code (two hidden-text lines become one card). The code's own MOST CRITICAL FINDING
// leads (score.py breaks ties by priority), then the rest strongest first.
function scoredGroups(evidence) {
  const groups = new Map();
  for (const s of (evidence && evidence.signals) || []) {
    if (!s.points) continue;
    const g = groups.get(s.code) || { code: s.code, family: s.family, signals: [], points: 0, top: s, critical: false };
    g.signals.push(s);
    g.points = Math.max(g.points, s.points);
    if (s.points > g.top.points) g.top = s;
    if (s.evidence_id === evidence.most_critical) g.critical = true;
    groups.set(s.code, g);
  }
  return [...groups.values()].sort((a, b) => (b.critical - a.critical) || b.points - a.points
    || FAMILY_ORDER[a.family] - FAMILY_ORDER[b.family]);
}

// [{label, key, text}]: one card per scored code, then one per check that didn't run.
export function reasonsFor(evidence) {
  const out = scoredGroups(evidence).map((g) => ({
    label: STRENGTH_WORD[g.top.strength] || "Signal",
    key: g.top.strength,
    text: wording(g.top, g.signals.length).reason,
  }));
  const seen = new Set();
  for (const s of (evidence && evidence.signals) || []) {
    if (s.points || !GAPS[s.code] || seen.has(s.code)) continue;
    seen.add(s.code);
    out.push({ label: GAPS[s.code][0], key: "none", text: GAPS[s.code][1] });
  }
  return out;
}

// The verdict card's sentence: the strongest finding, plus the strongest one from another family, if any.
export function headlineFor(evidence) {
  if (!evidence) {
    return "Run a check to see how risky this application looks. It reads the resume, the application and any interview recording, and takes about a minute.";
  }
  const groups = scoredGroups(evidence);
  if (!groups.length) return "Nothing in this application needs attention.";
  const first = wording(groups[0].top, groups[0].signals.length).clause;
  if (bandKey(evidence.band) === "low") return `Only a minor signal: ${first}.`;
  const other = groups.find((g) => g.family !== groups[0].family);
  return `${cap(first)}${other ? `, and ${wording(other.top, other.signals.length).clause}` : ""}.`;
}

// One line for a case tile, from the case list's most critical signal.
export function whyFor(summary) {
  const s = summary && summary.critical_signal;
  if (s && s.code) return wording(s).why;
  const line = String((summary && summary.most_critical) || "").replace(/^MOST CRITICAL FINDING:\s*E\d+\.\d+\s*/, "");
  return line.split(/(?<=\.)\s/)[0];
}

// What one of the code's checks found (chimera/checks.py: bundle_check.txt or evidence_check.txt). The problems are
// the "- " lines under the "... PROBLEMS ..." heading, up to the next blank line: since Oct 23 the Bundle Check adds a
// CONTRADICTIONS section after it, whose "- None found." line is not a problem. quotes: the Evidence Check's counts.
export function checkResult(text) {
  if (!text) return null;
  const block = (String(text).split(/PROBLEMS[^\n]*\n/)[1] || "").split(/\n\s*\n/)[0];
  const problems = block.split("\n").filter((l) => l.startsWith("- ") && l.trim() !== "- none").length;
  const m = String(text).match(/citations in report: (\d+); verified: (\d+)/);
  return { problems, quotes: m ? { cited: +m[1], verified: +m[2] } : null };
}

// The live face check's reading, from the newest row of scripts/live_check.py's score log (/api/live/events). The
// verdict column says "checking n/8", "looks real", "LIKELY FAKE" or "paused" (the same picture again: a paused player
// or a frozen feed); face_found is "False" when no face was in view, and then the verdict is from the last faces seen.
// closed: the feed stopped. stale: the log has had no new row for a few seconds (the live check writes two a second),
// so its last row is history, not the call now: the server replays the newest log from the start even when
// live_check.py is not running, and an old "LIKELY FAKE" must not pass for a reading of this call.
export function liveReading(row, closed = false, stale = false) {
  if (closed) return { key: "wait", word: "Feed closed", say: "The live check feed stopped. Follow it again once the live check is running." };
  if (!row) return { key: "wait", word: "Waiting", say: "Start the live check on this computer (python scripts\\live_check.py); its readings appear here." };
  if (stale) {
    return { key: "wait", word: "No new readings", say: "The live check hasn't written a new reading, so nothing here describes the call now. "
      + "Is it running (python scripts\\live_check.py)?" };
  }
  const v = String(row.verdict || "");
  const noFace = String(row.face_found) === "False";
  if (/^paused/i.test(v)) {
    return { key: "wait", word: "Paused", say: "The video shows the same picture again (a paused player or a frozen feed), so it isn't being checked." };
  }
  if (/fake/i.test(v)) {
    return { key: "high", word: "Likely fake", say: "The face on the call may be digitally altered. Carry on with the interview as usual; "
      + "the recording and this reading go to the hiring team." + (noFace ? " No face in view right now; this reading is from the last faces seen." : "") };
  }
  if (/real/i.test(v)) {
    return { key: "low", word: "Looks real", say: noFace ? "No face in view right now. The last faces seen showed no sign of a face swap."
      : "No sign of a face swap in the last few seconds." };
  }
  const m = v.match(/(\d+)\s*\/\s*(\d+)/);
  const sofar = m ? ` (${m[1]} of ${m[2]} checks so far)` : "";
  return { key: "review", word: "Checking", say: noFace ? `Waiting for a face on the call${sofar}.` : `Reading the face on the call${sofar}.` };
}

// The line under the meter: which log it follows and the cut-off that log says it used (never a constant here).
// (Until Oct 25 it added "Scores only, no pictures"; the live check now keeps its five most suspicious moments.)
export function liveSource(file, cutoff) {
  if (!file) return "";
  const cut = Number.parseFloat(cutoff);
  return `Following ${file}${Number.isFinite(cut) ? `, cut-off ${cut.toFixed(2)} from the log` : ""}.`;
}

// Why a report is out of date (chimera/api.py report_freshness): the evidence on file now is not the evidence the
// agents were given. Reports from before Oct 19 carry no fingerprint of that evidence, so a newer evidence file is
// all the API can see for them.
const STALE_WHY = {
  changed: "The evidence changed after this report was written.",
  collected_again: "The evidence was collected again after this report was written, and the report is too old to "
    + "show whether anything changed.",
  no_evidence: "There is no evidence on file for this case now.",
};
export const staleWhy = (why) => STALE_WHY[why] || STALE_WHY.changed;
