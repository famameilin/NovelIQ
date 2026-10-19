"诊断素材查询的读侧边界"

from types import SimpleNamespace

from src.diagnosis import queries as queries_module


def test_relation_changes_skip_entries_without_chapter(monkeypatch):
    relation = SimpleNamespace(
        relation_semantics="ordinary",
        from_name="甲",
        to_name="乙",
        relation_type="友情",
        changes=[
            {"chapter_id": None, "change_kind": "assert", "after": {"relation_type": "友情"}},
            {"chapter_id": 7, "change_kind": "assert", "after": {"relation_type": "友情"}},
        ],
    )
    source = SimpleNamespace(fetch_relation_history=lambda run_id: [relation])
    monkeypatch.setattr(queries_module, "graph_projection", lambda _graph: source)

    rows = queries_module.DiagnosisQueries(SimpleNamespace(graph=object())).fetch_relation_changes("run")

    assert rows == [(7, "甲", "乙", "友情", "assert")]
