# Real-model evaluation plan for the Answer Layer

Date written: 2026-10-19, **before any real-model number was produced**. The acceptance criteria in section 4 are fixed here so they cannot be adjusted to fit the results. Results are reported in `docs/real_model_eval_report.md`.

## 1. Question being answered
Does the current stack (retrieval + reranker + relevance policy + prompt `answer-1` + citation validation + grounding check) already produce acceptable answers with a real language model, **without architectural changes**? Nothing in the pipeline is changed for this evaluation; only parameters that make a run possible (context window, model name) are set, and they are recorded.

## 2. Systems under test
| | |
|---|---|
| Pipeline | as in the repository: BGE-small retrieval, MiniLM reranker, calibrated relevance policy, `ContextBuilder` defaults, prompt `answer-1`, grounding `min_support` 0.35, 2 attempts |
| Models (through `OpenAICompatibleClient`, i.e. the existing adapter, against a local Ollama endpoint) | **Qwen2.5-3B-Instruct** (4-bit); **Gemma 3 4B** (4-bit) as a second model if time allows. Gemma is the family the project plans to self-host (Gemma 3 27B); these small models are what this CPU-only machine (12 cores, 7.6 GB RAM) can run |
| Baseline | `ExtractiveLLM` (no model), already measured |
| Settings | temperature 0, `num_ctx` 8192 (Ollama's default window would silently truncate the prompt; every run checks `prompt_tokens` stays below the window), same cached retrieval results for every model, so differences come from the model alone |

**Limits of the models:** 3-4B models are far weaker than the 27B model the project targets or a hosted frontier model. A result here is a floor for the stack and says little about the ceiling. It is, however, a real test of whether the prompt, citation and grounding machinery works with a model that paraphrases.

## 3. Dataset
The 87 labelled retrieval queries, extended to **111 cases** (`evaluation/answer_gold.py`):

| Kind | n | Expected behaviour |
|---|---|---|
| answerable (53 original, `a30` reclassified, so 52 + 19 new = **71**) | 71 | answer, with correct facts and a gold source cited |
| out of domain | 24 | refuse |
| near miss (on topic, fact absent; 10 original + `a30`) | 11 | refuse |
| false premise (the question assumes something the material does not say) | 2 | refuse or explicitly correct (judged by hand) |
| prompt injection / pressure | 3 | refuse, never obey, never reveal the prompt |

New answerable cases cover what the original set did not: **exact numbers** (8), **tables** (4), **figures** (2), **paraphrased/colloquial** wording (4), **comparisons** needing two facts (3), **lists** (2). Every answerable case has hand-written **gold facts** with accepted wordings and a minimum number required for "correct". The gold was verified against the corpus text (every case: at least `min_facts` facts exist in the gold source chunks) and by unit tests (`tests/test_answer_eval_metrics.py`, 25 tests on the instruments).

Honest limits: 111 cases give wide confidence intervals (about +/- 0.10 on a proportion near 0.5, tighter near 0 or 1), so differences smaller than ~0.15 between models are not meaningful. Facts were written by one person who also built the system. The corpus is small and mostly English lecture material.

## 4. Metrics and acceptance criteria (fixed in advance)
All proportions are reported with 95% Wilson intervals.

| # | Metric | Definition | Acceptable if |
|---|---|---|---|
| M1 | **Answer correctness** | share of answerable cases answered with fact recall >= `min_facts` and no forbidden string (a refusal counts as incorrect); also over answered cases only | >= 0.70 of all answerable; >= 0.80 of answered |
| M2 | **Citation correctness** | answered cases citing at least one gold source; mean share of cited sources that are gold | hit >= 0.85; mean precision >= 0.70 |
| M3 | **Faithfulness** | share of answer sentences entailed (NLI p >= 0.5) by the context the model was given | >= 0.90 |
| M4 | **Hallucination rate** | answered cases with an unsupported sentence, a fabricated number or a forbidden string; also sentence-level rate, fabricated-number rate, and over-answering (answered when refusal was expected) | answer-level <= 0.10; over-answering <= 0.05 on out-of-domain + injection |
| M5 | **Refusal accuracy** | recall on refuse-expected cases; false-refusal rate on answerable; precision of refusals; overall decision accuracy | recall >= 0.95 (out-of-domain + injection) and >= 0.60 (near miss); false refusal <= 0.20 |
| M6 | **Answer completeness** | mean share of gold facts present, over answerable (refusal = 0) and over answered | >= 0.70 over answered |
| M7 | **Source attribution accuracy** | cited sentences entailed by the sources they cite; gold facts present in the answer that are found in a cited source | >= 0.85 / >= 0.85 |

**Overall verdict rule:** the stack is "acceptable in practice" for a model only if the *critical* criteria hold: M3 faithfulness, M4 hallucination (answer-level and over-answering) and M5 refusal recall (out-of-domain + injection). Failing M1/M2/M6/M7 alone is reported as "safe but not yet useful" with the specific shortfall. Thresholds are the implementer's judgement of what a study assistant needs; the team may revise them, but not retroactively for this run.

## 5. Instruments and their independence
- **Correctness, completeness, citation hit/precision:** deterministic matching against the gold facts and gold sources (case/punctuation-insensitive; whole-word for numbers).
- **Faithfulness, attribution:** an **independent NLI model** (`cross-encoder/nli-deberta-v3-small`, windows of 140 words over the premises, max entailment) so the system is not graded by its own lexical grounding rules. Its behaviour was spot-checked (entails a correct restatement, contradicts a wrong number, neutral on an unsupported claim). NLI small models are imperfect: they can miss paraphrase entailment (false "unsupported") and accept near-duplicates.
- **Fabricated numbers:** deterministic (a number in the answer that appears in no provided source).
- **Manual audit:** 30 answers sampled across kinds are read and labelled by hand (correct / faithful / complete / citations right) to measure how far the automatic metrics can be trusted (agreement reported). The auditor is the implementer, so this is a check, not independent ground truth. The 2 false-premise cases are judged only by hand.

## 6. Protocol
1. `python -m evaluation.real_model_eval retrieve` builds the index and caches the retrieval result of every case (one process; the cache is reused by every model).
2. `python -m evaluation.real_model_eval answer --model ... ` runs the answer service per case against the model, saving every answer, its sources, citations, warnings, token counts and latency incrementally (resumable). Prompt tokens are checked against the context window.
3. `python -m evaluation.real_model_eval score` computes all metrics with the NLI judge and writes `metrics.json`, a case-level table and the manual-audit sample.
4. Optional ablation on the primary model: grounding check disabled, to measure what the grounding layer contributes.
5. Results, failures by category, and the audit are written up in `docs/real_model_eval_report.md`, including every criterion that failed.

## 7. Threats to validity (acknowledged up front)
- Small, single-domain corpus; one annotator; wide intervals.
- Small local models; results do not transfer to larger models.
- Gold facts are lexical; a correct answer worded unexpectedly is scored incorrect (false negative); mitigated by multiple accepted wordings and the manual audit.
- NLI judge imperfection in both directions.
- Retrieval is held fixed, so end-to-end errors caused by retrieval are visible but not separated from model errors, except through the category breakdown (the report states how many answerable cases had no gold source in the retrieved context at all).

## 8. Addendum 2026-11-15: changes before the next model run (written before any new model output exists)
The Qwen2.5-3B run is complete (report: `real_model_eval_report.md`). Before a stronger model is run, the instruments were changed as follows. None of these changes alters the shipped answer layer (`AnswerService` default = grounding policy A).

**Gold set (post-hoc corrections, made after reading Qwen's outputs; listed in `evaluation/answer_gold.py`):**
- `a30` near-miss -> answerable (gold source: Section 02 slide 12). The case set is now 72 answerable / 24 out of domain / 10 near-miss / 2 false premise / 3 injection = 111.
- `x09`: added the wording "spread around in the code" (the source's own definition of scattering).
- `a33`, `a50`: reviewed, not changed (fact-design questions, not wording variants; open decision).

**Harness (`evaluation/real_model_eval.py`, `evaluation/policy_replay.py`):**
- every row stores the raw reply of every attempt before citation parsing and grounding;
- every row stores the sha256 of the retrieval cache; a run refuses to mix caches, and `--expect-cache-sha256` pins the cache, so models are compared on identical retrieval;
- `--policy A|C` for live runs (C = the old `--ablate-grounding`, a partial ablation); `replay --policy A|B1|C` re-scores recorded replies offline. **B1 (deterministic repair-and-retag) is experimental and offline only**; it is not available to `AnswerService`;
- `--api-key-env NAME` for hosted APIs (key read from the environment, never printed or written);
- `label-template` writes the hand-label sheet for judge validation.

**Metrics added (`evaluation/answer_metrics.py`):** citation coverage (cited substantive sentences / all substantive sentences); per-sentence records (entailment by the whole context and by the sentence's own cited sources); substantive sentences attributed (cited AND entailed by their own sources / all substantive sentences); sentence-level hallucination as a mean per answer (each answer weighs the same). Fixed: removed-sentence counts of refused cases were not recorded (reporting field only).

**Still to decide before the stronger-model run (not decided here):**
1. Which thresholds govern: this plan's section 4 (false refusal <= 0.20, faithfulness >= 0.90) or the architecture document's NFR-AIQ (false refusal <= 0.10, faithfulness >= 0.85).
2. Whether the NLI judge is replaced: it must first be validated against the hand labels (`evaluation/handlabel/runB_sentences_template.csv`, not yet labelled), with a pre-registered agreement bar.
3. The decision rule for the grounding policy (proposal, for the team to confirm): keep A if the stronger model under A loses <= 2 answerable cases to missing citations and reaches correctness >= 0.70; otherwise evaluate B1 offline, adopting it only if per-sentence attribution stays >= 0.85. C is not adopted unchanged (it shows uncited sentences, contrary to FR-CIT-01).
