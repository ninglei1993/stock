"""概念板块筛选（勾选 / 关键词）。"""

from app.adapters.base import ConceptInfo
from app.services import concept_select as cs


def test_explicit_selection_filters_codes(monkeypatch):
    monkeypatch.setattr(
        cs,
        "read_scan_sectors_selection",
        lambda: (True, ["886033.TI", "MISSING.TI"]),
    )
    concepts = [
        ConceptInfo(code="886033.TI", name="CPO"),
        ConceptInfo(code="885001.TI", name="其他"),
    ]
    out = cs.select_concepts_for_ingest(concepts, max_concepts=1)
    assert len(out) == 1
    assert out[0].code == "886033.TI"


def test_env_filter_when_not_explicit(monkeypatch):
    monkeypatch.setattr(cs, "read_scan_sectors_selection", lambda: (False, []))
    monkeypatch.setattr(cs.settings, "ingest_concept_filter", "CPO")
    monkeypatch.setattr(cs.settings, "ingest_max_concepts", 10)
    concepts = [
        ConceptInfo(code="886033.TI", name="CPO概念"),
        ConceptInfo(code="885001.TI", name="锂电池"),
    ]
    out = cs.select_concepts_for_ingest(concepts)
    assert len(out) == 1
    assert out[0].code == "886033.TI"
