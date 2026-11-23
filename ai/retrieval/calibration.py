"""The retrieval policy in force, with the evidence it was calibrated on.

Regenerate the evidence with ``python -m evaluation.retrieval_eval --strategy all --calibrate`` (needs the
index from ``python -m evaluation.index_builder``). The numbers are valid only for the models named in the
policy; the service ignores them (and says so in ``result.warnings``) when a different embedder or reranker
is configured, because cosine and cross-encoder scores are not comparable across models.

Calibration set: 87 hand-labelled queries over 30 files (53 answerable, 24 unrelated, 10 near-miss),
measured 2026-10-18, chunker 1.1.0. Two-fold cross-validation on query ids:

    vector only  unrelated max 0.59 vs answerable min 0.57 (they overlap) -> accept at 0.59;
                 answerable passed 0.88-0.96, unrelated refused 100%, near-miss refused 0-40%
    + reranker   unrelated max -6.33 vs answerable min -5.31 (clean gap) -> accept at the midpoint -5.8;
                 answerable passed 96-100%, unrelated refused 100%, near-miss refused 40-60%;
                 "strong" precision 0.89-0.96 (strong = correct chunk within the top 3)

Judgement calls: the reranker accept threshold is the midpoint of the gap, not the fitted edge; the vector coverage
floor 0.34 was preferred over the fitted 0.0 because it generalised in cross-validation. Near-miss questions
(on-topic, fact absent) are only partly refused here, so the answer layer must still verify support. With 87
queries these are coarse estimates, not guarantees.
"""

from __future__ import annotations

from ai.retrieval.assessment import RetrievalPolicy
from ai.retrieval.rerank import DEFAULT_RERANKER_MODEL

DEFAULT_POLICY = RetrievalPolicy(
    version="2026-10-18-bge-small-minilm-l6",
    strong_vector=0.76,
    weak_vector=0.59,
    strong_rerank=2.8,
    weak_rerank=-5.8,
    min_coverage_vector=0.34,
    min_coverage_rerank=0.5,
    embedding_model="BAAI/bge-small-en-v1.5",
    reranker_model=DEFAULT_RERANKER_MODEL,
)
