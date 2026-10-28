# Wiring the LangFlow flow (Phase 2)

The flow copies the Assignment 2 layout:

```
Chat Input (case ID, e.g. case_005)
  -> Orchestrator agent  [tools: A1 Video, A2 Resume, A3 Application analysts]
       \-> second Chat Output on the Orchestrator's Response (keeps tool calls visible)
  -> Bundle Check (custom code component)
  -> Reporter agent
  -> Evidence Check (custom code component)
  -> Chat Output
```

Run `python -m chimera run ...` first. The flow only reads `out/<case>/evidence.md`; no model runs inside the flow except the agents.

## 1. Make `chimera` importable from LangFlow

From the repo root, in the same Python environment LangFlow runs in:

```
pip install -e .
```

Each custom component has an advanced field **Chimera folder**. Set it once in each copy to the repo folder (the one that holds `chimera\` and `out\`, not `out\` itself); its default is a placeholder. The components read `out/<case>/evidence.md` under it. `CHIMERA_OUT` is read only by the Console.

## 2. Custom components

Adapt these functions to your LangFlow version's custom-component template (inputs and outputs differ between versions). Log the version in `docs/DECISIONS.md`.

Each analyst's only Chimera tool is the Case Reader (the Orchestrator's tools are the three analysts; the Reporter has none). LangFlow's Agent component also switches on two built-in tools by default, Current Date and Calculator, and they stayed on in every run measured: in the last saved run of each of the ten synthetic cases (Oct 25) an agent asked for the date in 7 and none used the calculator (`docs/EVALUATION.md` section 24). Neither reaches the network. Turning them off is a step for after the demo.

**Case Reader** (attach to each analyst as its only tool):

```python
from pathlib import Path
from chimera.bundle import read_section

def case_reader(case_id: str, family: str, chimera_dir: str) -> str:
    """Return one family's evidence section (A1, A2 or A3) for a case."""
    out = Path(chimera_dir) / "out"
    return read_section((out / case_id / "evidence.md").read_text(encoding="utf-8"), family)
```

**Bundle Check** (input: the Orchestrator's full text):

```python
from chimera.checks import bundle_check
result = bundle_check(evidence_md_text, orchestrator_text)
```

**Evidence Check** (input: the Reporter's text):

```python
from chimera.checks import evidence_check
result = evidence_check(evidence_md_text, report_text)
```

The Reporter also needs the bundle's "Code score" section. Pass `evidence.md` (or just its last section) into the Reporter's prompt input.

## 3. Agents

| Agent | Prompt | Tools |
|---|---|---|
| A1 Video analyst | `prompts/analyst_video.md` | Case Reader |
| A2 Resume analyst | `prompts/analyst_resume.md` | Case Reader |
| A3 Application analyst (shown as "Application & OSINT" in the Console; it reads the lookups, web leads, watchlist and ID check lines) | `prompts/analyst_application.md` | Case Reader |
| Orchestrator | `prompts/orchestrator.md` | the three analysts, as tools |
| Reporter | `prompts/reporter.md` | none |

- **Stream off on every agent** (Assignment 2: streaming interleaved and garbled the output).
- Tool descriptions for the analysts, e.g. "A2 Resume analyst. Input: case ID. Returns the resume findings report."
- Model: the local 30B used in Assignment 2. Only switch to the Claude API after asking Darpan (decision D3).

## 4. Test without LangFlow

`examples/` holds a hand-written analyst output and report for `case_005`. Both checks should report no problems:

```
python -m chimera check-bundle   --evidence out/case_005/evidence.md --analysts langflow/examples/case_005_analysts.txt
python -m chimera check-evidence --evidence out/case_005/evidence.md --report   langflow/examples/case_005_report.md
```

The example's names and row IDs come from the synthetic data generated with seed 13. A different Faker version can change them, so if the checks complain, compare the example against your own `out/case_005/evidence.md`.

## 5. Step by step in LangFlow Desktop 1.12 (Oct 18)

The custom components are in `components/` (tested: on `case_005` with the hand-written example, both checks print "- none"). Paste each file whole into a Custom Component's Code editor, then Check & Save.

0. Check the agents' model: `python scripts\check_agent_model.py http://localhost:11434 qwen3-coder:30b` (one tool call like the analysts', and speed). Keep Ollama on localhost only (Ollama app settings: "Expose Ollama to the network" off).
1. **Case Reader x3**: `components/case_reader.py`; Family A1, A2, A3 (one copy each); Tool Mode on. Chimera folder (advanced): the repo folder.
2. **Three analyst Agents**: model `qwen3-coder:30b` from Ollama (`http://localhost:11434`, or the OpenAI-compatible `http://localhost:11434/v1` with any API key text); instructions from `prompts/analyst_video.md`, `analyst_resume.md`, `analyst_application.md`; each one's Case Reader on its Tools input; stream off; Tool Mode on, named `A1_Video_analyst` (and A2, A3) with a one-line description.
3. **Orchestrator** Agent: `prompts/orchestrator.md`; Tools = the three analysts; Chat Input in; its Response to Chat Output #1 (keeps the analyst reports and tool calls visible; the console reads them there).
4. **Bundle Check**: `components/bundle_check.py`; Case ID from Chat Input; Orchestrator output from the Orchestrator's Response. Chimera folder (advanced): the repo folder.
5. **Reporter**: a Prompt Template `Orchestrator output:\n{orchestrator}\n\n{bundle}` (Orchestrator's Response, Bundle Check) into an Agent with `prompts/reporter.md`, no tools, stream off; its Response to Chat Output #2 (the report).
6. **Evidence Check**: `components/evidence_check.py`; Case ID from Chat Input; Report from the Reporter's Response; to Chat Output #3. Chimera folder (advanced): the repo folder.
7. **Playground**: `case_005`. The report starts with the bundle's MOST CRITICAL FINDING and CODE SCORE lines, and both checks end in "- none".
8. **Console**: create a LangFlow API key, copy the flow ID, and put `LANGFLOW_URL=http://127.0.0.1:7860`, `LANGFLOW_FLOW_ID` and `LANGFLOW_API_KEY` in `chimera\.env` (gitignored); restart the console; Run analysts on `case_005` shows the LangFlow banner.

The 30B takes about 18 GB of the 24 GB GPU while the flow runs, so don't run the video detector at the same time (`ollama stop qwen3-coder:30b` frees it).

First run (Oct 18, Analyst A1 alone on `case_005`) led to two fixes before building the rest:

- **Model:** use `qwen3-coder-16k` in every Agent. Create it once: `ollama create qwen3-coder-16k -f langflow\qwen3-coder-16k.Modelfile` (same weights, no extra download). The Ollama app's Context length setting (here 256K) applies to every model it loads. At 256K the 30B took 45 GB and ran half on the CPU, and one analyst took 129.5 s, although its two calls used only 777 and 924 tokens. After a run, `ollama ps` should show PROCESSOR 100% GPU and CONTEXT 16384.
- **Analyst prompts:** STATUS now says whether the analyst did its job, and Limits copies the info lines word for word. With no recording, the first run wrote `STATUS: INCOMPLETE`, which Bundle Check reports as an unfinished analyst, and its Limits sentence added an ID check the evidence never mentions.

First Orchestrator run (Oct 18, `case_005`): it called all three analysts and their reports came back right, but it pasted them without their first lines (Bundle Check: all three "report missing"), called two findings that point the same way a contradiction, and wrote three follow-up questions that each told the candidate what was found (one asked about "a known watchlist ring"). Fixes: `prompts/orchestrator.md` (paste from the first line; what a contradiction is; five allowed kinds of question and why), `prompts/reporter.md` (leave out flagged questions), and a code check on the questions in both Bundle Check and Evidence Check (`chimera/checks.py`, `question_problems`). After `git pull`, paste the new `orchestrator.md` into the Orchestrator; LangFlow picks up the new checks when Bundle Check first runs.

Second Orchestrator run (same day): the reports came through whole and "Contradictions: None found." was right, but two questions were still unsafe in ways a word check misses (an invented date discrepancy; a hint at the email check). The follow-up questions are now a closed list: six approved questions in `chimera/schema.py` and `prompts/orchestrator.md`; the Orchestrator copies 3 to 5 word for word, and both checks flag anything else.

Full flow (Oct 18, `case_005`): the whole chain ran (Orchestrator, Bundle Check, Reporter, Evidence Check), and Bundle Check flagged all five of the Orchestrator's questions, but the Reporter kept them all. Since then **code chooses the follow-up questions** (`chimera/questions.py`): the pipeline writes them into the evidence bundle, Bundle Check ends with a FOLLOW-UP QUESTIONS section for the Reporter to copy, and the Orchestrator no longer writes questions. After updating: run Collect evidence again (the bundles gain the questions), paste the new `prompts/orchestrator.md` and `prompts/reporter.md`, and restart LangFlow Desktop so it reloads the chimera code (it keeps modules loaded between runs).

Later the same day: **Chimera never addresses the candidate** (Darpan). Its output goes only to the hiring team, so the follow-up questions are gone: the Orchestrator writes none, the report has no questions section, and both checks flag one if an agent writes it anyway. The recruiter screen asks for nothing beyond camera on, so there is no liveness step either. After pulling: run Collect evidence again, paste the new `prompts/orchestrator.md`, `prompts/reporter.md` and `prompts/analyst_video.md`, and restart LangFlow Desktop.

Full flow after that change (Oct 18, `case_005`): no questions anywhere, the Orchestrator ends with Contradictions and the dispatch log, Bundle Check found no problems, and the report goes from Contradictions to Checks. Evidence Check reported one finding without an Evidence: line. LangFlow's message store showed the cause: the Reporter wrote "- No scored evidence." as a bullet under [A1], although its prompt asks for plain text. That line is not a finding, so the check now accepts it with or without a bullet, and any real finding without evidence is named in the problem. Two other things from this run:

- **Each analyst report appears twice in the Orchestrator's output.** LangFlow 1.12 adds every nested agent's answer to the parent agent's message (`lfx/base/agents/events.py`, `handle_on_chat_model_end`), so the analysts' own answers come first, glued together without line breaks, and then the Orchestrator's copy. The model isn't doing it, so no prompt change fixes it. The checks read both copies; the console shows one of each (`tidy_committee_text`); the Playground still shows both.
- **The Orchestrator left out the "point the same way" sentence** although the resume and application families both scored. The CODE SCORE line still shows both families' points, so the report carries that fact either way.

The checks are also stricter now: an evidence ID named in the Orchestrator's notes or anywhere in the report must exist in the bundle, and scored evidence the report leaves out is a problem. After pulling, quit and reopen LangFlow Desktop and restart the console. No prompts changed.

## 6. Pass rate through the Console (Oct 19)

Ten synthetic cases, three rounds each, sent through the flow by the Console (`tools\agent_passrate.ps1`, a script outside the repo on the PC, keeps every run's checks, report and, from the third run on, the analysts' text; `python scripts/agent_passrate_summary.py --runs data/scores/agent_passrate_<name>` sorts the failures).

- **Shared chat memory.** The Console sent no `session_id`, so LangFlow used the flow ID as the session for every run and the agents' chat memory carried one case into the next: `case_004`'s analysts quoted `case_005`'s watchlist match. 3 of 12 runs passed both checks; 26 quotes were not verbatim (17 found in no bundle, 9 from `case_005`), and three reports held 21 items (quotes, emails, watchlist rows) from another case. Evidence Check failed every one of those runs. Fixed in `chimera/agents_client.py`: every run gets its own session (`chimera-<case>-<random>`, kept in `flow_meta.json`).
- **With a fresh session** 18 of 30 runs passed both checks, nothing came from another case, and every failure came from the prompts' own templates: the Orchestrator copied its example "(E1.2; E3.1)" (5 runs) or adapted it to cite "No interview recording", an info line (2 runs, which both checks passed); A3 wrapped quotes in the angle brackets of the `"<quote>"` placeholder or lower-cased their first letter (6 quotes); and the Orchestrator listed `case_008`'s claimed-experience line, which code already compares inside one line and its prompt named as an example, as a contradiction, so the Reporter left that finding out of [A3] (3 runs).
- **Changes.** No example IDs and no `"<quote>"` in any prompt; the analysts' quote rule names capital letters and angle brackets; a contradiction is two lines, and a line code already compared stays a finding; the Reporter keeps every analyst finding under its family. Both checks now read the Contradictions section: a contradiction cites two lines, and "point the same way" cites scored lines from two families and no info line.

After pulling: put all five prompts into their agents (`analyst_video.md`, `analyst_resume.md`, `analyst_application.md`, `orchestrator.md`, `reporter.md`), quit and reopen LangFlow Desktop (it reloads the checks), and restart the console.

Two more rounds the same night (`docs/EVALUATION.md` section 13): with the first revision 24 of 30 runs passed (four times the Orchestrator wrote that one family "points the same way"; once the Reporter dropped "Evidence:" after its format line lost that word), and after a second revision of `orchestrator.md` and `reporter.md`, 27 of 30. Both checks also flag an email, watchlist row, ring, phone number, IP address or profile the case's evidence does not contain. On the PC, `tools\langflow_set_prompts.py --apply` (outside the repo) puts the five prompt files into the flow through LangFlow's API (it saves the flow to `tools\backups\` first and reads every Agent back); quit and reopen LangFlow Desktop after a change to `chimera/checks.py`.

## 7. Contradictions written by code (Oct 23)

Every failed run in sections 13 and 14 of `docs/EVALUATION.md` was in the Orchestrator's Contradictions section, and every fact it needs is in the bundle. `chimera/contradictions.py` writes the section now (`## Contradictions (code)` in `evidence.md`, `contradictions` in `evidence.json`): the contradictions code can see, then "None found." with the same-way sentence built from the families that have scored lines. The Bundle Check appends the lines to its output under CONTRADICTIONS, the Reporter copies them under `## Contradictions`, and the Evidence Check requires the copy, line for line, with nothing added. The Orchestrator's prompt loses Step 2: it writes "Contradictions: written by code." and the dispatch log.

After pulling: `tools\langflow_set_prompts.py --apply` (on the PC, outside the repo) (the Orchestrator and the Reporter changed), then quit and reopen LangFlow Desktop so it re-reads `chimera/checks.py`, and restart the Console. A report written with the old prompts against a new bundle fails the Evidence Check's copy rule, which is the point.
