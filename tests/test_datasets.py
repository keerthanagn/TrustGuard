"""Regression tests guarding evaluation-dataset integrity and anti-leakage invariants."""
import json
from pathlib import Path

import pytest

from evaluation.leakage import check_splits, load_split

DATASETS = Path(__file__).resolve().parent.parent / "evaluation" / "datasets"
REQUIRED_FIELDS = {"id", "split", "category", "question", "gold_refs", "expected_release"}


def test_all_splits_parse_and_have_fields():
    for split in ["dev", "test", "final_test_v1", "final_test_v2", "final_test_v3"]:
        items = load_split(split)
        assert items, f"{split} is empty"
        ids = [it["id"] for it in items]
        assert len(ids) == len(set(ids)), f"duplicate ids in {split}"
        for it in items:
            assert REQUIRED_FIELDS <= set(it), f"{it.get('id')} missing fields"


def test_final_set_disjoint_from_dev():
    rep = check_splits("dev", "final_test_v1")
    assert rep["disallowed_shared_refs"] == [], f"provision leakage: {rep['disallowed_shared_refs']}"
    assert rep["exact_question_duplicates"] == []
    assert rep["near_duplicates"] == [], f"near-duplicates: {rep['near_duplicates']}"


def test_final_set_disjoint_from_consumed_test():
    rep = check_splits("test", "final_test_v1")
    assert rep["disallowed_shared_refs"] == []
    assert rep["near_duplicates"] == []


def test_final_test_v2_disjoint_from_all_prior():
    for prior in ("dev", "test", "final_test_v1"):
        rep = check_splits(prior, "final_test_v2")
        assert rep["disallowed_shared_refs"] == [], f"v2 shares provisions with {prior}: {rep['disallowed_shared_refs']}"
        assert rep["exact_question_duplicates"] == [], f"v2 duplicates a {prior} question"
        assert rep["near_duplicates"] == [], f"v2 near-duplicates {prior}: {rep['near_duplicates']}"


def test_final_test_v2_labels_marked():
    for it in load_split("final_test_v2"):
        assert it.get("review_status") and it.get("annotator") and it.get("source")


def test_final_test_v3_disjoint_from_all_prior():
    for prior in ("dev", "test", "final_test_v1", "final_test_v2"):
        rep = check_splits(prior, "final_test_v3")
        assert rep["disallowed_shared_refs"] == [], f"v3 shares provisions with {prior}: {rep['disallowed_shared_refs']}"
        assert rep["exact_question_duplicates"] == [], f"v3 duplicates a {prior} question"
        assert rep["near_duplicates"] == [], f"v3 near-duplicates {prior}: {rep['near_duplicates']}"
    for it in load_split("final_test_v3"):
        assert it.get("review_status") and it.get("annotator") and it.get("source")


def test_final_set_labels_are_honestly_marked():
    # every final-set item must declare its (single-reviewer) annotation provenance - no silent gold labels
    for it in load_split("final_test_v1"):
        assert it.get("review_status"), f"{it['id']} missing review_status"
        assert it.get("annotator"), f"{it['id']} missing annotator"
        assert it.get("source"), f"{it['id']} missing source"


def test_manifest_hashes_match_files():
    manifest_path = DATASETS / "MANIFEST.json"
    if not manifest_path.exists():
        pytest.skip("MANIFEST.json not generated yet")
    import hashlib
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for split, info in manifest["splits"].items():
        if not info.get("present"):
            continue
        actual = hashlib.sha256((DATASETS / info["file"]).read_bytes()).hexdigest()
        assert actual == info["sha256"], f"{split} hash drift: regenerate MANIFEST.json"
