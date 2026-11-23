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

## 9. Next run: prepared 2026-11-15 (executed 2026-11-23 with DeepSeek instead of OpenAI, see section 10)
**No OpenAI result exists.** The protocol below was executed unchanged on 2026-11-23 with `MODEL=deepseek-chat`, `--base-url https://api.deepseek.com` and `--api-key-env DEEPSEEK_API_KEY` (bash, Linux), writing to `runs_2026-11/` and passing `--out-dir "$RUNS"` to `score`; results in section 10. The text below is kept as written on 2026-11-15.

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

## 10. DeepSeek run (2026-11-23)

### 10.1 What was run (*measured*)
- Protocol of section 9, unchanged code: `answer` (policy A, live), `replay` B1 and C on the same recorded replies (no API calls), `score` for each. Outputs in `evaluation/results/runs_2026-11/`: `smoke_deepseek-chat.jsonl` (3 cases), `run_deepseek-chat_{A,B1,C}.jsonl`, `metrics_/cases_/audit_sample_deepseek-chat_{A,B1,C}.json`, `root_cause_deepseek-chat.json` (A with C as the ablation) and `SHA256SUMS.txt` (14 artifacts, paths relative to the repository root; verify with `sha256sum -c evaluation/results/runs_2026-11/SHA256SUMS.txt` from the root).
- Model: requested `deepseek-chat`; **every reply (75/75) reports `model: deepseek-flash`**. DeepSeek's changelog announced the discontinuation of the legacy name `deepseek-chat` for 2026-07-24; the API still accepted it and served `deepseek-flash`. Non-thinking mode is supported by the evidence: completion tokens per answer word median 1.44 (max 2.28), every `finish_reason` = `stop`, mean 1.8 s per call. Temperature 0, `max_tokens` 700, k = 6, prompt `answer-1`, up to 2 attempts (no repair attempt was needed).
- Retrieval identity: every row carries cache sha256 `c003e59f...`, the same cache as both Qwen runs; same 111 case ids; 0 endpoint errors, no `.failure.json`.
- Data sent to the provider: the prompt (question + retrieved passages) of the 75 model-called cases; 111,414 prompt tokens and 10,492 completion tokens in total (largest prompt 2,680 tokens).

### 10.2 Results against the pre-registered criteria (95% Wilson CI in the metrics files)

| Metric (criterion) | Qwen A (re-scored) | Qwen C (re-scored) | DeepSeek A | DeepSeek B1 (replay) | DeepSeek C (replay) |
|---|---|---|---|---|---|
| M1 correctness, all answerable (>= 0.70) | 40/72 = 0.56 | 51/72 = 0.71 | **68/72 = 0.94** (0.87-0.98) | 68/72 = 0.94 | 68/72 = 0.94 |
| M1 correctness, answered (>= 0.80) | 40/60 = 0.67 | 51/61 = 0.84 | **68/68 = 1.00** | 68/68 = 1.00 | 68/68 = 1.00 |
| M2 gold source cited (>= 0.85) | 57/60 = 0.95 | 58/61 = 0.95 | 67/68 = 0.99 | 68/68 = 1.00 | 68/68 = 1.00 |
| M2 citation precision (>= 0.70) | 0.90 | 0.89 | 0.94 | 0.93 | 0.94 |
| Citation coverage (no criterion) | 77/79 = 0.97 | 77/119 = 0.65 | 251/272 = 0.92 | 281/302 = 0.93 | 254/293 = 0.87 |
| M3 faithfulness, NLI (>= 0.90) | 49/79 = 0.62 | 74/119 = 0.62 | 176/272 = 0.65 | 193/302 = 0.64 | 179/293 = 0.61 |
| M4 hallucination, answer level (<= 0.10) | 23/60 = 0.38 | 26/61 = 0.43 | 41/68 = 0.60 | 45/68 = 0.66 | 47/68 = 0.69 |
| Hallucination, sentence level pooled | 0.38 | 0.38 | 0.35 | 0.36 | 0.39 |
| Fabricated numbers | 0/60 | 0/61 | 0/68 | 0/68 | 0/68 |
| M4 over-answering (<= 0.05) | 0/37 | 0/37 | 0/37 | 0/37 | 0/37 |
| M5 refusal recall (>= 0.95) | 37/37 | 37/37 | 37/37 = 1.00 | 37/37 | 37/37 |
| M5 false refusal (<= 0.20; NFR-AIQ <= 0.10) | 12/72 = 0.17 | 11/72 = 0.15 | **4/72 = 0.06** | 4/72 | 4/72 |
| M6 completeness, answered (>= 0.70) | 0.61 | 0.78 | 0.96 | 0.97 | 0.98 |
| M7 cited sentences entailed by their sources (>= 0.85) | 40/77 = 0.52 | 40/77 = 0.52 | 135/251 = 0.54 | 147/281 = 0.52 | 134/254 = 0.53 |
| M7 gold facts found in a cited source (>= 0.85) | 83/84 = 0.99 | 103/104 = 0.99 | 153/154 = 0.99 | 156/156 = 1.00 | 158/158 = 1.00 |
| Sentences removed by grounding | 74 | 26 | 72 | 13 | 24 |
| Mean seconds per model call | 112.7 | 238.9 | 1.8 | (replay) | (replay) |

**Verdict under the plan's rule (section 4 of the plan):** every non-NLI criterion passes, including correctness (M1), citation (M2), over-answering and refusal (M4/M5) and completeness (M6). The three NLI-judged criteria (M3 faithfulness, M4 answer-level hallucination, M7 cited-sentence entailment) fail. M3 and M4 are *critical*, so formally the run is **not "acceptable in practice"**, but that verdict rests entirely on the NLI judge, which the evidence below shows to be unreliable. The final verdict waits for judge validation (hand labels).

### 10.3 How far to trust the NLI numbers
- `root_cause`'s judge check (the same instrument that gave 24 of 30 for Qwen): **74 of the 84 sentences the judge calls unsupported are judge disagreements** (>= 80% of their content words found in the sources), 10 possibly unsupported. An independent check over the context-level verdicts gives the same picture (88 of 96 share >= 80% of their content words with the context, 73 share all). Most "hallucinations" are paraphrases the 140-word-window judge does not accept.
- Answer-level hallucination rises from 0.38 (Qwen) to 0.60 while the sentence-level rate is unchanged (0.38 -> 0.35): DeepSeek answers carry 4.0 substantive sentences per answer (272/68) against 1.3 for Qwen (79/60), so the same per-sentence false-positive rate compounds over more sentences. This is an artefact of the judge plus answer length, not evidence that DeepSeek invents more.
- 0 fabricated numbers and 0 over-answers in 68 answers are judge-independent and hold.

### 10.4 Failures and grounding behaviour
- The 4 answerable failures are all refusals. `root_cause` triage: **retrieval 3** — a04 and x01 (the gold page AOP1 p. 5 never reached the model; the model then correctly declined, INSUFFICIENT_CONTEXT; likely root the flattened-timeline ingestion defect F-COV-3) and x08 (gold in context, but the relevance policy refused before the model: "databases" missing from the hits); **model reasoning 1** — a53 (dense-math arXiv question, gold in context, model declined). None is recoverable by switching grounding off. No answered case is wrong (68/68).
- Policy A removed 72 sentences in 34 answerable cases (69 "no citation", 2 quotation not found, 1 low support). 17 of them start with a list marker and 16 are introductions ending in ":", which is the newline-splitting property of citation parsing (project_context section 7). **The grounding policy made no difference to correctness on this model** (A, B1 and C: 68/72 each); it changes only how much of each answer survives (coverage 0.92 / 0.93 / 0.87).

### 10.5 Limits
One run of one hosted model (temperature 0 is not bit-deterministic on hosted APIs; run-to-run variation not measured); the served model is `deepseek-flash`, whatever the requested name; same single-annotator lexical gold and unvalidated NLI judge as for Qwen; 111 cases (about +/-0.10 on proportions near 0.5, less near 0.95).

### 10.6 What the data supports next (no change made)
1. **Validate the judge** (hand labels, `evaluation/handlabel/`). It is now the only thing between this run and a verdict; the critical criteria cannot be decided without it.
2. **Grounding policy:** with a model that cites reliably, A costs nothing in correctness but trims list items and introductions; B1 keeps the most cited content (13 removals). The decision needs the validated judge (does B1 keep unsupported sentences?) and should then fix the newline/list citation property regardless of policy.
3. **Ingestion, not the model, is now the visible loss:** a04 and x01 (F-COV-3) fail because the gold page is never retrieved.
4. ~~Write `runs_2026-11/SHA256SUMS.txt` and run `root_cause`~~ (done 2026-11-23, see section 11).

## 11. Final evaluation summary (milestone closed 2026-11-23)

Scope: 111 cases (72 answerable, 37 refuse-expected), one retrieval cache (sha256 `c003e59f...`) for every run, so retrieval, prompt (`answer-1`), k = 6, temperature 0 and `max_tokens` 700 are identical and only the model and the grounding policy vary. Qwen numbers are the 2026-11-15 re-scores; B1/C runs replay recorded replies offline. Artifacts verified by `SHA256SUMS.txt` in `runs_2026-10/` (3 files) and `runs_2026-11/` (14 files).

### 11.1 Comparison

| | Qwen A | Qwen C | DeepSeek A | DeepSeek B1 | DeepSeek C |
|---|---|---|---|---|---|
| **Correctness** all answerable | 40/72 = 0.56 | 51/72 = 0.71 | **68/72 = 0.94** | 68/72 = 0.94 | 68/72 = 0.94 |
| Correctness of answered | 40/60 = 0.67 | 51/61 = 0.84 | 68/68 = 1.00 | 68/68 = 1.00 | 68/68 = 1.00 |
| Completeness of answered | 0.61 | 0.78 | 0.96 | 0.97 | 0.98 |
| **Refusal** recall (refuse-expected) | 37/37 | 37/37 | 37/37 | 37/37 | 37/37 |
| Over-answering | 0/37 | 0/37 | 0/37 | 0/37 | 0/37 |
| False refusal (answerable) | 12/72 = 0.17 | 11/72 = 0.15 | **4/72 = 0.06** | 4/72 | 4/72 |
| Refused as uncited | 7 | 6 | **0** | 0 | 0 |
| **Citation**: gold source cited | 57/60 = 0.95 | 58/61 = 0.95 | 67/68 = 0.99 | 68/68 = 1.00 | 68/68 = 1.00 |
| Citation precision | 0.90 | 0.89 | 0.94 | 0.93 | 0.94 |
| Citation coverage of sentences | 0.97 | 0.65 | 0.92 | 0.93 | 0.87 |
| Fabricated numbers | 0/60 | 0/61 | 0/68 | 0/68 | 0/68 |
| Sentences removed by grounding | 74 | 26 | 72 | 13 | 24 |
| NLI faithfulness / answer-level hallucination (judge unvalidated) | 0.62 / 0.38 | 0.62 / 0.43 | 0.65 / 0.60 | 0.64 / 0.66 | 0.61 / 0.69 |

### 11.2 Major failure categories (answerable cases)

| Category | Qwen A (32 failures) | DeepSeek A (4 failures) |
|---|---|---|
| Wrong answer although the gold source was in context | 19 | 0 |
| Refused because the model never cited (`uncited_answer`) | 7 | 0 |
| Model declined (INSUFFICIENT_CONTEXT) with gold in context | 3 (a27, a46, a53) | 1 (a53) |
| Gold source not retrieved (a04, x01; F-COV-3) | 2 | 2 |
| Refused by the relevance policy (x08) | 1 | 1 |

(Qwen per `metrics_qwen_rescored_20261115.json`: 19 wrong with gold in context, 1 wrong with gold not retrieved (a04), 7 uncited, 4 declined (incl. x01, gold not retrieved), 1 policy; regrouped here by stage.)

### 11.3 Retrieval is not the bottleneck
- The gold source was in the model's context for **70 of 72** answerable cases (0.97, CI 0.90-0.99); retrieval hit@5 on the labelled set is 0.96 with reranking (phase0_report).
- Retrieval-stage failures are **3 cases** (a04, x01: gold page not retrieved; x08: relevance-policy refusal), **the same 3 for both models** because retrieval is identical. They cap correctness at 69/72 = 0.96; DeepSeek reaches 68/72.
- The two missed retrievals trace to an ingestion defect (F-COV-3, flattened timeline on AOP1 p. 5), not to the embedding/ranking stage.

### 11.4 Model capability was the bottleneck
- On the **69 cases where retrieval delivered the gold source**, correctness is 40/69 (Qwen A), 51/69 (Qwen C) and **68/69** (DeepSeek A, B1 and C).
- Paired by case (A vs A): both correct 40, **DeepSeek only 28, Qwen only 0**, neither 4; exact McNemar test p = 7.5e-9. Every case Qwen answers correctly, DeepSeek also does.
- Qwen's losses are model behaviours that disappear with DeepSeek on the identical context: 19 wrong answers with the gold source in context, 7 answers refused for missing citations, placeholder answers ("a.c [1]", "This is stated in [1, 2, 3]").
- The grounding policy is a secondary factor whose size depends on the model: switching it off recovered 11 Qwen cases (A 40 -> C 51) and **0 DeepSeek cases** (68 in A, B1 and C).
- Caveats: one run per model; Qwen ran locally as a 4-bit 3B model, DeepSeek as a hosted model (`deepseek-flash`), so "model" includes size, quantisation and serving; lexical single-annotator gold.

### 11.5 What remains open
1. **NLI judge validation** (hand labels). It blocks the verdict on the critical criteria M3/M4: 74 of 84 DeepSeek sentences the judge rejects are judge disagreements.
2. **Grounding-policy decision** (A / B1 / C) and `min_support` calibration, after 1. With DeepSeek the choice affects how much of an answer survives, not correctness.
3. **Citation parsing splits at newlines**, removing list items and ":" introductions under policy A (33 of 72 DeepSeek removals). A stack fix independent of the policy decision.
4. **F-COV-3** (a04, x01) and the **x08** relevance-policy refusal: the only retrieval-stage losses.
5. Governing thresholds (plan vs NFR-AIQ) still formally open; DeepSeek's false refusal (0.06) passes both.
6. Run-to-run variation of a hosted model not measured; production model not chosen (DeepSeek is a stand-in; the planned OpenAI -> Gemma 3 27B path is untested).

## 12. Post-evaluation fix: list-aware citation parsing (2026-11-23, branch `post-eval-quality`)

**Defect.** `ai/answering/citations.parse` split replies at every newline and after every period, so (1) list items under an introduction cited once (`include [S5]:`) had no tag, (2) untagged `...:` introductions over cited items had no tag, (3) inline enumerations (`weaving: 1. A, 2. B`) were cut into fragments. Policy A removed them all as "no citation"; `render` then joined the survivors with spaces, flattening lists.

**Fix.** Untagged list items take the tags of their own item, else of the enclosing item or the introduction; untagged introductions take their items' tags; inherited tags are marked (`Sentence.inherited`) and go through the **unchanged** grounding check against the named source (tested: an inherited item about something else is removed for low support). No split after inline enumerators or `e.g. / i.e. / vs. / cf. / Fig. / Eq. / No. / al.`; answers keep their lines and paragraphs. Tests: 9 new, 800 pass.

**Measurement (*measured*, no API call).** Policy A/B1/C replayed with the fixed parser on the recorded DeepSeek replies; scored with the unchanged instruments. The replay harness was first shown to reproduce the live run exactly with the old parser (72 removals, 111/111 identical texts). Outputs: `evaluation/results/citefix_2026-11-23/` (with `SHA256SUMS.txt`). Qwen cannot be replayed (no raw replies).

| DeepSeek | A before | A after | B1 before | B1 after | C before | C after |
|---|---|---|---|---|---|---|
| Sentences removed by grounding | 72 | **34** | 13 | 13 | 24 | 5 |
| of which list items / ":" introductions | 17 / 16 | **1 / 4** | | 1 / 3 | | 0 / 0 |
| Substantive sentences in final answers | 272 | 366 | 302 | 388 | 293 | 396 |
| Correctness, all answerable | 68/72 | 68/72 | 68/72 | 68/72 | 68/72 | 68/72 |
| Completeness, answered | 0.958 | 0.966 | 0.973 | 0.973 | 0.984 | 0.984 |
| Gold source cited | 67/68 | **68/68** | 68/68 | 68/68 | 68/68 | 68/68 |
| Citation precision | 0.935 | 0.938 | 0.931 | 0.931 | 0.938 | 0.938 |
| Citation coverage (official instrument) | 0.923 | 0.872 | 0.930 | 0.876 | 0.867 | 0.821 |
| Citation coverage (splitter aligned with parser) | 251/253 = 0.992 | 319/326 = 0.979 | 0.993 | 0.980 | 0.937 | 0.915 |
| Cited sentences entailed by their sources (NLI) | 135/251 = 0.538 | **177/319 = 0.555** | 0.523 | 0.550 | 0.528 | 0.548 |
| Substantive sentences attributed (NLI) | 135/272 = 0.496 | 177/366 = 0.484 | 0.487 | 0.482 | 0.457 | 0.449 |
| Faithfulness, NLI sentence level | 0.647 | 0.656 | 0.639 | 0.657 | 0.611 | 0.639 |
| Hallucination, sentence / answer level (NLI) | 0.353 / 0.603 | 0.344 / 0.632 | 0.361 / 0.662 | 0.343 / 0.662 | 0.389 / 0.691 | 0.361 / 0.721 |
| Fabricated numbers | 0/68 | 0/68 | 0/68 | 0/68 | 0/68 | 0/68 |

**Reading.** Removals under the shipped policy halve (72 -> 34); 94 more substantive sentences reach the reader, 42 more of them attributed by the judge (135 -> 177), with a slightly higher entailment rate among cited sentences. The **official coverage drop is an instrument artifact**: `answer_sentences` splits after every period, so list numbers ("1.") and abbreviation fragments ("e.g.") count as uncited claims; they used to be deleted together with their content, now the content is kept. With a splitter aligned to the parser, coverage stays at about 0.98. Answer-level hallucination rises only because answers are longer (the sentence-level rate falls). The remaining 34 removals: 28 no citation (12 are code lines of one answer, a11: fenced code is still parsed line by line), 4 low support, 2 unmatched quotations.

**Effect on the policy decision.** With list-aware parsing, A removes 34 sentences against B1's 13 and C's 5; the gap that motivated B1 is now mostly code blocks and genuinely uncited prose.

## 13. F-COV-3 investigation: why a04 and x01 never retrieve AOP1 p. 5 (2026-11-23)

**Hypothesis tested.** F-COV-3 assumed that the flattened timeline graphic on AOP1 p. 5 hides the assessment facts. *Measured:* it does not. Ingestion keeps every fact ("Final Exam 40", "Lab Assignments 10", ...) in one intact 220-token chunk (`p. 5 > Assessment Criteria`); the timeline rows are noise at its top.

**Chunk-level scores** (BGE-small vector / MiniLM rerank; the current values reproduce x18's cached scores exactly; a hit needs to be in the 20-candidate vector pool and beat the 6th rerank score):

| Variant of the p. 5 chunk | a04 (6th rerank -3.30) | x01 (6th rerank -6.34) | x18 (6th rerank -11.19) |
|---|---|---|---|
| current | 0.642 / -9.52 | 0.618 / -6.82 | 0.686 / -5.11 |
| timeline rows removed | 0.659 / -8.80 | 0.606 / -7.31 | 0.671 / -4.10 |
| + document title prefix | 0.790 / **+3.20** | 0.720 / **+0.69** | 0.637 / -6.13 |
| file-name prefix (timeline kept) | 0.793 / **+3.01** | 0.727 / **+2.06** | 0.641 / -5.31 |

**Root cause.** The questions name the course ("the Aspect-Oriented course"); the chunk's only context is its heading. A document label is what the chunk lacks; the timeline is irrelevant.

**Smallest change tried: label in the reranker passage only** (no re-embedding; full 30-file index rebuilt in this environment, all 111 queries; `evaluation/results/fcov3_2026-11-23/`). The rebuilt index is equivalent to the pinned cache (gold-in-top-6 and assessment level identical for all 111 cases; 14 near-tie order swaps), but not bit-identical, so the pinned cache stays the reference.

| | pinned cache | rerank label = file name | rerank label = title, else file name |
|---|---|---|---|
| Gold source in top 6 (answerable) | 70/72 | 71/72 (+x01) | 71/72 (+x01) |
| Answerable refused by the relevance policy | 1 (x08) | 1 (x18 newly; x08 unblocked) | 2 (x18, x11 newly; x08 unblocked) |
| Not-answerable cases refused before the model | 35/39 | **32/39** (n09, n10, x15 now pass) | 32/39 |
| a04 | gold not retrieved | still not retrieved (chunk outside the vector pool) | same |

The reranker-only label is **not acceptable as is**: it trades x01/x08 for x18 (a case DeepSeek answers correctly today) and weakens the calibrated pre-model refusal, whose thresholds were fitted to unlabelled passages.

**Expected gain of the full fix** (label in the embedded text and the reranker passage, re-embedded corpus, recalibrated relevance policy, new retrieval cache): at most **+2 answerable cases** (a04, x01), i.e. DeepSeek about 68/72 -> 70/72 (0.94 -> 0.97); x08 may also be unblocked by recalibration. This is within the benchmark's noise, and it ends the identical-retrieval comparison with the Qwen runs unless Qwen is re-run. Label quality is a real problem: of the 28 retrieved files, 4 are titled "PowerPoint Presentation", 7 have no title, AOP lecture 2 and Sections 02-03 carry copied titles, and several file names are meaningless (`hard_PDF_1`, `sample-long`). **Not implemented**; recorded as a decision (project_context section 8, item 15c).
