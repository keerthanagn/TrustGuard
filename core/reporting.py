"""Serialisation of verification reports to JSON, CSV (claim-level) and human-readable Markdown."""
from __future__ import annotations

import csv
import io
import json

from core.models import TrustReport


def aggregate_timings(timings) -> dict[str, float]:
    """Sum per-stage milliseconds for the component-timing view.

    Accepts either StageTiming objects (the live TrustReport) or their serialized dicts (the output of
    TrustReport.to_dict, which the UI and API pass around), so every consumer uses one implementation
    instead of re-deriving the stage/ms access and risking an object-vs-dict mismatch.
    """
    agg: dict[str, float] = {}
    for t in timings:
        stage = t["stage"] if isinstance(t, dict) else t.stage
        ms = t["ms"] if isinstance(t, dict) else t.ms
        agg[stage] = agg.get(stage, 0.0) + ms
    return agg


def report_to_json(report: TrustReport, include_drafts: bool = True) -> str:
    return json.dumps(report.to_dict(include_drafts=include_drafts), ensure_ascii=False, indent=2)


def report_to_claims_csv(report: TrustReport) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["request_id", "attempt", "claim_id", "material", "status", "reason", "cited_refs",
                "supporting_citations", "contradicting_citations", "signals"])
    for attempt in report.attempts:
        for cv in attempt.claims:
            signals = "; ".join(f"{s.name}={'' if s.passed is None else ('pass' if s.passed else 'fail')}"
                                for s in cv.signals)
            w.writerow([
                report.request_id, attempt.attempt, cv.claim.claim_id, cv.claim.material, cv.status.value,
                cv.reason, "; ".join(f"{r.act_code} {r.number}".strip() for r in cv.claim.refs),
                " | ".join(e.citation for e in cv.supporting),
                " | ".join(e.citation for e in cv.contradicting), signals,
            ])
    return buf.getvalue()


def report_to_markdown(report: TrustReport) -> str:
    d = report
    lines = [
        f"# TrustGuard Verification Report",
        f"- **Request ID:** {d.request_id}",
        f"- **Timestamp:** {d.created_at}",
        f"- **Mode:** {d.mode}",
        f"- **Model:** {d.model}",
        f"- **Knowledge base:** {', '.join(d.knowledge_base) or '(none)'}",
        f"- **Decision:** {d.decision.value} ({d.decision_category})",
        f"- **Retries:** {d.retries}",
        f"- **Total time:** {d.total_ms:.0f} ms",
        "",
        f"## Question",
        d.question,
        "",
        f"## Decision",
        d.explanation,
        "",
    ]
    if d.decision.value == "RELEASED":
        lines += ["## Released Answer", d.final_answer, ""]
        if d.citations:
            lines += ["### Citations"] + [f"- {c}" for c in d.citations] + [""]

    if d.question_safety:
        s = d.question_safety
        lines += [f"## Question Safety Screening", f"- Label: **{s.label.value}** (risk {s.risk_score})",
                  f"- {' '.join(s.reasons)}", ""]

    if d.evidence_notes:
        lines += ["## Evidence Diagnostics"]
        lines += [f"- **{n['kind']}**: {n['detail']}" for n in d.evidence_notes]
        lines.append("")

    final = d.final_attempt
    if final and final.claims:
        lines += ["## Claim-by-Claim Verification (final attempt)"]
        for cv in final.claims:
            mark = {"SUPPORTED": "[OK]", "CONTRADICTED": "[CONTRADICTED]",
                    "INSUFFICIENT_EVIDENCE": "[UNSUPPORTED]", "VERIFICATION_ERROR": "[ERROR]"}.get(cv.status.value, "")
            tag = "" if cv.claim.material else " _(non-material)_"
            lines.append(f"\n### {cv.claim.claim_id} {mark}{tag}")
            lines.append(f"> {cv.claim.text}")
            lines.append(f"- **Status:** {cv.status.value}")
            lines.append(f"- **Reason:** {cv.reason}")
            for e in cv.supporting:
                lines.append(f"- Supporting: {e.citation}")
            for e in cv.contradicting:
                lines.append(f"- Contradicting: {e.citation}")
            sig = ", ".join(f"{s.name}:{'-' if s.passed is None else ('pass' if s.passed else 'FAIL')}"
                            for s in cv.signals)
            if sig:
                lines.append(f"- Signals: {sig}")
        if final.safety:
            lines += ["", f"## Answer Safety Screening",
                      f"- Label: **{final.safety.label.value}** (risk {final.safety.risk_score})",
                      f"- {' '.join(final.safety.reasons)}"]

    if d.retries:
        lines += ["", "## Retry / Repair History"]
        for a in d.attempts:
            lines.append(f"- Attempt {a.attempt} ({a.kind}): policy {'PASSED' if a.policy_passed else 'failed: ' + ', '.join(a.policy_failures)}")
            if a.prompt_feedback:
                lines.append(f"    - Feedback used: {a.prompt_feedback.splitlines()[0] if a.prompt_feedback else ''}")

    if d.errors:
        lines += ["", "## Technical Notes"] + [f"- {e}" for e in d.errors]

    lines += ["", "## Component Timings (ms)"]
    for stage, ms in aggregate_timings(d.timings).items():
        lines.append(f"- {stage}: {ms:.0f}")
    return "\n".join(lines)
