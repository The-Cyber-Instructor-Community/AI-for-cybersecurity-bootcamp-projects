// Node's built-in test runner: node --test tests/web/plain.test.mjs (tests/test_web.py runs it when Node is installed).
import test from "node:test";
import assert from "node:assert/strict";
import { BAND_WORD, bandKey, checkResult, headlineFor, liveReading, liveSource, reasonsFor, staleWhy, whyFor } from "../../web/plain.js";

const sig = (evidence_id, family, code, strength, points, data = {}, text = "") => ({ evidence_id, family, code, strength, points, data, text });

// Shaped like out/case_005/evidence.json (synthetic case).
const case005 = {
  band: "High", score: 8, most_critical: "E3.1",
  signals: [
    sig("E1.1", "A1", "no_recording", "info", 0),
    sig("E2.1", "A2", "resume_injection", "strong", 4, { page: 1 }),
    sig("E2.2", "A2", "resume_injection", "strong", 4, { page: 1 }),
    sig("E2.3", "A2", "template_clear", "info", 0),
    sig("E3.1", "A3", "watchlist_match", "strong", 4, { field: "email", rows: ["W-0117"], ring_size: 5 }),
  ],
};

test("band words", () => {
  assert.equal(BAND_WORD[bandKey("High")], "High risk");
  assert.equal(BAND_WORD[bandKey("Review")], "Review");
  assert.equal(BAND_WORD[bandKey(null)], "Not checked");
});

test("the headline leads with the code's most critical finding, then another family", () => {
  assert.equal(headlineFor(case005),
    "The email on this application matches a known fraud watchlist entry, and the resume hides instructions aimed at AI screeners.");
});

test("reasons: one card per scored code, then checks that didn't run", () => {
  const r = reasonsFor(case005);
  assert.deepEqual(r.map((x) => x.label), ["Strong", "Strong", "Not checked"]);
  assert.equal(r[0].text, "The email matches watchlist entry W-0117, which is linked to a ring of 5 personas.");
  assert.equal(r[1].text, "The resume contains hidden text with instructions aimed at AI screeners (2 places).");
  assert.equal(r[2].text, "No interview recording yet. Record the next interview to check the video.");
});

test("low risk and not checked", () => {
  assert.equal(headlineFor({ band: "Low", signals: [sig("E3.1", "A3", "name_similarity", "weak", 1)] }),
    "Only a minor signal: the name resembles a watchlist persona.");
  assert.equal(headlineFor({ band: "Low", signals: [sig("E1.1", "A1", "no_recording", "info", 0)] }),
    "Nothing in this application needs attention.");
  assert.match(headlineFor(null), /^Run a check to see how risky this application looks/);
});

test("countries are named, and unknown codes fall back to the evidence line", () => {
  const r = reasonsFor({ band: "Review", signals: [sig("E3.2", "A3", "country_mismatch", "moderate", 2, { claimed: "US", observed: "PL" })] });
  assert.equal(r[0].text, "They say they are in the US, but the application came from an IP in Poland.");
  const odd = reasonsFor({ band: "Review", signals: [sig("E3.9", "A3", "brand_new_signal", "moderate", 2, {}, "Something odd happened. More detail.")] });
  assert.equal(odd[0].text, "Something odd happened.");
});

test("tile lines", () => {
  assert.equal(whyFor({ critical_signal: { code: "watchlist_match", data: { field: "email" } } }), "Email matches a watchlist entry.");
  assert.equal(whyFor({ most_critical: "MOST CRITICAL FINDING: E3.4 Phone line is odd. Second sentence." }), "Phone line is odd.");
});

// Shaped like chimera/checks.py's output (bundle_check.txt since Oct 23, with the CONTRADICTIONS section; evidence_check.txt).
const BUNDLE = "BUNDLE CHECK (code)\n\n| Analyst | Report found |\n|---|---|\n| A1 Video | yes |\n\nBUNDLE PROBLEMS / COVERAGE GAPS\n- none\n\n"
  + "CONTRADICTIONS (written by code; the Reporter copies these lines under ## Contradictions)\n- None found. The resume and application evidence points the same way (E2.1; E3.1).";
const EVIDENCE = "EVIDENCE CHECK (code)\n\n- Evidence citations in report: 3; verified: 3\n- Scored evidence lines cited: 3 of 3\n\nEVIDENCE PROBLEMS\n- none\n\nNote: this proves quotes are real.";

test("check results: the Contradictions line after the problems is not a problem", () => {
  assert.deepEqual(checkResult(BUNDLE), { problems: 0, quotes: null });
  assert.deepEqual(checkResult(EVIDENCE), { problems: 0, quotes: { cited: 3, verified: 3 } });
  const bad = BUNDLE.replace("COVERAGE GAPS\n- none", "COVERAGE GAPS\n- A2 Resume: E2.2 not cited\n- A3 Application: no STATUS line");
  assert.equal(checkResult(bad).problems, 2);
  assert.equal(checkResult(""), null);
});

// Rows shaped like /api/live/events (scripts/live_check.py's log columns, as strings).
const row = (verdict, face_found = "True", average = "0.3", cutoff = "0.46") => ({ seconds: "4.0", face_found, face_score: "0.3", average, verdict, cutoff });

test("live reading: every verdict the live check writes", () => {
  assert.equal(liveReading(null).word, "Waiting");
  assert.equal(liveReading(null, true).word, "Feed closed");
  assert.deepEqual([row("checking 3/8"), row("looks real"), row("LIKELY FAKE"), row("paused", "False", "")].map((r) => liveReading(r).key),
    ["review", "low", "high", "wait"]);
  assert.equal(liveReading(row("checking 3/8")).say, "Reading the face on the call (3 of 8 checks so far).");
  assert.equal(liveReading(row("paused", "False", "")).word, "Paused");
});

test("live reading: a closed feed or a log with no new rows never shows its last verdict as the call now", () => {
  assert.equal(liveReading(row("LIKELY FAKE"), true).word, "Feed closed");
  const stale = liveReading(row("LIKELY FAKE"), false, true);
  assert.equal(stale.word, "No new readings");
  assert.equal(stale.key, "wait");
  assert.doesNotMatch(stale.say, /fake|altered/i);
});

test("live reading: no face in view says the reading is from the last faces", () => {
  assert.equal(liveReading(row("looks real", "False")).say, "No face in view right now. The last faces seen showed no sign of a face swap.");
  assert.match(liveReading(row("LIKELY FAKE", "False")).say, /No face in view right now; this reading is from the last faces seen\.$/);
  assert.equal(liveReading(row("checking 0/8", "False", "")).say, "Waiting for a face on the call (0 of 8 checks so far).");
});

test("live source line: the cut-off comes from the log row, never a constant", () => {
  assert.equal(liveSource("live_x.csv", "0.46"), "Following live_x.csv, cut-off 0.46 from the log.");
  assert.equal(liveSource("live_x.csv", undefined), "Following live_x.csv.");
  assert.equal(liveSource("", "0.46"), "");
});

test("out-of-date reports say why", () => {
  assert.equal(staleWhy("changed"), "The evidence changed after this report was written.");
  assert.match(staleWhy("collected_again"), /^The evidence was collected again/);
  assert.equal(staleWhy(undefined), staleWhy("changed"));
});
