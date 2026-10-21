"""诊断角色裁面（案例面/报告面）与共享工具的生产契约"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.diagnosis.case_write_tools import CASE_WRITE_TOOL_NAMES
from src.agents.diagnosis.tools import build_diagnosis_tools
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.support.storage_fixtures import fixture_id, storage_for


def _build_tools(ledger=None, role="case", **kwargs):
    return {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(MagicMock()), fixture_id(__name__, "run"), role=role, evidence_ledger=ledger, **kwargs
        )
    }


def _materials():
    repo = MagicMock()
    repo.fetch_pivot_blocks.return_value = [(3, "转折原文", "高潮")]
    repo.fetch_high_tension_chunks.return_value = [(7, "高张力原文", 0.9)]
    repo.fetch_foreshadowing_sources.return_value = []
    repo.calculate_foreshadow_expectation.return_value = 0.35
    repo.fetch_relation_changes.return_value = [(3, "甲", "乙", "盟友", "assert")]
    repo.fetch_topic_words.return_value = [{"topic_id": 9, "weight": 0.2, "words": ["寻路"], "label": None}]
    return repo


def test_role_faces_expose_only_their_writes():
    from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime
    from src.agents.diagnosis.prompts import build_diagnosis_system_prompt

    case_tools = _build_tools()
    assert {"write_event", "push_case"} <= set(case_tools)
    assert {"write_arc", "write_outcome", "write_diagnosis", "read_metrics", "read_topics"}.isdisjoint(case_tools)
    report_tools = _build_tools(role="report")
    assert {"write_arc", "write_outcome", "write_diagnosis", "read_metrics", "read_topics"} <= set(report_tools)
    assert {"write_event", "push_case", "claim_case", "claim_random_case", "submit_case"}.isdisjoint(report_tools)
    assert "claim_random_case" in case_tools
    # 两个角色共享读取与结束工具
    shared = {
        "search_text",
        "read_text",
        "search_events",
        "read_event",
        "search_graph",
        "read_entity",
        "search_cases",
        "finish",
    }
    assert shared <= set(case_tools) and shared <= set(report_tools)
    report_catalog = DiagnosisProgramRuntime(list(report_tools.values())).build_tool().description
    case_catalog = DiagnosisProgramRuntime(list(case_tools.values())).build_tool().description
    assert "claim_case" not in report_catalog and "claim_random_case" not in report_catalog
    assert "submit_case" not in report_catalog
    assert "write_diagnosis" not in case_catalog
    assert "write_diagnosis" not in build_diagnosis_system_prompt(role="case")
    assert "claim_random_case" not in build_diagnosis_system_prompt(role="report")


def test_case_write_channel_mounts_only_with_binding_and_requires_caseid():
    assert set(CASE_WRITE_TOOL_NAMES).isdisjoint(_build_tools())
    tools = _build_tools(case_binding=MagicMock(), case_writes_graph=MagicMock())
    case_tools = {name: tools[name] for name in CASE_WRITE_TOOL_NAMES if name in tools}
    assert set(case_tools) == set(CASE_WRITE_TOOL_NAMES)
    assert all("caseid" in tool.args_schema.model_fields for tool in case_tools.values())


def test_read_metrics_keeps_original_signals_and_named_material_fields():
    ledger = MagicMock()
    with (
        patch("src.storage.access.StatisticsAccess.fetch_global_stats_dict") as stats,
        patch("src.diagnosis.queries.DiagnosisQueries", return_value=_materials()),
        patch("src.agents.diagnosis.tools.graph_signals", return_value={"nodes": 10}),
    ):
        stats.return_value = {"tension": 0.8, "pace": 0.5}
        data = json.loads(_build_tools(ledger, role="report")["read_metrics"].invoke({}))
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
    repo.fetch_foreshadowing_sources.return_value = [{"event_id": "actual-id", "summary": "庇护约定"}]
    with (
        patch("src.storage.access.StatisticsAccess.fetch_global_stats_dict") as stats,
        patch("src.diagnosis.queries.DiagnosisQueries", return_value=repo),
        patch("src.agents.diagnosis.tools.graph_signals", return_value={}),
    ):
        stats.return_value = {}
        data = json.loads(_build_tools(role="report")["read_metrics"].invoke({}))
    assert data["aggregate"] == {} and data["pivots"] == []
    assert data["foreshadowing"] == [{"event_id": "actual-id", "summary": "庇护约定"}]


def test_metric_service_failure_is_raised_without_fake_empty_signals():
    with (
        patch("src.storage.access.StatisticsAccess.fetch_global_stats_dict") as stats,
        patch("src.diagnosis.queries.DiagnosisQueries", return_value=_materials()),
        patch("src.agents.diagnosis.tools.graph_signals", side_effect=ConnectionError("graph dependency unavailable")),
    ):
        stats.return_value = {}
        with pytest.raises(ConnectionError, match="dependency unavailable"):
            _build_tools(role="report")["read_metrics"].invoke({})


def test_topics_keep_actual_ids_weights_words_and_empty_is_literal():
    repo = _materials()
    with patch("src.diagnosis.queries.DiagnosisQueries", return_value=repo):
        tools = _build_tools(role="report")
        assert json.loads(tools["read_topics"].invoke({})) == {"topics": repo.fetch_topic_words.return_value}
        repo.fetch_topic_words.return_value = []
        assert json.loads(tools["read_topics"].invoke({})) == {"topics": []}


def test_report_requires_exactly_one_input_and_failed_patch_preserves_report():
    tools = _build_tools(role="report")
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
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            agent_id=fixture_id(__name__, "batch"),
        )
    }
    ids = list(draft._all_events())

    def item(key, event_id):
        return {
            "operation": "event",
            "key": key,
            "title": "寻路",
            "problem": "能否找到路",
            "summary": "寻路",
            "event_type": "寻路",
            "status": "ongoing",
            "from": 1,
            "to": 1,
            "reason": "批量测试明确判断独立事件",
            "evidence": [{"paragraph_id": 999 if event_id == "missing" else 0}],
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
