"""Regression tests for report/timing-table rendering and the pyarrow/NumPy version conflict.

Guards two fixed bugs:
  - 'pyarrow requires NumPy 2.0 or newer' — pyarrow must import alongside the pinned NumPy 1.26.x.
  - the timing table must render without any dataframe/pyarrow dependency, so a serialization-library
    failure can never hide the legal answer or withholding explanation.
"""
import pytest

from core.models import StageTiming
from core.reporting import aggregate_timings, timings_markdown


def test_pyarrow_imports_with_pinned_numpy():
    import numpy
    assert numpy.__version__.startswith("1.26"), "NumPy must stay pinned for torch/faiss"
    pa = pytest.importorskip("pyarrow")
    # the original crash was at import under NumPy 1.26; a trivial table must also build
    assert pa.table({"stage": ["retrieval"], "ms": [12]}).num_rows == 1


def test_timings_markdown_from_objects_and_dicts():
    objs = [StageTiming("retrieval", 12.0, 0), StageTiming("verification", 40.0, 0),
            StageTiming("retrieval", 5.0, 1)]
    md_obj = timings_markdown(objs)
    md_dict = timings_markdown([t.to_dict() for t in objs])
    assert md_obj == md_dict
    assert md_obj.startswith("| Stage | ms |")
    assert "| retrieval | 17 |" in md_obj and "| verification | 40 |" in md_obj


def test_timings_markdown_needs_no_pyarrow(monkeypatch):
    # simulate pyarrow being unavailable/broken: timing rendering must still work
    import builtins
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("pyarrow requires NumPy 2.0 or newer, found 1.26.4")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    out = timings_markdown([StageTiming("retrieval", 9.0, 0)])
    assert "| retrieval | 9 |" in out


def test_report_markdown_contains_answer_and_timings(settings, db, index):
    from core.reporting import report_to_markdown
    from llm.base import ScriptedLLM
    from middleware.pipeline import TrustGuardPipeline
    ans = ("Under Section 103 of the Bharatiya Nyaya Sanhita, murder is punishable with death or "
           "imprisonment for life, and shall also be liable to fine.")
    report = TrustGuardPipeline(settings, db, llm=ScriptedLLM([ans]), index=index).run(
        "What is the punishment for murder under the BNS?", persist=False)
    md = report_to_markdown(report)
    assert "Released Answer" in md and "Section 103" in md and "Component Timings" in md
