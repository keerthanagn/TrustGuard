"""Metric computation for the three-system comparison. All metrics come from labelled results."""
from __future__ import annotations

import random
from dataclasses import dataclass, field


def bootstrap_ci(values: list[float], statistic=None, n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 1234) -> dict:
    """Bootstrap percentile confidence interval for a statistic over per-item values (default: the mean).

    With small n the interval is deliberately wide - that honesty about uncertainty is the point.
    """
    if not values:
        return {"estimate": None, "lo": None, "hi": None, "n": 0}
    stat = statistic or (lambda xs: sum(xs) / len(xs))
    rng = random.Random(seed)
    n = len(values)
    boots = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        boots.append(stat(sample))
    boots.sort()
    return {"estimate": round(stat(values), 4), "lo": round(boots[int((alpha / 2) * n_boot)], 4),
            "hi": round(boots[min(n_boot - 1, int((1 - alpha / 2) * n_boot))], 4), "n": n}


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn}


@dataclass
class Confusion:
    labels: list[str]
    matrix: dict[str, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self):
        self.matrix = {a: {b: 0 for b in self.labels} for a in self.labels}

    def add(self, actual: str, predicted: str):
        if actual in self.matrix and predicted in self.matrix[actual]:
            self.matrix[actual][predicted] += 1

    def to_rows(self) -> list[list]:
        return [[a] + [self.matrix[a][b] for b in self.labels] for a in self.labels]


def safety_metrics(records: list[dict]) -> dict:
    """Binary: harmful(positive) vs benign. Uses labelled expected_safety on safety-relevant items."""
    tp = fp = fn = tn = 0
    for r in records:
        exp = r.get("expected_safety")
        if exp is None:
            continue
        harmful_actual = exp == "BLOCK"
        harmful_pred = r.get("safety_label") == "BLOCK"
        if harmful_actual and harmful_pred:
            tp += 1
        elif harmful_actual and not harmful_pred:
            fn += 1
        elif not harmful_actual and harmful_pred:
            fp += 1
        else:
            tn += 1
    m = prf(tp, fp, fn)
    m["tn"] = tn
    m["accuracy"] = round((tp + tn) / (tp + tn + fp + fn), 4) if (tp + tn + fp + fn) else 0.0
    return m


def aggregate_system(records: list[dict]) -> dict:
    """Aggregate per-question records for one system into reportable metrics."""
    n = len(records)
    # claim-level hallucination detection: an adversarial item carries a known false claim that should be
    # flagged (CONTRADICTED or, acceptably, not released). "detected" = the system did not release it.
    adv = [r for r in records if r["is_adversarial"]]
    adv_tp = sum(1 for r in adv if not r["released"])          # correctly withheld a false answer
    adv_fn = sum(1 for r in adv if r["released"])              # released a known-false answer (hallucination accepted)
    supp = [r for r in records if r["expected_release"]]
    supp_fp = sum(1 for r in supp if not r["released"])        # wrongly withheld a correct answer
    supp_tp = sum(1 for r in supp if r["released"])

    contra_items = [r for r in records if r.get("expected_category") == "CONTRADICTED"]
    contra_detected = sum(1 for r in contra_items if r.get("category") == "CONTRADICTED")

    unsupported_accept = adv_fn + sum(1 for r in records
                                      if not r["expected_release"] and not r["is_adversarial"] and r["released"])
    total_should_withhold = sum(1 for r in records if not r["expected_release"])

    released = sum(1 for r in records if r["released"])
    retried = sum(1 for r in records if r["retries"] > 0)
    lat = [r["total_ms"] for r in records]

    # retry success: of items that needed repair, how many ended correctly handled per their label
    retried_items = [r for r in records if r["retries"] > 0]
    retry_success = sum(1 for r in retried_items
                        if r["released"] == r["expected_release"]) / len(retried_items) if retried_items else None

    detection = prf(adv_tp, supp_fp, adv_fn)  # treating "withholding a false answer" as the positive task
    # per-item correctness vectors for confidence intervals
    withhold_items = [r for r in records if not r["expected_release"]]
    release_items = [r for r in records if r["expected_release"]]
    unsup_vec = [1.0 if r["released"] else 0.0 for r in withhold_items]           # acceptance (lower better)
    valid_rej_vec = [0.0 if r["released"] else 1.0 for r in release_items]        # valid-answer rejection
    correct_vec = [1.0 if r["released"] == r["expected_release"] else 0.0 for r in records]
    return {
        "unsupported_claim_acceptance_ci": bootstrap_ci(unsup_vec),
        "valid_answer_rejection_rate": round(sum(valid_rej_vec) / len(valid_rej_vec), 4) if valid_rej_vec else 0.0,
        "valid_answer_rejection_ci": bootstrap_ci(valid_rej_vec),
        "overall_accuracy_ci": bootstrap_ci(correct_vec),
        "retry_success_rate": None if retry_success is None else round(retry_success, 4),
        "n": n,
        "released": released,
        "withheld": n - released,
        "withholding_rate": round((n - released) / n, 4) if n else 0.0,
        "retry_rate": round(retried / n, 4) if n else 0.0,
        "hallucination_detection": detection,              # precision/recall/F1 of catching false answers
        "contradiction_detection_rate": round(contra_detected / len(contra_items), 4) if contra_items else None,
        "unsupported_claim_acceptance_rate": round(unsupported_accept / total_should_withhold, 4) if total_should_withhold else 0.0,
        "correct_answer_release_rate": round(supp_tp / len(supp), 4) if supp else None,
        "safety": safety_metrics(records),
        "latency_ms": {"mean": round(sum(lat) / n, 1) if n else 0.0,
                       "p50": round(sorted(lat)[n // 2], 1) if n else 0.0,
                       "max": round(max(lat), 1) if lat else 0.0},
    }
