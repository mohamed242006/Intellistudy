# Hand-label validation of the NLI judge (template; NOT completed)

**Status (2026-11-15): template generated, no sentence has been labelled.** Until it is filled in, faithfulness,
hallucination and attribution numbers from `evaluation/answer_metrics.py` are not validated.

## Why
The real-model evaluation grades faithfulness with `cross-encoder/nli-deberta-v3-small`. In the Qwen2.5-3B run, 24 of
the 30 sentences it rejected share at least 80% of their content words with the sources, so the judge looks too strict.
Hand labels tell us how far to trust it, and whether a candidate replacement judge is better.

## The file
`runB_sentences_template.csv` (UTF-8 with BOM, opens in Excel): one row per substantive sentence of every answered case
of the Qwen run B (`evaluation/results/runs_2026-10/run_qwen_noground.jsonl`); the same sentences the judge scores.
Regenerate with:

```
python -m evaluation.real_model_eval label-template --run evaluation/results/runs_2026-10/run_qwen_noground.jsonl --cases evaluation/results/cases_qwen_noground_rescored_20261115.json --out evaluation/handlabel/runB_sentences_template.csv
```

Columns given: `sentence_id`, `case_id`, `kind`, `query`, `sentence`, `citation_numbers` (empty = the sentence carries
no citation), `cited_locations`, `cited_source_text` (text + wider section of the cited sources), `all_context_excerpt`
(every source the model saw, truncated), `nli_entailed_by_context` (the judge's verdict: yes/no).
Columns to fill: `human_label`, `human_notes`, `labeller`, `labelled_on`.

## How to label
Judge the sentence against `all_context_excerpt` (open the source file when the excerpt is truncated). Do not look at
`nli_entailed_by_context` before deciding (hide the column).

| `human_label` | Meaning |
|---|---|
| `supported` | Every claim in the sentence is stated in, or follows directly from, the sources. Paraphrase is fine. |
| `partial` | Some claims are supported, at least one is not. |
| `unsupported` | The main claim is not in the sources (outside knowledge, wrong, or invented). |
| `unclear` | Cannot decide (garbled sentence, source text unreadable). Explain in `human_notes`. |

Add a second label in `human_notes` when the sentence is supported by the context but **not by the source it cites**
(write `misattributed`): this is what per-sentence attribution measures.

Recommended: two people label independently (different `labeller`), then resolve disagreements; report their raw
agreement before resolution.

## How the result is used
- Judge agreement = share of rows where the judge's yes/no matches `supported` vs (`partial` or `unsupported`);
  report `unclear` separately.
- Pre-register the acceptance bar before computing it (proposal: >= 0.85 agreement), see
  `docs/real_model_eval_plan.md` section 8.
- A replacement judge is accepted only if it beats the current one on these labels.
