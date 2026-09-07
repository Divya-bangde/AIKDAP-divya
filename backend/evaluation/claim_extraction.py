"""Sprint 16 Phase 8.6 -- free-text answer -> structured claim.

Evaluation-scoped only: this module is imported by the evaluation
harness, never by `app.*`. It does not touch `GroundedSynthesizer` and
is not wired into production. Its rules were designed and frozen
against the DEV subset only (see `evaluation/gold_claim_extraction.json`
`_dev_set_keys`); the held-out subset was not read until after this
file was written, per the phase's held-out discipline.

Extraction rules, and why each is this narrow:

1. The backend always appends fixed sections ("## Evidence quality",
   "## Objective" / "## Result" for the zero-evidence template) after
   the model's own prose (`synthesis._decorate` / `_insufficient_answer`).
   Those are backend-authored, not model claims, and are stripped
   before extraction rather than parsed as if the model asserted them.
2. `GroundedSynthesizer`'s prompt asks for citation ids inline as
   `[cN]` markers (observed directly in real aguilar_cti output); a
   sentence's citation ids are exactly its `[cN]` markers.
3. The real corpus shows two answer styles: some sentences bold their
   key figure/entity (`**73.5%**`, `**S4 (One-Shot + BLUF)**` --
   observed in the real aguilar_cti answer), others are plain prose
   with no markdown at all (observed in the real sinanian_lte answer).
   A bolded span becomes its own claim (numeric if it matches a number
   pattern, categorical otherwise); a sentence with no bolded span at
   all becomes one categorical claim for the whole sentence. This is a
   routing rule keyed on an objectively observable feature (does bold
   markdown appear), not a per-paper special case.
4. Aggregate-vs-component scope reuses the exact vocabulary already in
   `app.modules.research.claim_verification` (S\\d / Strategy N / Tier
   N / Phase N / "Label:" for component; overall/aggregate/total/
   across all/combined for aggregate) so extraction and verification
   agree on what "aggregate language" means, rather than maintaining a
   second copy of that judgment call.
5. Insufficiency is detected two ways, because the real corpus contains
   two real mechanisms: the backend's own fixed template (no model call
   was made at all -- `grounded_synthesis_skipped`) and free model prose
   declining to answer (observed in the real vaniscak_c2 answer). These
   are recorded with different `source` values so the report can show
   which one is at issue when a case is wrong.
6. Citation binding: a claim with `[cN]` markers in its own sentence
   binds to exactly those ids. A claim with none (the whole-sentence
   categorical path) falls back to every citation the run actually
   returned, since that full set is what backs the sentence when no
   narrower marker exists. This fallback is coarser and is recorded as
   such (`binding_method`) so its accuracy can be reported separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CITATION_MARKER = re.compile(r"\[c(\d+)\]")
_BOLD_SPAN = re.compile(r"\*\*(.+?)\*\*")
_NUMERIC = re.compile(r"^-?\d[\d,]*(?:\.\d+)?%?$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z#*])")

_AGGREGATE_LANGUAGE = re.compile(r"\b(overall|aggregate|combined|across all|total)\b", re.I)
_COMPONENT_LABEL = re.compile(
    r"\b(?:S\d|Strategy\s*\d|Tier\s*\d|Phase\s*\d)\b|\b[A-Z][\w\- ]{0,24}:\s", re.I
)

#: The backend's own fixed wording when synthesis was never called
#: (`GroundedSynthesizer._insufficient_answer`) -- a claim recognized
#: here is a *backend* assertion, not a model one.
_BACKEND_TEMPLATE_MARKER = "The available evidence is insufficient to answer this question"

#: Free-prose phrasings a model uses to decline an answer. Narrow and
#: literal on purpose: this is the vocabulary actually observed in the
#: real corpus, not a general negation detector.
_MODEL_INSUFFICIENCY_LANGUAGE = re.compile(
    r"\b(does not contain enough information|does not (?:explicitly state|provide)|"
    r"cannot (?:be )?determin|not enough information|no (?:single|specific|definitive) "
    r"(?:aggregate |ranking)?(?:percentage|rate|value|ranking))\b",
    re.I,
)


@dataclass(frozen=True)
class ExtractedClaim:
    claim_text: str
    claim_type: str  # "numeric" | "categorical"
    claimed_value: str | None
    scope: str | None  # "aggregate" | "component" | None
    source_reference_ids: list[str]
    binding_method: str  # "explicit_markers" | "whole_answer_fallback"
    attributed_to_primary: bool = True


@dataclass(frozen=True)
class InsufficiencyAssertion:
    claimed_insufficient: bool
    source: str | None  # "backend_template" | "model_text" | None
    evidence_text: str = ""


@dataclass(frozen=True)
class ExtractionResult:
    body: str
    claims: list[ExtractedClaim] = field(default_factory=list)
    insufficiency: InsufficiencyAssertion = field(
        default_factory=lambda: InsufficiencyAssertion(False, None)
    )


def _strip_backend_sections(answer_text: str) -> str:
    """Drop the backend-appended sections, keep only the model's own prose."""
    body = re.split(r"\n##\s", answer_text)[0]
    return body.strip()


def _scope_of(sentence: str) -> str | None:
    has_aggregate = bool(_AGGREGATE_LANGUAGE.search(sentence))
    has_component = bool(_COMPONENT_LABEL.search(sentence))
    if has_aggregate:
        return "aggregate"
    if has_component:
        return "component"
    return None


def _detect_insufficiency(answer_text: str) -> InsufficiencyAssertion:
    if _BACKEND_TEMPLATE_MARKER in answer_text:
        return InsufficiencyAssertion(True, "backend_template", _BACKEND_TEMPLATE_MARKER)
    match = _MODEL_INSUFFICIENCY_LANGUAGE.search(answer_text)
    if match:
        return InsufficiencyAssertion(True, "model_text", match.group(0))
    return InsufficiencyAssertion(False, None)


def extract_claims(answer_text: str, run_citation_ids: list[str]) -> ExtractionResult:
    """Turn one real synthesis answer into structured claims.

    `run_citation_ids` are the ids the run actually returned (its
    accepted citation set), used as the whole-answer fallback binding
    target for a claim with no `[cN]` marker of its own.
    """
    insufficiency = _detect_insufficiency(answer_text)
    body = _strip_backend_sections(answer_text)
    if not body or insufficiency.source == "backend_template":
        # The zero-evidence template carries no factual claim of its own
        # to verify -- only the insufficiency assertion above matters.
        return ExtractionResult(body=body, claims=[], insufficiency=insufficiency)

    claims: list[ExtractedClaim] = []
    for sentence in _SENTENCE_SPLIT.split(body):
        sentence = sentence.strip()
        if not sentence:
            continue
        marker_ids = list(dict.fromkeys(_CITATION_MARKER.findall(sentence)))
        marker_ids = [f"c{n}" for n in marker_ids]
        bold_spans = _BOLD_SPAN.findall(sentence)

        if not bold_spans:
            ids = marker_ids or list(run_citation_ids)
            binding = "explicit_markers" if marker_ids else "whole_answer_fallback"
            claims.append(
                ExtractedClaim(
                    claim_text=sentence,
                    claim_type="categorical",
                    claimed_value=None,
                    scope=None,
                    source_reference_ids=ids,
                    binding_method=binding,
                )
            )
            continue

        for span in bold_spans:
            ids = marker_ids or list(run_citation_ids)
            binding = "explicit_markers" if marker_ids else "whole_answer_fallback"
            if _NUMERIC.match(span.strip()):
                claims.append(
                    ExtractedClaim(
                        claim_text=sentence,
                        claim_type="numeric",
                        claimed_value=span.strip(),
                        scope=_scope_of(sentence),
                        source_reference_ids=ids,
                        binding_method=binding,
                    )
                )
            else:
                claims.append(
                    ExtractedClaim(
                        claim_text=span.strip(),
                        claim_type="categorical",
                        claimed_value=None,
                        scope=None,
                        source_reference_ids=ids,
                        binding_method=binding,
                    )
                )

    return ExtractionResult(body=body, claims=claims, insufficiency=insufficiency)
