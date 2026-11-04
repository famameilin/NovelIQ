"""诊断角色裁面（案例面/报告面）与共享工具的生产契约"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.agents.diagnosis.case_write_tools import CASE_WRITE_TOOL_NAMES
from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.event_trees.organization_models import (
    EventOutcomeDraft,
    NarrativeOrganization,
    OrganizationEvidence,
)
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.support.storage_fixtures import fixture_id, storage_for


def _build_tools(ledger=None, role="case", **kwargs):
    if role == "report":
        kwargs.setdefault("report_draft", {"topic_ids": set()})
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
    assert {"write_outcome", "write_diagnosis", "read_metrics", "read_topics"}.isdisjoint(case_tools)
    report_tools = _build_tools(role="report")
    assert {"write_outcome", "write_diagnosis", "read_metrics", "read_topics"} <= set(report_tools)
    assert "write_arc" not in case_tools and "write_arc" not in report_tools
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
    for removed in ("write_arc", "ArcItem", "ArcLinkItem", "parent_arc_id"):
        assert removed not in report_catalog and removed not in case_catalog
    assert "write_diagnosis" not in build_diagnosis_system_prompt(role="case")
    assert "claim_random_case" not in build_diagnosis_system_prompt(role="report")
    assert "write_arc" not in build_diagnosis_system_prompt(role="report")


def test_case_write_channel_mounts_only_with_binding_and_requires_caseid():
    assert set(CASE_WRITE_TOOL_NAMES).isdisjoint(_build_tools())
    tools = _build_tools(case_binding=MagicMock(), case_writes_graph=MagicMock())
    case_tools = {name: tools[name] for name in CASE_WRITE_TOOL_NAMES if name in tools}
    assert set(case_tools) == set(CASE_WRITE_TOOL_NAMES)
    assert all("caseid" in tool.args_schema.model_fields for tool in case_tools.values())


@pytest.mark.parametrize("field", ["arcs", "event_arc_links"])
def test_report_organization_rejects_independent_arc_fields(field):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        NarrativeOrganization.model_validate({field: []})


@pytest.mark.parametrize("changed", ["content", "structure", "outcome"])
def test_report_save_rejects_changed_event_tree_or_outcome_snapshot(changed):
    evidence = [{"paragraph_id": 0, "chapter_id": 1, "char_start": 0, "char_end": 1, "text_hash": "hash"}]
    identity = {"content": "event-content", "structure": "event-structure"}
    draft = SimpleNamespace(
        content_digest=lambda: identity["content"],
        structure_digest=lambda: identity["structure"],
        outcomes={
            "result": EventOutcomeDraft(
                outcome_id="result",
                title="身份确认",
                description="身份得到证实",
                first_text_position=0,
                evidence=evidence,
            )
        },
        finish=MagicMock(side_effect=AssertionError("快照失配不能进入发布")),
    )
    domain = object.__new__(DiagnosisDomain)
    domain.draft = draft
    domain._require_cases_saved = MagicMock()
    domain.reports = {"report": {"analysis": {"diagnosis": "综合报告"}}}
    domain.report_bindings = {"report": domain._report_snapshot()}
    if changed in identity:
        identity[changed] = "changed"
    elif changed == "outcome":
        draft.outcomes["result"] = draft.outcomes["result"].model_copy(update={"description": "身份尚未确认"})
    with pytest.raises(ValueError, match="快照已改变"):
        domain._save_report_progress("report-author")
    draft.finish.assert_not_called()


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


def test_report_rejects_character_names_outside_run_roster():
    tools = _build_tools(role="report", character_roster=["顾霜", "贺重明"])
    with pytest.raises(ValueError, match="不是本 run 的正式角色") as rejected:
        tools["write_diagnosis"].invoke(
            {"analysis": {"arc_scores": {"开局": 6.0, "顾霜": 8.0}, "focus_characters": ["离火之源"]}}
        )
    assert "开局" in str(rejected.value) and "离火之源" in str(rejected.value)
    assert "顾霜" in str(rejected.value)
    receipt = json.loads(
        tools["write_diagnosis"].invoke({"analysis": {"arc_scores": {"顾霜": 8.0}, "focus_characters": ["顾霜"]}})
    )
    assert receipt["status"] == "written"


def test_report_checks_character_names_on_patch():
    tools = _build_tools(role="report", character_roster=["顾霜"])
    tools["write_diagnosis"].invoke({"analysis": {"arc_scores": {"顾霜": 8.0}}})
    with pytest.raises(ValueError, match="不是本 run 的正式角色"):
        tools["write_diagnosis"].invoke({"patch": {"main_characters": ["重明"]}})


def test_write_event_rolls_back_whole_queue_when_member_source_is_invalid(draft_case):
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

    with pytest.raises(ValueError):
        tools["write_event"].invoke(
            {
                "items": [
                    item("a", ids[0]),
                    item("bad", "missing"),
                    item("b", ids[1]),
                ]
            }
        )
    assert not draft.events and not draft.queues
    with pytest.raises(ValueError):
        tools["write_event"].invoke({"items": [{**item("extra", ids[0]), "invented": True}]})
    assert not draft.events and not draft.queues


def test_report_write_rejects_contract_violations() -> None:
    """报告写入点直接拒绝提示词承诺的全部硬约束"""
    roster = ["顾霜", "贺重明", "甲", "乙", "丙", "丁"]
    tools = _build_tools(role="report", character_roster=roster)
    violations = [
        ({"unknown_field": 1}, "Extra inputs"),
        ({"arc_scores": {"顾霜": 11}}, "0–10"),
        ({"arc_scores": {"顾霜": 8, " 顾霜 ": 7}}, "等价重复"),
        (
            {
                "arc_scores": dict.fromkeys(roster, 5),
                "main_characters": roster,
            },
            "最多 5",
        ),
        ({"main_characters": ["顾霜"]}, "必须同时出现在 arc_scores"),
        (
            {
                "arc_scores": {"顾霜": 8, "贺重明": 7},
                "focus_characters": ["顾霜", "贺重明"],
                "focus_structure": "single",
            },
            "不一致",
        ),
        ({"focus_structure": "single"}, "focus_characters 为空"),
        ({"theme_color": "blue"}, "theme_color"),
        ({"narrative_arc_type": "  "}, "不能为空"),
    ]
    for payload, match in violations:
        with pytest.raises(ValueError, match=match):
            tools["write_diagnosis"].invoke({"analysis": payload})


def test_report_write_requires_topics_read_and_exact_ids() -> None:
    """未读主题先写、主题缺项或多项都在写入点拒绝"""
    unread = _build_tools(role="report", report_draft={})
    with pytest.raises(ValueError, match="read_topics"):
        unread["write_diagnosis"].invoke({"analysis": {}})

    tools = _build_tools(role="report", report_draft={"topic_ids": {0, 1}})
    with pytest.raises(ValueError, match="缺少"):
        tools["write_diagnosis"].invoke({"analysis": {"topic_labels": {"0": "成长"}}})
    with pytest.raises(ValueError, match="多出"):
        tools["write_diagnosis"].invoke({"analysis": {"topic_labels": {"0": "成长", "1": "复仇", "2": "冗余"}}})


def test_report_write_canonicalizes_names_and_derives_focus_structure() -> None:
    """等价写法按正式角色名落库，缺失的焦点结构按人数派生并在回执说明"""
    tools = _build_tools(role="report", character_roster=["alice"])
    receipt = json.loads(
        tools["write_diagnosis"].invoke(
            {"analysis": {"arc_scores": {"ALICE": 8}, "focus_characters": ["ALICE"]}}
        )
    )
    assert receipt["status"] == "written"
    assert receipt["canonicalized"] == {"ALICE": "alice"}
    assert receipt["derived"] == {"focus_structure": "single"}
    assert receipt["topic_gap"] == 0


def test_writes_after_report_mark_it_stale_until_resubmission(draft_case) -> None:
    """报告提交后再写事件：写入生效、报告立即失效；重新提交报告后清除"""
    draft = draft_case
    report = {"analysis": {}, "topic_ids": set()}
    case_tools = {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            report_draft=report,
            agent_id=draft.agent_id,
        )
    }
    item = {
        "key": "stale-write",
        "title": "回望",
        "problem": "能否回头",
        "summary": "回望",
        "event_type": "行动",
        "status": "ongoing",
        "from": 1,
        "to": 1,
        "reason": "明确判断独立事件",
        "evidence": [{"paragraph_id": 0}],
    }
    receipt = json.loads(case_tools["write_event"].invoke({"items": [item]}))
    assert receipt["status"] == "written"
    assert receipt["report_stale"] is True
    assert report["stale"] is True
    assert {"unparented_trees", "unassigned", "outcomes"} <= set(receipt["progress"])

    report_tools = {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            role="report",
            organization_draft=draft,
            report_draft=report,
            agent_id=draft.agent_id,
        )
    }
    written = json.loads(report_tools["write_diagnosis"].invoke({"analysis": {"diagnosis": "结构完整"}}))
    assert written["status"] == "written"
    assert "stale" not in report


def test_last_case_submission_rejects_unpublished_cross_execution_references() -> None:
    """最后一个案例提交前先拦截引用其他执行尚未正式保存的事件"""
    from src.agents.diagnosis.tools import _validate_case_submission

    case_pool = MagicMock()
    case_pool.unsubmitted_for.return_value = ["case-1"]
    draft = MagicMock()
    draft.unpublished_references.return_value = ["event-9"]
    with pytest.raises(ValueError, match="尚未正式保存"):
        _validate_case_submission(case_pool, draft, "author", "case-1")


def test_event_case_submission_allows_tree_without_parent() -> None:
    """事件案例确认无真实包含关系时可直接提交"""
    from src.agents.diagnosis.tools import _validate_case_submission
    from src.storage.records.cases import event_tree_case_description

    tree_id = "01a18db2-e32a-7a6e-9003-68f7ce25cae9"
    case_pool = MagicMock()
    case_pool.cases = {"case-1": {"case_type": "event", "description": event_tree_case_description(tree_id)}}
    case_pool.unsubmitted_for.return_value = []
    case_pool.case_runtime = {}
    draft = MagicMock()
    draft.queue_graph.return_value = SimpleNamespace(queues={tree_id: ("event-1",)}, parents={tree_id: []})
    draft.unpublished_references.return_value = []
    _validate_case_submission(case_pool, draft, "author", "case-1")


def test_queue_write_allows_eleventh_structural_root(draft_case) -> None:
    """归并阶段不限制结构入口数量"""
    draft = draft_case
    base = len(draft.queue_graph().unparented)
    assert base == 5
    allowed = 10 - base
    for index in range(allowed + 1):
        key = f"extra-{index}"
        created = draft.event(
            key=key,
            title=f"独立事件{index}",
            problem="是否独立",
            summary=f"独立事件{index}",
            event_type="行动",
            status="ongoing",
            reason="明确判断独立事件",
            from_chapter_id=1,
            to_chapter_id=1,
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
        event_id = created["event_id"]
        draft.queue(
            event_ids=[event_id],
            reason="父子顺序",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    assert len(draft.queue_graph().unparented) == 11
