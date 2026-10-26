"""TrustGuard — Streamlit application.

Five pages:
  1. Legal Query Workspace     - ask a question, choose model/KB/settings, watch the pipeline run
  2. Verification Results       - released/withheld status, claim-by-claim evidence, reports, downloads
  3. Knowledge Base Management   - upload/remove PDFs, status (verified/unreviewed/outdated), re-index
  4. Evaluation Dashboard        - three-system comparison, metrics, confusion matrices
  5. Audit History               - search past requests, inspect decisions and citations

Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from app_pages.render import render_report
from app_pages.ui_common import available_models, badge, get_base_settings, get_db, header
from core.models import DocStatus
from middleware.pipeline import build_pipeline

st.set_page_config(page_title="TrustGuard", page_icon="⚖", layout="wide")

DB = get_db()
BASE = get_base_settings()


def rehydrate(data: dict):
    from api.server import _rehydrate
    return _rehydrate(data)


# ===================================================================== Page 1
def page_query():
    header("TrustGuard — Legal Query Workspace",
           "Intelligent middleware for hallucination detection and legal fact verification (Indian law)")
    docs = DB.list_documents()
    acts = sorted({d["act_code"] for d in docs if d["index_status"] == "indexed"})

    with st.sidebar:
        st.subheader("Query settings")
        models = available_models(BASE.llm["base_url"])
        if models:
            default = models.index(BASE.llm["model"]) if BASE.llm["model"] in models else 0
            model = st.selectbox("Model (Ollama)", models, index=default)
        else:
            st.warning("No Ollama models found. Start Ollama and pull a model.")
            model = st.text_input("Model", BASE.llm["model"])
        mode = st.selectbox("System", ["trustguard", "retrieval", "base"],
                            format_func={"trustguard": "TrustGuard (verified)", "retrieval": "LLM + retrieval",
                                         "base": "Base LLM (no checks)"}.get)
        chosen_acts = st.multiselect("Knowledge base (acts)", acts, default=acts)
        max_retries = st.slider("Max repair retries", 0, 4, BASE.middleware["max_retries"])
        with st.expander("Verification thresholds"):
            entail = st.slider("Entailment threshold", 0.3, 0.9, float(BASE.verification["entail_threshold"]), 0.05)
            min_rel = st.slider("Min evidence relevance", 0.05, 0.8, float(BASE.retrieval["min_relevance"]), 0.05)
            withhold_review = st.checkbox("Withhold answers flagged REVIEW", BASE.safety["withhold_on_review"])

    examples = [
        "What is the punishment for murder under the Bharatiya Nyaya Sanhita?",
        "What does Section 66C of the IT Act say about identity theft?",
        "Can a person be prosecuted under Section 66A of the IT Act for an offensive post?",
        "What is the GST rate on gold jewellery?",
    ]
    col = st.columns([3, 1])
    with col[1]:
        ex = st.selectbox("Examples", [""] + examples)
    question = col[0].text_area("Legal question", value=ex or st.session_state.get("q", ""), height=90,
                                max_chars=BASE.limits["max_question_chars"])
    run = st.button("Verify with TrustGuard", type="primary", use_container_width=True)

    if run and question.strip():
        if not chosen_acts:
            st.error("Select at least one act in the knowledge base.")
            return
        overrides = {
            "llm": {"model": model},
            "middleware": {"max_retries": max_retries},
            "verification": {"entail_threshold": entail},
            "retrieval": {"min_relevance": min_rel},
            "safety": {"withhold_on_review": withhold_review},
        }
        settings = BASE.with_overrides(overrides)
        doc_ids = [d["doc_id"] for d in docs if d["act_code"] in set(chosen_acts)]
        pipe = build_pipeline(settings, DB)
        stages = st.status("Running verification pipeline…", expanded=True)
        with stages:
            st.write("① Screening the question for malicious intent")
            st.write("② Retrieving legal evidence")
            st.write("③ Generating a draft answer (not shown yet)")
            st.write("④ Extracting atomic claims and verifying each against evidence")
            st.write("⑤ Screening the draft and applying the strict release policy")
            t = time.time()
            report = pipe.run(question.strip(), doc_ids=doc_ids, mode=mode)
            stages.update(label=f"Done in {time.time()-t:.1f}s — {report.decision.value}", state="complete",
                          expanded=False)
        st.session_state["last_report"] = report.to_dict(include_drafts=True)
        st.session_state["q"] = question
        st.divider()
        render_report(st.session_state["last_report"], rehydrate)
        st.info("Full details are also on the **Verification Results** page.")
    elif run:
        st.error("Enter a question first.")


# ===================================================================== Page 2
def page_results():
    header("Verification Results", "The most recent query's decision, evidence and downloadable reports")
    data = st.session_state.get("last_report")
    if not data:
        st.info("Run a query on the Legal Query Workspace page first.")
        return
    st.caption(f"Request ID: {data['request_id']}  ·  {data['created_at']}  ·  mode: {data['mode']}")
    render_report(data, rehydrate)


# ===================================================================== Page 3
def _admin_gate(surface: str) -> bool:
    """Return True if the current viewer may use an admin surface; render a gate otherwise."""
    from core.access import admin_required, check_admin
    if not admin_required(BASE):
        return True
    token = st.sidebar.text_input("Admin token", type="password", key="admin_token")
    ok, reason = check_admin(BASE, token)
    if not ok:
        st.warning(f"🔒 {surface} requires admin access. {reason}")
        return False
    return True


def page_kb():
    header("Knowledge Base Management", "Upload, review and index authoritative legal documents")
    if not _admin_gate("Knowledge Base management"):
        return
    from retrieval.kb_manager import KnowledgeBase
    kb = KnowledgeBase(BASE, DB)

    with st.expander("Upload a legal document (PDF / TXT / DOCX)", expanded=False):
        up = st.file_uploader("File", type=["pdf", "txt", "docx"])
        c = st.columns(4)
        title = c[0].text_input("Title")
        act = c[1].text_input("Act / source code", placeholder="BNS / ITA / COI / SCI")
        ref_type = c[2].selectbox("Reference type", ["Section", "Article", "Paragraph"])
        status = c[3].selectbox("Status", [s.value for s in DocStatus], index=1)
        c2 = st.columns(4)
        doc_type = c2[0].selectbox("Document type", ["legislation", "judgment", "rules", "notification"])
        effective_date = c2[1].text_input("Effective date", placeholder="YYYY-MM-DD")
        court = c2[2].text_input("Court (judgments)", placeholder="Supreme Court of India")
        citation = c2[3].text_input("Citation (judgments)", placeholder="(2015) 5 SCC 1")
        version = st.text_input("Version / currency note", placeholder="e.g. as amended up to 2023")
        licence = st.text_input("Licence / provenance", placeholder="e.g. Government of India - public document")
        if st.button("Ingest and index", type="primary"):
            if not up or not act:
                st.error("A file and an act/source code are required.")
            else:
                with st.spinner("Extracting, chunking and embedding…"):
                    try:
                        with tempfile.TemporaryDirectory() as tmp:
                            p = Path(tmp) / up.name
                            p.write_bytes(up.getbuffer())
                            doc = kb.ingest(p, title=title or up.name, act_code=act.upper(), ref_type=ref_type,
                                            status=status, version=version, doc_type=doc_type,
                                            effective_date=effective_date, court=court, citation=citation,
                                            licence=licence)
                        st.success(f"Indexed {doc['title']}: {doc['chunks']} chunks, {doc['sections']} sections.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Ingestion failed: {exc}")

    docs = DB.list_documents()
    if not docs:
        st.info("No documents yet. Run `python -m scripts.init_kb` or upload a PDF above.")
        return
    st.markdown("##### Indexed documents")
    for d in docs:
        with st.container(border=True):
            cols = st.columns([4, 1.3, 1.3, 1.1])
            meta = f"{d.get('doc_type','legislation')} · {d.get('jurisdiction','India')}"
            if d.get("court"):
                meta += f" · {d['court']}"
            if d.get("citation"):
                meta += f" · {d['citation']}"
            if d.get("effective_date"):
                meta += f" · in force {d['effective_date']}"
            cols[0].markdown(f"**{d['title']}**  \n`{d['doc_id']}` · {d.get('file_type','pdf').upper()} · "
                             f"{d['pages']} pages · {d['chunks']} chunks · {d['sections']} sections")
            cols[0].caption(f"{meta}  ·  {d['version'] or '—'}  ·  licence: {d.get('licence') or 'n/a'}  ·  "
                            f"source: {d['source_url'] or 'n/a'}")
            cols[1].markdown(badge(d["status"].upper(), {"verified": "SUPPORTED", "unreviewed": "REVIEW",
                                                          "outdated": "CONTRADICTED"}.get(d["status"], "REVIEW")),
                             unsafe_allow_html=True)
            new_status = cols[2].selectbox("Status", [s.value for s in DocStatus],
                                           index=[s.value for s in DocStatus].index(d["status"]),
                                           key=f"st_{d['doc_id']}", label_visibility="collapsed")
            if new_status != d["status"]:
                kb.set_status(d["doc_id"], new_status, reviewer_note="status changed via UI")
                st.rerun()
            if cols[3].button("Remove", key=f"rm_{d['doc_id']}"):
                kb.remove(d["doc_id"])
                st.rerun()
            with st.expander("Extracted text sample & page references"):
                chunks = DB.load_chunks([d["doc_id"]])[:4]
                for c in chunks:
                    st.markdown(f"<span class='tg-cite'>{c.ref_type} {c.section} · p.{c.page_start}</span> — "
                                f"{c.heading}", unsafe_allow_html=True)
                    st.caption(c.text[:300])
    st.caption("Status legend: **verified** = authenticated against an official source · "
               "**unreviewed** = provenance not independently checked · "
               "**outdated** = superseded text, excluded from evidence by default.")


# ===================================================================== Page 4
def page_eval():
    header("Evaluation Dashboard", "Three-system comparison on the labelled benchmark")
    settings = BASE
    eval_dir = settings.path("reports_dir") / "eval"
    split = st.radio("Split", ["final_test_v1", "test", "dev"], horizontal=True,
                     help="final_test_v1 is the FROZEN held-out set (report these numbers); 'test' is "
                          "CONSUMED (its failures drove code changes); 'dev' is the threshold-tuning split.")
    _status = {"final_test_v1": "🔒 frozen held-out set", "test": "⚠ consumed (development-informed)",
               "dev": "threshold-tuning split"}.get(split, "")
    if _status:
        st.caption(f"Split role: {_status}. See `evaluation/datasets/STATUS.md`.")
    metrics_path = eval_dir / f"metrics_{split}.json"
    records_path = eval_dir / f"records_{split}.json"

    st.markdown("Reproduce: `python -m evaluation.calibrate` (tunes on **dev** → `config/calibrated.yaml`), "
                "then `python -m evaluation.run_eval --split test` (scripted) or `--split test --llm ollama` "
                "(live model). Refresh after it finishes.")
    if not metrics_path.exists():
        st.warning(f"No results for the {split} split yet. Run the evaluation script first.")
        return
    m = json.loads(metrics_path.read_text(encoding="utf-8"))
    fh = m.get("frozen_artifacts", {}).get("frozen_artifact_hash", "n/a")
    st.caption(f"Split: **{m.get('split', split)}** (status: {m.get('split_status','?')}) · "
               f"backend: {m['llm_backend']} · {m['n_questions']} questions · "
               f"thresholds {m.get('thresholds', {})} ({m.get('thresholds_source','')}) · "
               f"frozen_artifact_hash: `{fh}` · generated {m['generated_at']}")

    rows = []
    for sysname, s in m["systems"].items():
        ci = s.get("unsupported_claim_acceptance_ci", {})
        rows.append({
            "system": sysname, "released": s["released"], "withheld": s["withheld"],
            "withholding_rate": s["withholding_rate"], "retry_rate": s["retry_rate"],
            "retry_success": s.get("retry_success_rate"),
            "hallucination_F1": s["hallucination_detection"]["f1"],
            "hallucination_precision": s["hallucination_detection"]["precision"],
            "hallucination_recall": s["hallucination_detection"]["recall"],
            "unsupported_acceptance": s["unsupported_claim_acceptance_rate"],
            "unsupported_acceptance_95CI": f"[{ci.get('lo')}, {ci.get('hi')}]" if ci else "",
            "valid_answer_rejection": s.get("valid_answer_rejection_rate"),
            "contradiction_detection": s["contradiction_detection_rate"],
            "safety_F1": s["safety"]["f1"], "mean_latency_ms": s["latency_ms"]["mean"],
        })
    df = pd.DataFrame(rows).set_index("system")
    st.markdown("##### Headline metrics")
    st.dataframe(df, use_container_width=True)
    st.caption("Unsupported-claim acceptance = share of should-withhold items the system released "
               "(lower is better); 95% CI is a bootstrap percentile interval. Valid-answer rejection = share "
               "of correct answers wrongly withheld (lower is better). No metric is hardcoded.")

    st.markdown("##### Unsupported-claim acceptance rate (lower is better)")
    st.bar_chart(df["unsupported_acceptance"])
    st.markdown("##### Hallucination-detection F1 (higher is better)")
    st.bar_chart(df["hallucination_F1"])

    if records_path.exists():
        recs = pd.DataFrame(json.loads(records_path.read_text(encoding="utf-8")))
        st.markdown("##### Decision confusion (released vs. should-release), per system")
        for sysname in m["systems"]:
            sub = recs[recs["system"] == sysname]
            tab = pd.crosstab(sub["expected_release"].map({True: "should release", False: "should withhold"}),
                              sub["released"].map({True: "released", False: "withheld/abstained"}))
            st.write(f"**{sysname}**")
            st.table(tab)

    st.download_button("Download metrics.json", metrics_path.read_text(encoding="utf-8"),
                       file_name="trustguard_metrics.json", mime="application/json")

    # retrieval quality (recall@k / MRR), if computed for this split
    retr_path = eval_dir / f"retrieval_{split}.json"
    if retr_path.exists():
        rq = json.loads(retr_path.read_text(encoding="utf-8"))
        st.markdown("##### Retrieval quality on labelled evidence")
        st.caption(f"{rq['configs'][0]['scored_items']} items with an in-KB gold provision scored; "
                   f"{rq['configs'][0]['skipped_no_kb_gold']} excluded (no in-KB gold). "
                   "Recall@k = gold provision appears in top-k; MRR = mean reciprocal rank of first gold hit.")
        rr = []
        for c in rq["configs"]:
            row = {"config": c["config"], "MRR": c["mrr"]["estimate"]}
            for k in rq["ks"]:
                row[f"recall@{k}"] = c[f"recall@{k}"]["estimate"]
            rr.append(row)
        st.dataframe(pd.DataFrame(rr).set_index("config"), use_container_width=True)


# ===================================================================== Page 5
def page_audit():
    header("Audit History", "Search and inspect previous verification decisions")
    is_admin = _admin_gate("Full audit records")
    try:
        integ = DB.verify_audit_integrity()
        st.caption(f"Audit integrity: {'✅ INTACT' if integ['intact'] else '⚠ TAMPERED'} "
                   f"({integ['checked']} chained records verified)"
                   + ("" if integ["intact"] else f" — broken at {integ['broken_at']}"))
    except Exception:
        pass
    if not BASE.privacy.get("log_queries", True):
        st.warning("Query logging is disabled in config (privacy.log_queries=false); questions are stored hashed.")
    c = st.columns([3, 1.3, 1])
    text = c[0].text_input("Search (request ID or question text)")
    decision = c[1].selectbox("Decision", ["", "RELEASED", "WITHHELD"])
    limit = c[2].number_input("Max rows", 10, 1000, 100, step=10)
    rows = DB.search_requests(text=text, decision=decision, limit=int(limit))
    if not rows:
        st.info("No matching requests. Run some queries first.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df[["request_id", "created_at", "mode", "decision", "category", "retries", "total_ms", "question"]],
                 use_container_width=True, height=260)
    rid = st.selectbox("Open a request", [r["request_id"] for r in rows])
    if rid:
        if not is_admin:
            st.info("🔒 Full verification records (including any withheld drafts) require admin access. "
                    "Enter the admin token in the sidebar.")
            return
        data = DB.get_report(rid)
        if data:
            st.divider()
            render_report(data, rehydrate)


PAGES = {
    "① Legal Query Workspace": page_query,
    "② Verification Results": page_results,
    "③ Knowledge Base": page_kb,
    "④ Evaluation Dashboard": page_eval,
    "⑤ Audit History": page_audit,
}

with st.sidebar:
    st.markdown("## ⚖ TrustGuard")
    choice = st.radio("Navigate", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption("Research prototype. Verifies LLM answers against traceable Indian legal evidence; "
               "withholds answers that fail mandatory checks. Not legal advice.")

PAGES[choice]()
