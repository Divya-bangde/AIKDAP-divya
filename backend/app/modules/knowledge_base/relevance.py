"""The relevance gate: stage 3 of retrieval (Sprint 9F).

Stage 1 (BGE-M3 + pgvector) finds candidates, stage 2
(BGE-Reranker-v2-m3) orders them, and this decides which of them are
relevant *at all*. Ordering and relevance are different questions: a
reranker asked for the top 5 chunks always returns 5, however poorly
they match — for "What is the capital of Japan?" it returns five
poultry chunks, correctly ordered and entirely useless.

Without this gate those chunks reach the synthesis model, and the only
thing standing between them and a fabricated answer is the grounding
prompt. That is a request, not a guarantee. The gate makes it a
guarantee: evidence below the threshold never enters the context, so
it cannot be cited even if the model tries.

## Calibrated, not guessed

The threshold is an empirical value measured against this deployment's
own corpus, not a round number. BGE-Reranker-v2-m3 emits an unbounded
logit, so no fixed constant (0.0, 0.5, "positive means relevant") has
any meaning for it; the observed range on this corpus is roughly
[-11, +10] with relevant pairs by no means always positive.

`docs/relevance-calibration.md` records the measurement: 70
(query, chunk) pairs over 5 in-corpus and 5 out-of-corpus queries,
labelled from document content. At the selected threshold of -2.0,
precision was 0.818 and recall 0.818 on that fixture, with 4 of the 5
out-of-corpus queries reduced to zero evidence.

The distributions overlap — this is a filter, not a classifier, and it
is calibrated to prefer rejecting borderline evidence over admitting
it. Recalibrate when the corpus changes materially.

## Scores are never transformed

The gate compares the raw `rerank_score` against the raw threshold.
Nothing is normalized into a 0-1 "confidence", because that mapping
would be invented rather than measured, and it would put a
scientific-looking number on a guess. The API keeps exposing the
model's own score.
"""

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.core.config import settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

#: The gate works on anything carrying a score; the knowledge base
#: passes `RetrievalHit`s and the tests pass simple stand-ins. Keeping
#: it generic avoids importing the service layer into this module and
#: keeps the dependency pointing one way.
ItemT = TypeVar("ItemT")


@dataclass(frozen=True)
class GateDecision(Generic[ItemT]):
    """What the gate did, in enough detail to explain any single result.

    Rejected items are *kept* here rather than discarded. They must not
    reach the synthesis model, but silently vanishing evidence is
    undebuggable — a caller needs to be able to answer "why was there
    no answer?" with "these five chunks were retrieved and all scored
    below the threshold", not with a shrug.
    """

    accepted: list[ItemT]
    rejected: list[ItemT]
    #: The threshold actually applied, or `None` when the gate did not
    #: run (no rerank scores to compare against).
    threshold: float | None
    #: False when scoring was unavailable, so the caller can tell
    #: "everything passed" from "nothing was checked".
    applied: bool

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


class RelevanceGate:
    """Filters reranked evidence by its cross-encoder score.

    Deliberately tiny and deliberately dumb: one comparison per item.
    Anything cleverer (a learned classifier, an LLM judge, a
    normalization curve) would be a second model to calibrate, monitor
    and explain, and this sprint's requirement is a *backend-enforced*
    guarantee — which is worth more when the rule is one line anyone
    can reason about.
    """

    def __init__(self, *, threshold: float | None = None) -> None:
        # Read from settings at construction, never hardcoded, so the
        # threshold is tunable without a code change.
        self._threshold = (
            threshold if threshold is not None else settings.reranker_relevance_threshold
        )

    @property
    def threshold(self) -> float:
        """The score an item must reach, inclusive, to be accepted."""
        return self._threshold

    def apply(
        self, items: list[ItemT], *, scores: list[float | None], query: str = ""
    ) -> GateDecision[ItemT]:
        """Split `items` into accepted and rejected by their scores.

        `scores` is positional against `items`. A `None` score means the
        reranker did not score that item — which happens when stage 2
        was unavailable or disabled. In that case the gate does not run
        at all rather than substituting a value: comparing an invented
        score against a threshold calibrated on real ones would produce
        a confident, meaningless verdict. Retrieval-only results are
        passed through untouched, and `applied` says so.
        """
        if not items:
            return GateDecision(
                accepted=[], rejected=[], threshold=self._threshold, applied=False
            )

        if any(score is None for score in scores):
            # All-or-nothing on purpose: a mixed batch would mean some
            # results were filtered and others were not, which is not a
            # state any caller could interpret.
            logger.info(
                "relevance_gate_skipped",
                reason="unscored_evidence",
                item_count=len(items),
            )
            return GateDecision(
                accepted=list(items), rejected=[], threshold=None, applied=False
            )

        accepted: list[ItemT] = []
        rejected: list[ItemT] = []
        rejected_scores: list[float] = []
        for item, score in zip(items, scores):
            if score >= self._threshold:
                accepted.append(item)
            else:
                rejected.append(item)
                rejected_scores.append(round(score, 4))

        logger.info(
            "relevance_gate_applied",
            threshold=self._threshold,
            evaluated=len(items),
            accepted=len(accepted),
            rejected=len(rejected),
            # Scores, not content: enough to explain a rejection
            # without logging user text. The query is likewise reduced
            # to its length, matching the reranker's logging contract.
            rejected_scores=rejected_scores,
            query_characters=len(query),
        )
        return GateDecision(
            accepted=accepted, rejected=rejected, threshold=self._threshold, applied=True
        )


def get_relevance_gate() -> RelevanceGate:
    """Return the configured gate.

    Not cached, matching `get_reranker_provider`: it holds no expensive
    state, and the threshold-sensitivity tests change configuration at
    runtime.
    """
    return RelevanceGate()
