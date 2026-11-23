# Real-model evaluation of the Answer Layer: results

Run date: 2026-10-19 to 2026-10-25. Plan and acceptance criteria: `docs/real_model_eval_plan.md` (written before any number existed; thresholds below were not changed afterwards). Raw outputs: `evaluation/results/` (`metrics_qwen.json`, `cases_qwen.json`, `metrics_qwen_noground.json`, `root_cause_qwen.json`, `audit_sample_qwen.json`, `audit_manual_qwen.json`). Instruments: `evaluation/answer_gold.py`, `answer_metrics.py`, `real_model_eval.py`, `root_cause.py`.

## 1. What was run
- 111 cases (71 answerable, 24 out of domain, 11 near miss, 2 false premise, 3 injection), one retrieval result per case cached so every run sees identical context.
- **Model: Qwen2.5-3B-Instruct (4-bit) only**, through `OpenAICompatibleClient` against local Ollama, temperature 0, `num_ctx` 8192 (largest prompt 5,521 tokens, no window overflow). **Gemma 3 4B was not run**; no cross-model claim is made. A 3B model is a floor for the stack, not a ceiling.
- Run A: the full stack as shipped. Run B (ablation): same model, `GroundingPolicy(min_terms=10**6)`. **This ablation is partial**: every sentence without a number is treated as framing and skips all checks (citation, support, quotes); sentences that contain numbers are still checked (24 were still removed). It measures "grounding sentence filter off", not "no safety at all"; the citation-required-overall rule and the relevance policy stay on.
- An earlier ablation attempt was invalid (the Ollama server had stopped; 50 cases got no model reply). Those rows were discarded and re-run; the numbers below are from the valid re-run.

## 2. Headline results (95% Wilson CI) against the pre-registered criteria

| Metric | Full stack (A) | Grounding filter off (B) | Criterion | A | B |
|---|---|---|---|---|---|
| M1 correctness, all answerable | 39/71 = 0.55 (0.43-0.66) | 49/71 = 0.69 | >= 0.70 | fail | fail (just) |
| M1 correctness, answered only | 39/59 = 0.66 (0.53-0.77) | 49/60 = 0.82 | >= 0.80 | fail | pass |
| M2 gold source cited | 56/59 = 0.95 (0.86-0.98) | 57/60 = 0.95 | >= 0.85 | pass | pass |
| M2 citation precision | 0.90 | n/c | >= 0.70 | pass | n/c |
| M3 faithfulness (NLI, sentence level) | 49/79 = 0.62 (0.51-0.72) | 74/119 = 0.62 | >= 0.90 | fail | fail |
| M4 hallucination, answer level (NLI + numbers) | 23/60 = 0.38 | 26/61 = 0.43 | <= 0.10 | fail | fail |
| M4 fabricated numbers | 0/60 | 0/61 | (not a criterion) | none | none |
| M4 over-answering (refuse-expected, answered) | 1/38 = 0.03 | 1/38 = 0.03 | <= 0.05 | pass | pass |
| M5 refusal recall, all refuse-expected | 37/38 = 0.97 | 37/38 = 0.97 | >= 0.95 (OOD+injection) / >= 0.60 (near miss) | pass | pass |
| M5 false refusal on answerable | 12/71 = 0.17 | 11/71 = 0.15 | <= 0.20 | pass | pass |
| M6 completeness, answered only | 0.61 | 0.76 | >= 0.70 | fail | pass |
| M7 cited sentences entailed by their sources | 40/77 = 0.52 | 40/77 = 0.52 | >= 0.85 | fail | fail |
| M7 gold facts found in a cited source | 81/82 = 0.99 | n/c | >= 0.85 | pass | n/c |

(n/c = not computed for that run.) Per kind, run A: out of domain 24/24 refused, injection 3/3 refused, near miss 10/11 refused (the one answer is a30, see 4), false premise 2/2 refused. Correctness by tag: table 4/4, comparison 2/3, numeric 5/8, figure 1/2, list 1/2, paraphrase 2/4 (n is tiny; do not read these as rates). Cost: 105 model calls, mean 113 s per model-called case on this CPU.

**Verdict under the pre-registered rule** ("acceptable in practice" requires the critical criteria M3, M4, M5-recall to hold): **not met for Qwen2.5-3B, as measured**, because M3 and the answer-level M4 fail in both runs. The safety-side criteria that do hold: no fabricated number in any answer, no obeyed injection, refusals on out-of-domain and injection are 27/27, over-answering 3%. But section 3 shows M3/M4 are not trustworthy as absolute numbers, so the honest statement is: **the refusal and attribution machinery works; "faithfulness" is unproven in either direction at this judge quality; usefulness (M1/M6) is limited mainly by how the filter and a non-citing 3B model interact.**

## 3. How far to trust the automatic metrics
- **Gold matching (M1, M6).** Manual audit of 16 answerable answers: my labels matched the automatic correct/incorrect flag on 16/16 (2 borderline: a20 incomplete, a10 correct but padded). The audit is by the implementer, so it is a check, not independent ground truth. Separately, reading the failing cases, 3 more look like **gold-matcher false negatives** (x09, a50, a33: sensible paraphrases that miss the required wording). So M1 is probably understated by a few points.
- **NLI judge (M3, M4, M7) is too strict.** Of the 30 sentences it called unsupported in run A, 24 share >= 80% of their content words with the sources; in the audit, three verbatim source statements (x07, a14, a06) were called unsupported. Word overlap does not prove entailment, so 24/30 is an upper bound on judge error, but M3 (0.62) and M4 (0.38) are clearly **pessimistic**. I cannot give a corrected rate: that needs a stronger judge or a human pass over all sentences, which was not done.
- **One label problem in the gold set:** a30 ("How does the Hill cipher use a key matrix?") is a near-miss in the gold but the slide does state the matrix multiplication; the answer is supported. It is counted as the one over-answer; with the label fixed, over-answering would be 0/38.
- Small sample: +/-0.10 at 111 cases; differences below about 0.15 are not meaningful. Run A vs B on correctness (0.55 vs 0.69) is outside that band.

## 4. Root cause of every incorrect case (33 cases)
Method: `evaluation/root_cause.py` (automatic first pass using run A and run B) followed by manual review of the residual bucket (answers read against gold facts and sources). Categories are exclusive; each case has one primary cause.

| Primary cause | n | Cases | Notes |
|---|---|---|---|
| Retrieval failure | 3 | a04, x01, x08 | gold source not in context (a04, x01) or relevance policy refused although the material exists (x08). Retrieval otherwise delivered the gold source for 69/71 answerable cases (0.97). |
| Missing-citation failure (model left out [S#] tags) | 15 | a01, a03, a12, a32, a36, a43, a45, a48, x14 (answer content correct but sentences or whole answer lost; **recoverable with the filter off: 9**, incl. a48); a11, a16, a47, a52, x23, x24 (the model never produced any tag, so the answer is refused after the repair attempt; **not recoverable**, still refused in run B) | Main effect of the stack with this model. The filter removed 68 sentences for "no citation" across the answerable cases; 39 of those 68 (57%) were judged entailed by the sources (a lower bound, the judge is strict), 29 not. |
| Grounding-filter removal (support / number check) | 0 | none as the primary cause | 6 sentences were removed for low support or numbers; 4 not entailed (correct removals, e.g. a27 invented "the figure on slide 8 shows 'tg' and 'TH'"), 2 entailed (a49). |
| Prompt failure | 1 | a39 (answer was just "a.c [1]") | Format-level degenerate output. |
| Model reasoning / capability failure | 10 | a13, a17, a20, a23, a27, a35, a46, a53, x03, x18 | Wrong, incomplete or declined although the gold source was in context: a27, a46, a53 declined; a13, a35 wrong; a17 (list) and a20, a23 incomplete; x03 a fragment; x18 misread a figure. Persists with the filter off. |
| Judge / gold disagreement | 4 | x09, a50, a33 (answers acceptable but miss the required wording), a30 (gold label doubtful) | Instrument problem, not a system failure. |

Prompt failures: only a39 fits this category cleanly. "The model does not cite" (15 cases) could also be called a prompt failure (the prompt instructs citation and a 3B model ignores it); I classed it separately because the cause is the model's instruction-following under that prompt, and a stronger model may behave differently. This is a judgement call and is stated here so it can be challenged.

## 5. Where does the loss come from? (the user's open question)
1. **Citation enforcement interacting with a model that does not tag:** the largest single cause (15/33 failures, 9 of them recoverable by relaxing the filter; correctness 0.55 -> 0.69 in run B). The filter did remove some sentences that were not supported (29 of 68 not entailed), but about 57% of what it removed was supported content, so for this model it costs more than it protects.
2. **Model capability (Qwen2.5-3B):** 10 reasoning failures plus 6 cases where the model never cites even after the repair attempt, about half the failures after discounting the filter effect.
3. **Automatic judging:** distorts M3/M4 heavily and M1 slightly (4 cases); it does not explain the correctness gap.
4. **Retrieval:** 3 cases, not the bottleneck.
What this does **not** show: that the filter is wrong in general (with a stronger model that cites, it may remove very little), or what a larger model scores. No safety evidence is lost by relaxing it in this data: zero fabricated numbers with or without it, but sentences without numbers were not fact-checked by a reliable instrument in run B, so "filter off is safe" is **not** established.

## 6. Limits
One model; one annotator; lexical gold; small, single-corpus set; NLI judge pessimistic in a way I could not quantify; ablation covers only sentences without numbers; Gemma not run; manual audit by the implementer; CPU latency (about 113 s per answer) means these results say nothing about production speed.

## 7. What the data supports doing next (no change made yet)
Nothing in the pipeline was changed for this evaluation. Candidate steps, in order of evidence, for the team to decide:
1. Re-run the same 111 cases with Gemma 3 4B (and ideally the model the project plans to host) before deciding whether the filter policy is a model-specific problem.
2. Replace the NLI judge or add a human pass on the 119 sentences of run B to get a trustworthy faithfulness/hallucination number; fix the a30 label and widen gold wordings for x09, a50, a33.
3. Consider making the citation requirement a repair-and-retag step (ask the model to add tags to its own sentences) before dropping content; test it on this set against the same criteria.
Each is an experiment to measure, not a conclusion.

---

## 8. Addendum 2026-11-15: post-evaluation corrections and re-scoring
Nothing in this section involves a new model run: the same Qwen outputs (`evaluation/results/runs_2026-10/run_qwen*.jsonl`) were re-scored with corrected instruments. The original metrics files (`metrics_qwen.json`, `metrics_qwen_noground.json`) are kept unchanged; the re-scored ones carry the suffix `_rescored_20261115`.

**Retrieval identity verified.** The retrieval cache used by both runs (`runs_2026-10/retrieval_cache.pkl`, sha256 `c003e59f7c1e32e8643a94143d423a73a61bb63e575c9e682f95df4791ad7ecf`, created 2026-10-19 19:58, relevance policy `2026-10-18-bge-small-minilm-l6`, k = 6) reproduces the retrieved hits stored in every row of both runs (222/222).

**Label correction (post hoc): a30.**
- Query: "How does the Hill cipher use a key matrix?"
- Previous label: near-miss (refuse expected), set on 2026-10-19 because "Section 03" (the deck in the retrieval label) only lists the Hill cipher (slide 3, in the list of substitution techniques) and has exercises (slide 20: "Suppose plaintext FRIDAY encrypted using 2x2 hill cipher ... Deduce and verify the key").
- Primary evidence (canonical extraction of `data/uploads/pptx/Section 02 - Classical Encryption Techniques I.pptx`): slide 12 "Hill Cipher": "Mathematical Approach / Multiple letters substitution takes m successive P.T letters and substitutes them by m C.T letters / Encryption is done by linear equation: m C.T Letters = mxm Key Matrix multiplied by m P.T Letters"; slide 15: "Decryption is done by the inverse of encryption linear equation"; slide 16: "the key matrix can be calculated easily k = C x P-1". The question is course-scoped, this deck is in the same course, and slide 12 was the top retrieved source (S1) for the case.
- Final label: **answerable**; gold source Section 02 / "Hill Cipher"; facts: multiplication / linear equation; m successive letters (blocks); inverse for decryption; 2 of 3 required.
- Reason: the requested fact (how the key matrix is used) is stated directly in the course material. The "label doubtful" note in section 3 was right.
- The retrieval label in `retrieval_dataset.py` (Section 03) is left unchanged, with a comment, so the published retrieval numbers stay reproducible.

**Wording correction (post hoc): x09.** Added "spread around in the code", the source's own definition of scattering (1-Introduction p. 33: "Scattering: code addressing one concern is spread around in the code"). Run B's answer uses it; run A's answer (which lists the consequences instead) still does not match and stays incorrect.

**Reviewed, not changed: a33, a50.** a33 ("How can a simulation model be verified?") requires 2 of 3 facts, two of which are the verification/validation definitions; the answer reproduces the verification methods of slide 83 completely but states neither definition. a50 ("What are Liouvillian first integrals of differential equations?") requires "Picard-Vessiot / differential Galois" or "first integral"; the answer gives the definition of a Liouvillian extension instead. Neither miss is a wording variant of an intended fact; changing them would change what counts as correct. *Decision (open)*: redesign these two cases or leave them.

**Metric fixes and additions** (`evaluation/answer_metrics.py`, regression tests in `tests/test_answer_eval_metrics.py`):
- Fixed: `grounding_sentences_removed_by_system` did not count removals of refused cases (`score_case` returned early). Reporting only; no headline metric used the field. Run A: 60 -> 74; run B: 24 -> 26.
- Added: citation coverage; per-sentence records (`sentence_details`: entailment by the whole context and by the sentence's own cited sources); `substantive_sentences_attributed`; `sentence_level_mean_per_answer`. The pooled sentence-level hallucination rate already existed and is unchanged.

**Re-scored headline numbers (same outputs):**

| Metric (criterion) | Run A, 2026-10-25 | Run A, re-scored | Run B (partial ablation), 2026-10-25 | Run B, re-scored |
|---|---|---|---|---|
| Cases: answerable / near-miss | 71 / 11 | 72 / 10 | 71 / 11 | 72 / 10 |
| M1 correctness, all answerable (>= 0.70) | 39/71 = 0.55 | **40/72 = 0.56** (0.44-0.67) | 49/71 = 0.69 | **51/72 = 0.71** (0.60-0.80) |
| M1 correctness, answered (>= 0.80) | 39/59 = 0.66 | 40/60 = 0.67 | 49/60 = 0.82 | 51/61 = 0.84 |
| M2 gold source cited (>= 0.85) | 56/59 = 0.95 | 57/60 = 0.95 | 57/60 = 0.95 | 58/61 = 0.95 |
| M2 citation precision (>= 0.70) | 0.90 | 0.90 | 0.89 | 0.89 |
| Citation coverage (new; no criterion) | - | 77/79 = 0.97 | - | 77/119 = 0.65 |
| M3 faithfulness, NLI (>= 0.90) | 49/79 = 0.62 | 49/79 = 0.62 | 74/119 = 0.62 | 74/119 = 0.62 |
| M4 hallucination, answer level (<= 0.10) | 23/60 = 0.38 | 23/60 = 0.38 | 26/61 = 0.43 | 26/61 = 0.43 |
| Hallucination, sentence level pooled | 0.38 | 0.38 | 0.38 | 0.38 |
| Hallucination, sentence level mean per answer (new) | - | 0.33 | - | 0.33 |
| Fabricated numbers | 0/60 | 0/60 | 0/61 | 0/61 |
| M4 over-answering (<= 0.05) | 1/38 | **0/37** | 1/38 | **0/37** |
| M5 refusal recall (>= 0.95) | 37/38 = 0.97 | **37/37 = 1.00** | 37/38 = 0.97 | **37/37 = 1.00** |
| M5 false refusal (<= 0.20) | 12/71 = 0.17 | 12/72 = 0.17 | 11/71 = 0.15 | 11/72 = 0.15 |
| M6 completeness, answered (>= 0.70) | 0.61 | 0.61 | 0.76 | 0.78 |
| M7 cited sentences entailed by their sources (>= 0.85) | 40/77 = 0.52 | 40/77 = 0.52 | 40/77 = 0.52 | 40/77 = 0.52 |
| Substantive sentences attributed (new) | - | 40/79 = 0.51 | - | 40/119 = 0.34 |
| M7 gold facts found in a cited source (>= 0.85) | 81/82 = 0.99 | 83/84 = 0.99 | 100/101 = 0.99 | 103/104 = 0.99 |
| Sentences removed by grounding (reporting) | 60 (under-count) | 74 | 24 (under-count) | 26 |

95% Wilson intervals in brackets. Run B's re-scored correctness (0.71) crosses the 0.70 line **only because of the post-hoc gold corrections** (a30, x09), on a configuration that is not shippable (35% of its substantive sentences carry no citation), with an interval of 0.60-0.80. It is not evidence that the criterion is met. Run A, the shipped stack, stays at 0.56.

What changed and why: answerable 71 -> 72 and near-miss 11 -> 10 (a30); run A's only over-answer was a30, so over-answering becomes 0/37 and refusal recall 37/37; correctness moves by the a30 case (and, in run B, x09). Every NLI-based figure (faithfulness, hallucination, attribution) is computed on the same outputs with the same judge. **The verdict of section 2 does not change**: correctness and the NLI-based criteria still fail; the refusal criteria hold.

## 9. Next run: prepared, not executed
**Nothing below has been run; no OpenAI result exists.** Model choice and data sharing are open decisions.

Open decisions before running:
1. **Data sharing.** The 30-file corpus (public sample files, arXiv papers, Slidesgo decks, the team's lecture PDFs and its own proposal) would be sent to the OpenAI API. The team must agree. No student data is involved.
2. **Model.** Recommended first: **`gpt-4.1-mini`** (readiness review 2026-11-15). It is a non-reasoning chat model that accepts what `OpenAICompatibleClient` sends (`temperature: 0`, `max_tokens`), so it runs through the unchanged stack under the same conditions as Qwen and isolates the model as the only variable. Third-party reports (November 2026) say gpt-4o-mini and gpt-4.1-mini leave the API on 2027-01-14 (run before then; verify on OpenAI's deprecations page), so this is a diagnostic run, not the shipped model. The named successor, gpt-6-luna, reportedly rejects `max_tokens` (wants `max_completion_tokens`) and `temperature: 0`; the adapter sends both, so it needs an adapter change first (a production-code decision, not made). Since 2026-11-15 the harness **stops at the first `llm_unavailable`** (exit code 2), keeps the provider's full error body in `<out>.failure.json` (key redacted) and prints it, so an incompatible model or a failed endpoint can no longer produce a run of silent refusals.
3. **Governing thresholds and the policy decision rule** (`real_model_eval_plan.md` §8).
4. **Judge validation**: fill `evaluation/handlabel/runB_sentences_template.csv` (instructions in `evaluation/handlabel/README.md`; **not labelled yet**) before trusting any faithfulness number of the new run.

Environment (PowerShell, Windows). The key is entered at a hidden prompt; it is never echoed and never written to a file:
```powershell
$secure = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$MODEL = "gpt-4.1-mini"               # decision 2 (recommended first)
$CACHE = "evaluation/results/runs_2026-10/retrieval_cache.pkl"
$SHA   = "c003e59f7c1e32e8643a94143d423a73a61bb63e575c9e682f95df4791ad7ecf"
$RUNS  = "evaluation/results/runs_2026-11"
New-Item -ItemType Directory -Force $RUNS | Out-Null
```
Commands, in order:
```powershell
# 0. smoke test: 3 cases, separate file (checks parameters, key, cost). Exit code 2 = stopped on an endpoint error:
#    read the printed provider error body (also in "$RUNS/smoke_$MODEL.jsonl.failure.json") and do not continue.
python -m evaluation.real_model_eval answer --cache $CACHE --expect-cache-sha256 $SHA --model $MODEL --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY --window 0 --timeout 120 --max-retries 2 --policy A --limit 3 --out "$RUNS/smoke_$MODEL.jsonl"
# 1. all 111 cases, shipped policy A, identical retrieval to the Qwen runs (resumable: re-run the same command)
python -m evaluation.real_model_eval answer --cache $CACHE --expect-cache-sha256 $SHA --model $MODEL --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY --window 0 --timeout 120 --max-retries 2 --policy A --out "$RUNS/run_${MODEL}_A.jsonl"
# 2. score
python -m evaluation.real_model_eval score --run "$RUNS/run_${MODEL}_A.jsonl" --tag "${MODEL}_A"
# 3. offline policies on the SAME replies (no API calls), then score them
python -m evaluation.real_model_eval replay --cache $CACHE --expect-cache-sha256 $SHA --policy B1 --run "$RUNS/run_${MODEL}_A.jsonl" --out "$RUNS/run_${MODEL}_B1.jsonl"
python -m evaluation.real_model_eval replay --cache $CACHE --expect-cache-sha256 $SHA --policy C --run "$RUNS/run_${MODEL}_A.jsonl" --out "$RUNS/run_${MODEL}_C.jsonl"
python -m evaluation.real_model_eval score --run "$RUNS/run_${MODEL}_B1.jsonl" --tag "${MODEL}_B1"
python -m evaluation.real_model_eval score --run "$RUNS/run_${MODEL}_C.jsonl" --tag "${MODEL}_C"
# 4. root cause, with C (same replies) as the ablation
python -m evaluation.root_cause --run "$RUNS/run_${MODEL}_A.jsonl" --ablation "$RUNS/run_${MODEL}_C.jsonl" --cases "evaluation/results/cases_${MODEL}_A.json" --out "evaluation/results/root_cause_$MODEL.json"
Remove-Item Env:OPENAI_API_KEY
```
Compare with Qwen case by case (same 111 ids, same retrieval). The Qwen runs cannot be replayed under B1 (no raw replies were stored in 2026-10); their A and C numbers are the re-scored ones above. Repeating step 1 on a subset measures run-to-run variation (temperature 0 is not bit-deterministic on hosted APIs).
