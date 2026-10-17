"""诊断五个 write、两个读取入口及共享工具的生产契约"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.diagnosis.tools import WRITE_NAMES, build_diagnosis_tools
from tests.agents.test_complete_event_invariants import draft_case as draft_case


def _build_tools(ledger=None):
    return {item.name: item for item in build_diagnosis_tools(MagicMock(), "run", evidence_ledger=ledger)}


def _materials():
    repo = MagicMock()
    repo.fetch_pivot_blocks.return_value = [(3, "转折原文", "高潮")]
    repo.fetch_high_tension_chunks.return_value = [(7, "高张力原文", 0.9)]
    repo.fetch_foreshadowing_sources.return_value = []
    repo.calculate_foreshadow_expectation.return_value = 0.35
    repo.fetch_relation_changes.return_value = [(3, "甲", "乙", "盟友", "assert")]
    repo.fetch_topic_words.return_value = [{"topic_id": 9, "weight": 0.2, "words": ["寻路"], "label": None}]
    return repo


def test_exact_five_writes_two_reads_and_shared_directory_has_no_old_bypass():
    from src.agents.diagnosis.case_write_tools import CASE_WRITE_TOOL_NAMES

    tools = _build_tools()
    base_writes = WRITE_NAMES - set(CASE_WRITE_TOOL_NAMES)
    assert {name for name in tools if name.startswith("write_")} == base_writes
    assert WRITE_NAMES == base_writes | set(CASE_WRITE_TOOL_NAMES)
    assert set(tools) == {
        *base_writes,
        "read_metrics",
        "read_topics",
        "search_text",
        "read_text",
        "search_events",
        "read_event",
        "search_graph",
        "read_entity",
        "search_cases",
        "push_case",
        "promise_case",
        "finish",
    }
    assert len(tools) == 17  # 外层另有 execute_code，共18个工具名称；案例处置三写入装配 case 通道时才挂载
    for name in WRITE_NAMES:
        schema = tools[name].args_schema.model_json_schema() if name in tools else None
        if schema is None:
            continue
        assert schema["additionalProperties"] is False
    old_names = {"event", "register_narrative_arc", "submit_diagnosis", "get_topic_data", "prepare_diagnosis"}
    assert old_names.isdisjoint(tools)


def test_case_write_channel_mounts_annotation_writer_into_store():
    from unittest.mock import MagicMock

    from src.agents.diagnosis.case_write_tools import CASE_WRITE_TOOL_NAMES

    store: dict[str, object] = {}
    tools = {
        item.name: item
        for item in build_diagnosis_tools(MagicMock(), "run", work_id="work", case_writes_graph=MagicMock(),
                                         case_writer_store=store)
    }
    assert {"write_entity", "write_relation", "write_dialogue"} <= set(tools)
    assert all(
        "caseid" in tool.args_schema.model_fields
        for name, tool in tools.items()
        if name in set(CASE_WRITE_TOOL_NAMES)
    )
    assert set(store) == {"work"}


def test_read_metrics_keeps_original_signals_and_named_material_fields():
    ledger = MagicMock()
    with (
        patch("src.storage.repositories.StatsRepository") as stats,
        patch("src.diagnosis.queries.DiagnosisQueries", return_value=_materials()),
        patch("src.agents.diagnosis.tools.graph_signals", return_value={"nodes": 10}),
    ):
        stats.return_value.fetch_global_stats_dict.return_value = {"tension": 0.8, "pace": 0.5}
        data = json.loads(_build_tools(ledger)["read_metrics"].invoke({}))
    assert data["aggregate"] == {"tension": 0.8, "pace": 0.5}
    assert data["pivots"] == [{"chapter_id": 3, "text": "转折原文", "event_type": "高潮"}]
    assert data["high_tension"][0]["paragraph_id"] == 7
    assert data["relation_changes"][0]["change_kind"] == "assert"
    assert data["graph_signals"] == {"nodes": 10} and data["foreshadow_expectation"] == 0.35
    ledger.record_tool_call.assert_called_once_with("read_metrics")


def test_read_metrics_keeps_foreshadowing_and_does_not_turn_empty_data_into_failure():
    repo = _materials()
    repo.fetch_pivot_blocks.return_value = []
    repo.fetch_high_tension_chunks.return_value = []
    repo.fetch_foreshadowing_sources.return_value = [{"declaration_id": "actual-id", "summary": "庇护约定"}]
    with (
        patch("src.storage.repositories.StatsRepository") as stats,
        patch("src.diagnosis.queries.DiagnosisQueries", return_value=repo),
        patch("src.agents.diagnosis.tools.graph_signals", return_value={}),
    ):
        stats.return_value.fetch_global_stats_dict.return_value = {}
        data = json.loads(_build_tools()["read_metrics"].invoke({}))
    assert data["aggregate"] == {} and data["pivots"] == []
    assert data["foreshadowing"] == [{"declaration_id": "actual-id", "summary": "庇护约定"}]


def test_metric_service_failure_is_raised_without_fake_empty_signals():
    with (
        patch("src.storage.repositories.StatsRepository") as stats,
        patch("src.diagnosis.queries.DiagnosisQueries", return_value=_materials()),
        patch("src.agents.diagnosis.tools.graph_signals", side_effect=ConnectionError("graph dependency unavailable")),
    ):
        stats.return_value.fetch_global_stats_dict.return_value = {}
        with pytest.raises(ConnectionError, match="dependency unavailable"):
            _build_tools()["read_metrics"].invoke({})


def test_topics_keep_actual_ids_weights_words_and_empty_is_literal():
    repo = _materials()
    with patch("src.diagnosis.queries.DiagnosisQueries", return_value=repo):
        tools = _build_tools()
        assert json.loads(tools["read_topics"].invoke({})) == {"topics": repo.fetch_topic_words.return_value}
        repo.fetch_topic_words.return_value = []
        assert json.loads(tools["read_topics"].invoke({})) == {"topics": []}


def test_report_requires_exactly_one_input_and_failed_patch_preserves_report():
    tools = _build_tools()
    tools["write_diagnosis"].invoke({"analysis": {"diagnosis": "有效报告"}})
    tools["write_diagnosis"].invoke({"patch": {"diagnosis": "明确修订"}})
    with pytest.raises(ValueError, match="必须且只能"):
        tools["write_diagnosis"].invoke({"analysis": {}, "patch": {}})
    with pytest.raises(ValueError):
        tools["write_diagnosis"].invoke({"patch": {"power_stance_score": 99}})
    assert "end_requested" in tools["finish"].invoke({})


def test_write_event_batch_rejects_invalid_source_but_keeps_good_items(draft_case):
    draft = draft_case
    tools = {
        item.name: item
        for item in build_diagnosis_tools(
            draft.session,
            draft.run_id,
            organization_draft=draft,
            execution_id="batch",
        )
    }
    ids = list(draft._declarations())

    def item(key, declaration_id):
        return {
            "operation": "identity",
            "key": key,
            "title": "寻路",
            "problem": "能否找到路",
            "summary": "寻路",
            "event_type": "寻路",
            "status": "ongoing",
            "declaration_ids": [declaration_id],
            "stage_order": [declaration_id],
            "current_declaration_id": declaration_id,
            "reason": "批量测试明确判断独立事件",
            "evidence": [{"paragraph_id": 0}],
        }

    result = json.loads(
        tools["write_event"].invoke(
            {
                "items": [
                    item("a", ids[0]),
                    item("bad", "missing"),
                    item("b", ids[1]),
                ]
            }
        )
    )
    assert result["status"] == "partial" and result["failed"][0]["index"] == 1
    assert result["results"][1] is None and len(draft.events) == 2
    assert all(result["results"][index]["event_id"] in draft.events for index in (0, 2))
    with pytest.raises(ValueError):
        tools["write_event"].invoke({"items": [{**item("extra", ids[0]), "invented": True}]})
    assert len(draft.events) == 2
