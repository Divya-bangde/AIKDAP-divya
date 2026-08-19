# Relevance gate calibration (Sprint 9F)

How `RERANKER_RELEVANCE_THRESHOLD` was measured, and what it costs.

## Why a gate exists

BGE-Reranker-v2-m3 orders candidates; it does not decide whether any of
them are relevant. Asked for the top 5 chunks it returns 5, whatever the
question. Before this gate, *"What is the capital of Japan?"* retrieved
five poultry chunks at cosine similarity ~0.24, and the only thing
preventing a fabricated answer was the grounding prompt — a request to
the model, not a guarantee from the backend.

## Why the threshold could not be guessed

The model emits an unbounded logit, not a probability. On this corpus
the observed range is roughly `[-11, +10]`, and relevant pairs are
frequently negative. `0.0`, `0.5`, and "positive means relevant" are all
meaningless for it. The value had to be measured.

## Method

The real stack — BGE-M3 → pgvector → BGE-Reranker-v2-m3 under
llama.cpp — scored every chunk in the project corpus against every
query. Nothing was mocked.

- **Corpus**: 7 chunks (the ABC Poultry FY2025 review plus six
  single-sentence documents).
- **Queries**: 5 answerable from the corpus, 5 not.
- **Pairs**: 70. **Relevant: 11. Irrelevant: 59.**
- **Labels**: assigned from document *content* — a chunk is relevant to
  a query only if it actually contains information answering it —
  never from the score being measured.

Raw data: `backend/tests/fixtures_relevance_calibration.json`.

## Score distribution

| | n | min | max | mean | median |
|---|---|---|---|---|---|
| Relevant | 11 | −10.759 | +10.272 | +2.296 | +3.262 |
| Irrelevant | 59 | −11.048 | +2.133 | −8.156 | −10.072 |

**The distributions overlap**, across `[−10.759 .. +2.133]`, with 39 of
70 pairs inside that band. There is no perfect separator, and this is a
filter rather than a classifier. Per query, however, separation is
usually clean — the overlap is mostly driven by two queries (see
*Known costs*).

## Candidate thresholds

| threshold | TP | FN | FP | TN | precision | recall | FPR | FNR |
|---|---|---|---|---|---|---|---|---|
| −4.0 | 9 | 2 | 12 | 47 | 0.429 | 0.818 | 0.203 | 0.182 |
| −3.0 | 9 | 2 | 8 | 51 | 0.529 | 0.818 | 0.136 | 0.182 |
| **−2.0** | **9** | **2** | **2** | **57** | **0.818** | **0.818** | **0.034** | **0.182** |
| −1.0 | 8 | 3 | 2 | 57 | 0.800 | 0.727 | 0.034 | 0.273 |
| 0.0 | 6 | 5 | 2 | 57 | 0.750 | 0.545 | 0.034 | 0.455 |
| +2.5 | 6 | 5 | 0 | 59 | 1.000 | 0.545 | 0.017 | 0.455 |

## Selected: −2.0

Chosen because it is the point where precision rises steeply (0.529 →
0.818 between −3.0 and −2.0) while recall is still at its maximum
plateau, and because of what it does per query rather than in aggregate:

- **Every one of the 5 in-corpus queries keeps at least one genuinely
  relevant chunk**, and every chunk it accepts for those queries is
  truly relevant.
- **4 of the 5 out-of-corpus queries drop to zero accepted evidence**,
  so no synthesis call is made at all for them.

A precision-weighted F0.5 score technically peaks higher at **+2.25**
(precision 1.000, recall 0.545). That threshold was rejected: it
reduces *"What factors may affect future growth?"* — a question the
corpus does answer — to zero evidence, turning a correct answer into a
false "insufficient evidence". Maximising a metric at the cost of
answering real questions is the wrong trade for this system.

## Known costs at −2.0

**Two false positives**, both on *"What was ABC Poultry's exact net
profit in FY2025?"*:

| score | chunk |
|---|---|
| +2.133 | `abc_poultry_fy2025_review.txt` |
| +0.954 | `sprint9d_A_production.txt` |

These are defensible: both documents genuinely are about ABC Poultry's
FY2025 finances, they simply do not state a profit figure. The gate is a
relevance filter, not an answerability oracle. Grounded synthesis
handles the remainder correctly — it returns `insufficient_evidence`
rather than inventing a number.

**Two false negatives:**

| score | chunk | query |
|---|---|---|
| −5.435 | `sprint9d_D_biosecurity.txt` | What challenges does ABC Poultry face? |
| −10.759 | `sprint9d_F_expansion.txt` | What factors may affect future growth? |

Neither loses an answer: both queries retain other chunks covering the
same facts. The first is a reranker-quality issue, not a threshold one —
the model scores the biosecurity chunk *below* an irrelevant location
chunk for that query, so no threshold recovers it without admitting the
irrelevant one too.

## When to recalibrate

This number is specific to this corpus and this reranker. Re-run the
calibration if the corpus changes materially in size or subject, or if
the reranker model or its serving runtime changes. It is configuration,
not a constant: `RERANKER_RELEVANCE_THRESHOLD`.
