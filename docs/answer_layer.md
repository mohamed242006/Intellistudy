# Answer Layer MVP, E2E-08 and the FigureDescriber plug-in point

> **STATUS: HISTORICAL (superseded in part, banner added 2026-11-15).** Kept as the design and guarantee record of the
> answer-layer MVP (2026-10-19); the text below is unchanged. The current single source of truth is
> [`project_context.md`](project_context.md). Outdated here:
> - **Real-model evaluation status** ("No real LLM was evaluated", §6 and the intro): Qwen2.5-3B was evaluated on 111
>   cases on 2026-10-25; the pre-registered criteria were not met - project_context.md §11 and
>   [`real_model_eval_report.md`](real_model_eval_report.md).
> - **Answer-layer status**: still an MVP (no HTTP endpoint, multi-turn history, streaming, rate limits or cost
>   accounting); the grounding policy is undecided after the real-model run - project_context.md §3.10, §7, §11.
> - **Grounding thresholds** ("provisional, exercised only with an extractive generator", §6): exercised on one real
>   model; the citation rule removed supported content - project_context.md §11.
> - Still current: chunk ids `c-{hash12}` / `p-{hash12}` (§1, chunker 1.3.0); schema 2.1; the FigureDescriber
>   plug-in point with no vision model (§3); the reranker as described.

Date: 2026-10-19 · Scope: the three items requested after Phase 0. **No Vision LLM was added** and **no real language model was available**, so nothing in this document measures the quality of a language model's writing (see section 6).

---

## 1. E2E-08: chunk ids are stable across file edits (fixed)

**Before:** a chunk id was `{file hash}-{position}-{text hash}`, so editing a file renamed every chunk (0% of ids survived on six real edits), even though vectors were reused. Enrichment (generated figure descriptions) would have made this much worse.
**Now (chunker 1.3.0):** `c-{hash12 of the chunk's own text}` (plus `.{n}` for the n-th later chunk with identical text in the same document); parents are `p-{hash12}`. The id depends on the chunk's text only: not on its position, not on the file hash. `vector_id` still adds the `document_uid`, so ids from different documents never clash.

| Real edit (one sentence added, last page/paragraph removed) | chunks | ids surviving |
|---|---|---|
| `sample-files.com-large-document.docx` | 97 -> 96 | 98% |
| `hard_PDF_3.pdf` | 19 -> 17 | 68% |
| `hard_PDF_5.pdf` | 52 -> 49 | 77% |

PDFs keep fewer ids because added text shifts chunk boundaries across pages. Re-indexing an edited file now touches only changed chunks: unchanged ones keep id and vector (their stored metadata is refreshed because it names the new file hash), only edited chunks are embedded and only their old versions deleted (tested end to end in `tests/test_e2e_findings.py::E2E08ChunkIdStabilityTests`). Four older tests that encoded the old behaviour ("inserting a section shifts ids") were rewritten to the new behaviour. Existing stores re-ingest cleanly: old ids are stale and removed, vectors are reused by `embedding_hash`.

## 2. The Answer Layer (`ai/answering/`)

```
question -> RetrievalService (scoped to user + course, reranker, relevance policy)
         -> refusal pre-check   --none/no hits--> refuse (model is NOT called)
         -> ContextBuilder      numbered sources S1..Sn under a token budget
         -> PromptBuilder       rules + fenced sources + question  (PROMPT_VERSION answer-1)
         -> LLMClient           OpenAI-compatible HTTP / extractive baseline / scripted
         -> citations.parse     [S#] tags validated against the offered sources
         -> grounding.check     per sentence: cited? words, numbers, quotes supported?
         -> Answer(text with [n] citations) or a refusal with a stated reason
```

| Component | File | What it does |
|---|---|---|
| LLM Adapter | `llm.py` | `LLMClient` protocol; `OpenAICompatibleClient` (stdlib HTTP, retries 408/429/5xx with backoff, never logs keys; works with OpenAI, vLLM, Ollama, LM Studio, i.e. also a self-hosted Gemma/Qwen); `ExtractiveLLM` (deterministic no-model baseline that quotes sources); `ScriptedLLM` (tests) |
| Context Builder | `context.py` | tags hits `S1..Sn` in rank order, de-duplicates identical passages, keeps the best hit and drops lower ones over budget, attaches the wider section for the top sources when small, flags generated text and low-confidence OCR |
| Prompt Builder | `prompt.py` | fixed, versioned rules: answer only from sources, cite every claim, `INSUFFICIENT_CONTEXT` when unsupported, sources are untrusted data; fence and `[S#]` tags inside source text are neutralised; caution and repair notes |
| Citation Injection | `citations.py` | parses `[S1]`, `[S1, S2]`, `x. [S1]`; invalid tags are removed and reported; reader-facing `[1]` numbers follow first use |
| Hallucination Prevention | `grounding.py` | each substantive sentence must cite an offered source; its content words, every number and every quoted string must be found in the cited sources; failing sentences are removed, never rewritten |
| Refusal Logic | `refusal.py` | pre-check from the relevance assessment (nothing retrieved / judged unrelated: no model call), caution on weak matches, user-facing messages that name the missing words and the closest material |
| Answer Service | `service.py` | orchestrates the flow, one repair attempt, records model, prompt version, token usage and warnings |

### Guarantees (each has tests in `tests/test_answering.py`)
- Retrieval is scoped to one user and course; another user's text never reaches the prompt.
- An answer is returned only if at least one sentence cites an offered source and passes grounding; otherwise it is a refusal with a reason: `no_results`, `not_relevant`, `model_declined`, `uncited_answer`, `unsupported_claims`, `llm_unavailable`.
- Unrelated questions are refused before the model is called.
- A model outage is a refusal, not an exception.
- Instructions hidden in a document cannot close the source fence or impersonate a citation.
- Answers that rest on AI-generated figure text are flagged (`contains_generated_text`) and the prompt tells the model to hedge and not to take numbers from it.

### Using it
```python
from ai.answering import AnswerService, OpenAICompatibleClient, ExtractiveLLM
llm = OpenAICompatibleClient("gpt-4o-mini")                       # key from OPENAI_API_KEY
# self-hosted:  OpenAICompatibleClient("qwen2.5-7b-instruct", base_url="http://localhost:8000/v1", api_key="x")
# no model:     ExtractiveLLM()
service = AnswerService(retrieval_service, llm)                    # retrieval_service built with a reranker
answer = service.answer("What is a pointcut?", user_id="u1", course_id="c1")
answer.text, answer.citations, answer.refused, answer.refusal_reason, answer.to_dict()
```
Not included in the MVP: multi-turn history, streaming, an HTTP endpoint, per-user rate limits and cost accounting beyond the recorded token counts.

## 3. FigureDescriber plug-in point (`ai/ingestion/figure_description.py`)
A future vision model plugs in without touching the pipeline:
- implement `FigureDescriber.describe(crop, context) -> FigureDescription` (`context` carries only the author's caption, text in the figure and citing sentences);
- `PdfFigureCropper` renders a figure's box from a PDF page (PPTX/DOCX croppers are future work: those figures are skipped, not failed);
- `enrich_figures(document, describer, cropper, cache=...)` fills `FigureData.description` and `description_status`, never overwriting source text;
- safety rules enforced for any model: numbers in a description must appear in the author's own text or the description is rejected as a `conflict`; empty/boilerplate descriptions are rejected; results are cached by `image sha256 + model + prompt version`; one failing figure never stops the rest;
- the chunker already renders a described figure with a labelled `Generated description (AI-generated, may contain errors)` line; because ids depend on text only, re-chunking after enrichment renames **only the figure chunks** (tested);
- `NullFigureDescriber` (default, does nothing) and `StubFigureDescriber` (tests) ship; no real describer was added.

**Adoption gate (unchanged):** a Qwen2.5-VL or other describer is adopted only if, on the existing figure benchmark and on real figure-heavy documents, it clearly improves retrieval and answer quality over the Phase 0 baseline, with description accuracy checked against the synthetic corpus's exact data and acceptable cost/latency. The answer layer is ready to be the judge of "answer quality" once a real LLM is connected.

## 4. Evaluation (`python -m evaluation.answer_eval`)
Generator: **`ExtractiveLLM`** (quotes source sentences; no language model). 87 labelled queries over 30 files, reranker and calibrated relevance policy on, 2026-10-19:

| Query kind | n | Result |
|---|---|---|
| unrelated to the corpus | 24 | 24 refused, all **before any model call** |
| on-topic but the fact is absent (near-miss) | 10 | 9 refused (6 by retrieval as not relevant, 3 declined by the generator); 1 answered with an irrelevant intro sentence |
| answerable | 53 | 45 answered (84.9%); 8 declined by the generator; **37 of the 53 (69.8%) cite the expected source** (82% of the answered ones) |

Reading it correctly:
- The refusal side works as designed: unrelated questions never reach a model, and no unrelated question was answered.
- The answer-quality side measures the *baseline*, not a language model. Its misses are what an extractive method cannot do (it quotes one sentence, so questions needing a definition split over sentences are declined or answered from the wrong passage). A real model should beat it clearly on answerable questions; if it does not, something is wrong.
- The grounding check removed 0 sentences here because quoted sentences are trivially grounded. It is exercised by unit tests with scripted replies, not by this run.
- Mean 2.3 s per query, dominated by reranking on CPU; 0.66 model calls per query (refusals cost none).


## 5. Findings from building it
- **Bug found by the end-to-end run:** a table-of-contents line full of dot leaders produced an answer made of orphan "." sentences. Fixed in two places (the citation parser ignores sentences without letters or digits; the extractive baseline skips leader/ToC lines) and covered by tests. It also shows that **table-of-contents pages are indexed and can outrank real content** for headings that appear in them: a retrieval-side finding to handle (down-rank or exclude ToC chunks), not fixed here.
- Chroma persistence: an index built by one process could not be re-opened by another on this machine (HNSW files missing); the evaluation therefore builds and queries in one process (`--rebuild`). Cloud-sync folders (OneDrive) also lock Chroma segment files; keep indexes outside the synced tree.

## 6. Limits (stated plainly)
- **No real LLM was evaluated.** The only generator measured is the extractive baseline, which cannot paraphrase or combine facts. The harness runs a real model with `--llm openai` (or `--base-url` for a local server) once one is available.
- The grounding thresholds are lexical and provisional (`min_support` 0.35); they must be calibrated on a real model's paraphrased answers. Too strict removes good sentences; too lax lets unsupported ones through.
- Refusal quality for near-miss questions (on-topic, fact absent) depends on the model and grounding, not on retrieval alone.
- Prompt injection is reduced (fencing, neutralised tags, explicit rules, validation of citations), not eliminated: a model can still be persuaded by text it reads. Nothing here lets such text change which sources are cited or bypass grounding.
- Multilingual behaviour (Arabic) is untested; the embedder and the OCR are English-only.
