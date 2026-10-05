"""Combines extractions from all documents into one submission, and decides whether a person must look at it."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date

from .models import REQUIRED_FIELDS, Conflict, DocKind, Extraction, SubmissionResult
from .normalize import company_key, squash

# Forms and spreadsheets beat the email body: brokers often shorten names or round dates in prose.
SOURCE_RANK = {DocKind.APPLICATION: 3, DocKind.SOV: 3, DocKind.LOSS_RUN: 3, DocKind.OTHER: 2, DocKind.EMAIL_BODY: 1}
METHOD_RANK = {"parser": 3, "rules": 2, "llm": 1}
MIN_CONFIDENCE = 0.7


def same_value(field: str, a: str | int | float | date, b: str | int | float | date) -> bool:
    if field in ("insured_name", "broker_name") and isinstance(a, str) and isinstance(b, str):
        return company_key(a) == company_key(b)
    if isinstance(a, str) and isinstance(b, str):
        return squash(a) == squash(b)
    return a == b


def merge(extractions: Iterable[Extraction], kinds: Mapping[str, DocKind]) -> SubmissionResult:
    by_field: dict[str, list[Extraction]] = defaultdict(list)
    for extraction in extractions:
        by_field[extraction.field].append(extraction)

    chosen: dict[str, Extraction] = {}
    conflicts: list[Conflict] = []
    for field, candidates in by_field.items():
        ranked = sorted(
            candidates,
            key=lambda e: (SOURCE_RANK[kinds.get(e.document_id, DocKind.OTHER)], METHOD_RANK[e.method], e.confidence),
            reverse=True,
        )
        best = ranked[0]
        chosen[field] = best
        disagreeing = [e for e in ranked[1:] if not same_value(field, best.value, e.value)]
        if disagreeing:
            distinct: list[Extraction] = [best]
            for e in disagreeing:
                if not any(same_value(field, e.value, d.value) for d in distinct):
                    distinct.append(e)
            conflicts.append(Conflict(field=field, values=distinct))

    missing = [f for f in REQUIRED_FIELDS if f not in chosen]
    reasons = [f"missing {f}" for f in missing]
    reasons += [f"documents disagree on {c.field}" for c in conflicts]
    reasons += [
        f"low confidence in {f} ({chosen[f].confidence:.2f})"
        for f in REQUIRED_FIELDS
        if f in chosen and chosen[f].confidence < MIN_CONFIDENCE
    ]
    return SubmissionResult(
        fields=chosen,
        conflicts=conflicts,
        missing=missing,
        status="needs_review" if reasons else "ready",
        review_reasons=reasons,
    )
