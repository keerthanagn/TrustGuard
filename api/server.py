"""REST API for TrustGuard (FastAPI). Start with:  uvicorn api.server:app --port 8000"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from config.settings import get_settings
from core.reporting import report_to_claims_csv, report_to_markdown
from database.db import Database
from llm.adapters import available_backends
from middleware.pipeline import build_pipeline

settings = get_settings()
db = Database(settings.path("db_path"))
app = FastAPI(title="TrustGuard API", version="1.0",
              description="Middleware for hallucination detection and legal fact verification in LLMs.")


class QueryRequest(BaseModel):
    question: str = Field(..., max_length=settings.limits["max_question_chars"])
    mode: str = Field("trustguard", pattern="^(trustguard|retrieval|base)$")
    acts: Optional[list[str]] = None          # restrict to these act codes, e.g. ["BNS","ITA"]
    model: Optional[str] = None
    max_retries: Optional[int] = Field(None, ge=0, le=5)


def _doc_ids_for_acts(acts: Optional[list[str]]) -> Optional[list[str]]:
    if not acts:
        return None
    want = {a.upper() for a in acts}
    return [d["doc_id"] for d in db.list_documents() if d["act_code"] in want]


@app.get("/health")
def health():
    return {"status": "ok", "documents": len(db.list_documents()), **available_backends(settings)}


@app.post("/query")
def query(req: QueryRequest):
    overrides = {}
    if req.model:
        overrides.setdefault("llm", {})["model"] = req.model
    if req.max_retries is not None:
        overrides.setdefault("middleware", {})["max_retries"] = req.max_retries
    s = settings.with_overrides(overrides)
    pipe = build_pipeline(s, db)
    report = pipe.run(req.question, doc_ids=_doc_ids_for_acts(req.acts), mode=req.mode)
    return report.to_dict(include_drafts=False)


@app.get("/report/{request_id}")
def get_report(request_id: str, fmt: str = Query("json", pattern="^(json|markdown|csv)$")):
    data = db.get_report(request_id)
    if not data:
        raise HTTPException(status_code=404, detail="Unknown request_id")
    if fmt == "json":
        return data
    # rebuild a lightweight view for text formats
    from core.models import TrustReport, Decision
    report = _rehydrate(data)
    if fmt == "markdown":
        return PlainTextResponse(report_to_markdown(report), media_type="text/markdown")
    return PlainTextResponse(report_to_claims_csv(report), media_type="text/csv")


@app.get("/history")
def history(text: str = "", decision: str = "", limit: int = Query(100, le=500)):
    return db.search_requests(text=text, decision=decision, limit=limit)


@app.get("/documents")
def documents():
    return db.list_documents()


def _rehydrate(data: dict):
    """Reconstruct a minimal TrustReport from stored JSON for text rendering."""
    from core.models import (Attempt, ClaimStatus, Claim, ClaimVerification, Decision, Evidence,
                             SafetyLabel, SafetyResult, SignalResult, StageTiming, TrustReport)

    def ev(d):
        return Evidence(chunk_id=d.get("chunk_id", ""), doc_id=d.get("doc_id", ""),
                        doc_title=d.get("doc_title", ""), act_code=d.get("act_code", ""),
                        section=d.get("section", ""), ref_type=d.get("ref_type", "Section"),
                        page_start=d.get("page_start", 0), page_end=d.get("page_end", 0),
                        text=d.get("text", ""), score=d.get("score", 0.0))

    def safety(d):
        return SafetyResult(label=SafetyLabel(d["label"]), risk_score=d["risk_score"],
                            categories=d.get("categories", []), reasons=d.get("reasons", [])) if d else None

    attempts = []
    for a in data.get("attempts", []):
        claims = []
        for cv in a.get("claims", []):
            cd = cv["claim"]
            claim = Claim(claim_id=cd["claim_id"], text=cd["text"], sentence_index=cd.get("sentence_index", 0),
                          material=cd.get("material", True))
            claims.append(ClaimVerification(claim=claim, status=ClaimStatus(cv["status"]), reason=cv["reason"],
                                            supporting=[ev(e) for e in cv.get("supporting", [])],
                                            contradicting=[ev(e) for e in cv.get("contradicting", [])],
                                            signals=[SignalResult(**s) for s in cv.get("signals", [])]))
        attempts.append(Attempt(attempt=a["attempt"], kind=a["kind"], draft=a.get("draft", ""),
                                prompt_feedback=a.get("prompt_feedback", ""), claims=claims,
                                safety=safety(a.get("safety")), policy_passed=a.get("policy_passed", False),
                                policy_failures=a.get("policy_failures", [])))
    r = TrustReport(request_id=data["request_id"], question=data["question"], created_at=data["created_at"],
                    model=data["model"], knowledge_base=data.get("knowledge_base", []), mode=data.get("mode", ""))
    r.decision = Decision(data["decision"])
    r.decision_category = data["decision_category"]
    r.final_answer = data.get("final_answer", "")
    r.explanation = data.get("explanation", "")
    r.citations = data.get("citations", [])
    r.question_safety = safety(data.get("question_safety"))
    r.evidence_notes = data.get("evidence_notes", [])
    r.attempts = attempts
    r.timings = [StageTiming(**t) for t in data.get("timings", [])]
    r.errors = data.get("errors", [])
    r.total_ms = data.get("total_ms", 0.0)
    return r
