"""Rendering of a TrustReport dict into Streamlit components (used by Query and Audit pages)."""
from __future__ import annotations

import streamlit as st

from app_pages.ui_common import STATUS_LABEL, badge, signal_chips
from core.reporting import report_to_claims_csv, report_to_markdown


def _evidence_block(e: dict, contra: bool = False):
    cls = "tg-evidence tg-contra" if contra else "tg-evidence"
    flag = " ⚠ instruction-like text was neutralised" if e.get("injection_flag") else ""
    st.markdown(
        f'<div class="{cls}"><span class="tg-cite">{e.get("citation","")}</span> '
        f'<span style="color:#8a97a3">· relevance {e.get("score",0):.2f} · {e.get("doc_status","")}{flag}</span>'
        f'<br>{e.get("text","")[:600]}</div>', unsafe_allow_html=True)


def render_report(data: dict, rehydrate):
    decision = data["decision"]
    st.markdown(badge(decision, decision) + "  " +
                f'<span style="color:#5a6b7b">· {data["decision_category"]} · '
                f'{data.get("retries",0)} retr{"y" if data.get("retries",0)==1 else "ies"} · '
                f'{data.get("total_ms",0):.0f} ms · model {data.get("model","")}</span>',
                unsafe_allow_html=True)
    st.write("")

    if decision == "RELEASED" and data.get("final_answer"):
        st.markdown("##### Verified answer")
        st.markdown(f'<div class="tg-answer">{data["final_answer"]}</div>', unsafe_allow_html=True)
        if data.get("citations"):
            st.caption("Citations: " + "  •  ".join(data["citations"]))
    else:
        st.markdown("##### Answer withheld")
        st.markdown(f'<div class="tg-withheld">{data.get("explanation","")}</div>', unsafe_allow_html=True)

    # question safety
    qs = data.get("question_safety")
    if qs:
        with st.expander(f"Question safety screening — {qs['label']} (risk {qs['risk_score']})",
                         expanded=qs["label"] != "SAFE"):
            for r in qs.get("reasons", []):
                st.write("•", r)

    attempts = data.get("attempts", [])
    final = attempts[-1] if attempts else None

    # claim-by-claim (final attempt)
    if final and final.get("claims"):
        st.markdown("##### Claim-by-claim verification")
        for cv in final["claims"]:
            status = cv["status"]
            tag = "" if cv["claim"].get("material", True) else '  <span style="color:#8a97a3">(non-material)</span>'
            st.markdown('<div class="tg-card">' +
                        badge(STATUS_LABEL.get(status, status), status) + tag +
                        f'<div class="tg-claim">{cv["claim"]["text"]}</div>'
                        f'<div style="color:#43525f; font-size:0.88rem">{cv["reason"]}</div>',
                        unsafe_allow_html=True)
            for e in cv.get("supporting", []):
                _evidence_block(e)
            for e in cv.get("contradicting", []):
                _evidence_block(e, contra=True)
            st.markdown(signal_chips(cv.get("signals", [])), unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    # answer safety
    if final and final.get("safety"):
        s = final["safety"]
        with st.expander(f"Answer safety screening — {s['label']} (risk {s['risk_score']})",
                         expanded=s["label"] != "SAFE"):
            if s.get("categories"):
                st.write("Risk categories:", ", ".join(s["categories"]))
            for r in s.get("reasons", []):
                st.write("•", r)

    # evidence diagnostics
    if data.get("evidence_notes"):
        icons = {"insufficient": "⚠", "outdated_present": "⌛", "conflicting_sources": "⚠",
                 "duplicate_sources": "ℹ"}
        with st.expander(f"Evidence diagnostics ({len(data['evidence_notes'])})",
                         expanded=any(n["kind"] in ("insufficient", "conflicting_sources")
                                      for n in data["evidence_notes"])):
            for n in data["evidence_notes"]:
                st.write(icons.get(n["kind"], "•"), f"**{n['kind']}** — {n['detail']}")

    # retry history
    if len(attempts) > 1:
        with st.expander(f"Retry / repair history ({data.get('retries',0)} repair attempt(s))"):
            for a in attempts:
                status = "PASSED" if a["policy_passed"] else "failed: " + ", ".join(a["policy_failures"])
                st.markdown(f"**Attempt {a['attempt']} ({a['kind']})** — policy {status}")
                if a.get("prompt_feedback"):
                    st.caption("Repair feedback used:")
                    st.code(a["prompt_feedback"], language="text")

    # timings
    if data.get("timings"):
        from core.reporting import aggregate_timings
        agg = aggregate_timings(data["timings"])
        with st.expander("Component timings (ms)"):
            st.table([{"stage": k, "ms": round(v, 0)} for k, v in agg.items()])

    if data.get("errors"):
        with st.expander("Technical notes"):
            for e in data["errors"]:
                st.write("•", e)

    # downloads
    import json
    st.write("")
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download JSON", json.dumps(data, indent=2), file_name=f"{data['request_id']}.json",
                       mime="application/json", use_container_width=True)
    try:
        report = rehydrate(data)
        c2.download_button("Download claims CSV", report_to_claims_csv(report),
                           file_name=f"{data['request_id']}_claims.csv", mime="text/csv", use_container_width=True)
        c3.download_button("Download report (Markdown)", report_to_markdown(report),
                           file_name=f"{data['request_id']}.md", mime="text/markdown", use_container_width=True)
    except Exception as exc:
        c2.caption(f"(text export unavailable: {exc})")
