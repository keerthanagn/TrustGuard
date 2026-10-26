"""Evidence-quality diagnostics: detect insufficient, outdated and conflicting evidence.

These are explainability signals surfaced in the report. They do not by themselves release or withhold
an answer (the per-claim verifier and the release policy do that), but they flag when the retrieved
evidence base is weak or internally inconsistent - which an evaluator or user should know about.
"""
from __future__ import annotations

from core.models import DocStatus, Evidence
from verification.numeric import extract_quantities, same_value


def diagnose(evidence: list[Evidence], min_relevance: float) -> list[dict]:
    notes: list[dict] = []

    strong = [e for e in evidence if e.score >= min_relevance]
    if not strong:
        notes.append({"kind": "insufficient",
                      "detail": f"No retrieved passage reaches the relevance threshold ({min_relevance})."})

    outdated = [e for e in evidence if e.doc_status == DocStatus.OUTDATED.value]
    if outdated:
        notes.append({"kind": "outdated_present",
                      "detail": "Retrieved set includes passages from a document marked outdated: "
                                + ", ".join(sorted({e.doc_title for e in outdated}))})

    # same provision appearing in more than one document (e.g. original vs amended IT Act)
    by_section: dict[tuple, list[Evidence]] = {}
    for e in strong:
        if e.section:
            by_section.setdefault((e.act_code, e.section), []).append(e)
    for (act, sec), evs in by_section.items():
        docs = {e.doc_title for e in evs}
        if len(docs) > 1:
            # do the duplicate sources disagree on any quantity?
            quant_sets = []
            for e in evs:
                vals = {(q.kind, round(q.value, 4), q.qualifier) for q in extract_quantities(e.text)}
                quant_sets.append((e.doc_title, vals))
            conflict = _quantities_conflict(quant_sets)
            notes.append({
                "kind": "conflicting_sources" if conflict else "duplicate_sources",
                "detail": f"{act} {sec} appears in {len(docs)} documents ({', '.join(sorted(docs))})"
                          + (" with differing stated values." if conflict else "; values are consistent."),
            })
    return notes


def _quantities_conflict(quant_sets: list[tuple]) -> bool:
    kinds = {}
    for _, vals in quant_sets:
        for kind, value, qual in vals:
            kinds.setdefault(kind, set()).add(value)
    # a conflict is two different values for the same kind of quantity across sources
    for kind, values in kinds.items():
        vs = sorted(values)
        for i in range(len(vs)):
            for j in range(i + 1, len(vs)):
                if not same_value(vs[i], vs[j]):
                    return True
    return False
