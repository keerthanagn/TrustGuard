from core.models import DocStatus, Evidence
from evaluation.metrics import aggregate_system, bootstrap_ci, prf, safety_metrics
from verification.evidence_diag import diagnose


def ev(section, text, title, score=0.9, status="verified"):
    return Evidence(chunk_id=f"{title}:{section}", doc_id=title, doc_title=title, act_code="ITA",
                    section=section, ref_type="Section", page_start=1, page_end=1, text=text,
                    score=score, doc_status=status)


def test_prf():
    m = prf(tp=8, fp=0, fn=2)
    assert m["precision"] == 1.0 and m["recall"] == 0.8


def test_bootstrap_ci_bounds():
    ci = bootstrap_ci([1.0] * 10)
    assert ci["estimate"] == 1.0 and ci["lo"] == 1.0 and ci["hi"] == 1.0
    ci2 = bootstrap_ci([0.0, 1.0] * 10)
    assert 0.0 <= ci2["lo"] <= ci2["estimate"] <= ci2["hi"] <= 1.0


def test_diagnose_conflicting_sources():
    evs = [ev("66", "punishable with imprisonment up to three years or fine up to five lakh rupees", "Amended Act"),
           ev("66", "punishable with imprisonment up to ten years", "Original Act")]
    notes = diagnose(evs, min_relevance=0.3)
    assert any(n["kind"] == "conflicting_sources" for n in notes)


def test_diagnose_outdated_flagged():
    evs = [ev("66", "some text about hacking", "Old Act", status=DocStatus.OUTDATED.value)]
    notes = diagnose(evs, min_relevance=0.3)
    assert any(n["kind"] == "outdated_present" for n in notes)


def test_retrieval_first_hit_rank_and_mrr():
    from evaluation.retrieval_eval import first_hit_rank
    ranked = [{"BNS:302"}, {"BNS:103"}, {"ITA:66"}]      # gold at rank 2
    assert first_hit_rank(ranked, {"BNS:103"}) == 2
    assert first_hit_rank([{"X:1"}, set()], {"BNS:103"}) is None   # miss
    assert first_hit_rank([{"BNS:103"}], {"BNS:103", "BNS:303"}) == 1


def test_aggregate_distinguishes_systems():
    # one adversarial item: trustguard withholds (good), base releases (bad)
    base = [{"is_adversarial": True, "expected_release": False, "released": True, "expected_category": None,
             "category": "BASELINE", "retries": 0, "total_ms": 100.0, "expected_safety": None, "abstained": False}]
    tg = [{"is_adversarial": True, "expected_release": False, "released": False, "expected_category": "CONTRADICTED",
           "category": "CONTRADICTED", "retries": 0, "total_ms": 100.0, "expected_safety": None, "abstained": False}]
    assert aggregate_system(base)["unsupported_claim_acceptance_rate"] == 1.0
    assert aggregate_system(tg)["unsupported_claim_acceptance_rate"] == 0.0
