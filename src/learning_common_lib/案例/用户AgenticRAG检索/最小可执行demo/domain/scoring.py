"""Deterministic scoring helpers for the first demo."""

from __future__ import annotations

from collections import defaultdict

try:
    from .contracts import EvidenceCardDraft
except ImportError:
    from 最小可执行demo.domain.contracts import EvidenceCardDraft


def score_evidence_cards(cards: list[EvidenceCardDraft]) -> dict[str, float | str]:
    if not cards:
        return {
            "coverage": 0.0,
            "confidence": 0.0,
            "conflict": 1.0,
            "total_score": 0.0,
            "gap_type": "no_evidence",
        }

    unique_sources = {(card.document_id, card.version_id, card.chunk_uid) for card in cards}
    coverage = min(1.0, len(unique_sources) / 3.0)
    confidence = round(sum(card.confidence for card in cards) / len(cards), 3)

    claims_by_text: dict[str, int] = defaultdict(int)
    for card in cards:
        claims_by_text[card.claim] += 1
    duplicate_ratio = 1.0 - (len(claims_by_text) / max(len(cards), 1))
    conflict = round(min(1.0, duplicate_ratio), 3)
    total_score = round((0.5 * coverage) + (0.3 * confidence) - (0.2 * conflict), 3)
    gap_type = "ok" if coverage >= 0.6 and confidence >= 0.55 and conflict <= 0.4 else "insufficient_evidence"
    return {
        "coverage": round(coverage, 3),
        "confidence": confidence,
        "conflict": conflict,
        "total_score": total_score,
        "gap_type": gap_type,
    }


def passes_threshold(eval_summary: dict[str, float | str], min_sources: int, evidence_count: int) -> bool:
    return (
        evidence_count >= min_sources
        and float(eval_summary["coverage"]) >= 0.6
        and float(eval_summary["confidence"]) >= 0.55
        and float(eval_summary["conflict"]) <= 0.4
    )
