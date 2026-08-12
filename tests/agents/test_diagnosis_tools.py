"""
诊断 Agent 工具测试

覆盖 src/agents/diagnosis/tools.py：
- build_diagnosis_tools 返回的工具集与命名
- 各工具的取证输出格式（空数据/有数据/异常降级）
- _format_topic_rows 主题词渲染
- 证据台账调用记录

注意：工具函数体内的 import 在调用时执行，patch 必须覆盖 invoke 调用。
2026-08-12 创建，补齐该模块 41% 的低覆盖率。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.agents.diagnosis.tools import _format_topic_rows, build_diagnosis_tools
from src.models.cloud.schema import CloudAnalysis


def _build_tools(session=None, ledger=None) -> list:
    return build_diagnosis_tools(session or MagicMock(), "run-1", evidence_ledger=ledger)


def _invoke(tool, payload: dict | None = None) -> str:
    return tool.invoke(payload or {})


def _make_analysis() -> CloudAnalysis:
    return CloudAnalysis(
        novel_id="novel-1",
        foreshadow_expectation=0.3,
        arc_scores={"沈砚": 8.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels=["成长"],
        diagnosis="ok",
        value_logic_type="善义有价值",
        narrative_arc_type="白手起家",
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )


# ============================================================================
# 工具集构建
# ============================================================================


def test_build_returns_eight_tools() -> None:
    tools = _build_tools()
    assert [tool.name for tool in tools] == [
        "get_aggregate_signals",
        "get_pivot_materials",
        "get_relation_changes",
        "get_character_data",
        "get_topic_data",
        "get_graph_signals",
        "finish",
        "revise_finish",
    ]


# ============================================================================
# get_aggregate_signals
# ============================================================================


def test_get_aggregate_signals_with_stats() -> None:
    ledger = MagicMock()
    with patch("src.storage.repositories.StatsRepository") as repo_cls:
        repo_cls.return_value.fetch_global_stats_dict.return_value = {"tension": 0.8, "pace": 0.5}
        tools = _build_tools(ledger=ledger)
        out = _invoke(tools[0])

    assert "tension: 0.8" in out
    assert "pace: 0.5" in out
    ledger.record_tool_call.assert_called_with("get_aggregate_signals")


def test_get_aggregate_signals_empty() -> None:
    with patch("src.storage.repositories.StatsRepository") as repo_cls:
        repo_cls.return_value.fetch_global_stats_dict.return_value = {}
        tools = _build_tools()
        assert _invoke(tools[0]) == "（无聚合指标数据）"


# ============================================================================
# get_pivot_materials
# ============================================================================


def _mock_pivot_repo(**kwargs) -> MagicMock:
    repo = MagicMock()
    repo.fetch_pivot_blocks.return_value = kwargs.get("pivot_blocks", [])
    repo.fetch_high_tension_chunks.return_value = kwargs.get("high_tension", [])
    repo.fetch_foreshadowing_threads.return_value = kwargs.get("threads", [])
    repo.calculate_foreshadow_expectation.return_value = kwargs.get("expectation")
    return repo


def test_get_pivot_materials_with_all_sections() -> None:
    repo = _mock_pivot_repo(
        pivot_blocks=[(1, "转折文本内容", "高潮")],
        high_tension=[(2, "高张力文本", 0.95)],
        threads=[SimpleNamespace(model_dump_json=lambda: '{"thread": 1}')],
        expectation=0.35,
    )
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        out = _invoke(tools[1])

    assert "<转折块>" in out and "[chunk 1] (高潮)" in out
    assert "<高张力>" in out and "(tension=0.9500)" in out
    assert "<伏笔线程>" in out and '{"thread": 1}' in out
    assert "伏笔兑现预期: 35.00%" in out


def test_get_pivot_materials_empty() -> None:
    repo = _mock_pivot_repo()
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        assert _invoke(tools[1]) == "（无转折素材数据）"


def test_get_pivot_materials_skips_sections_without_data() -> None:
    repo = _mock_pivot_repo(pivot_blocks=[(1, "只有转折", "铺垫")])
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        out = _invoke(tools[1])

    assert "<转折块>" in out
    assert "<高张力>" not in out
    assert "<伏笔线程>" not in out


# ============================================================================
# get_relation_changes
# ============================================================================


def test_get_relation_changes_formats_rows() -> None:
    repo = MagicMock()
    repo.fetch_relation_changes.return_value = [(3, "甲", "乙", "盟友", "新建")]
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        assert _invoke(tools[2]) == "[chunk 3] 甲 -> 乙 (盟友, 新建)"


def test_get_relation_changes_empty() -> None:
    repo = MagicMock()
    repo.fetch_relation_changes.return_value = []
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        assert _invoke(tools[2]) == "（无关系变化数据）"


# ============================================================================
# get_character_data
# ============================================================================


def test_get_character_data_with_known_characters() -> None:
    repo = MagicMock()
    repo.fetch_known_characters.return_value = ["沈砚", "顾霜"]
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        assert _invoke(tools[3]) == "已知人物: ['沈砚', '顾霜']"


def test_get_character_data_empty() -> None:
    repo = MagicMock()
    repo.fetch_known_characters.return_value = []
    with patch("src.storage.repositories.diagnosis_repository.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        assert _invoke(tools[3]) == "（无人物数据）"


# ============================================================================
# get_topic_data
# ============================================================================


def test_get_topic_data_formats_rows() -> None:
    repo = MagicMock()
    repo.fetch_topic_words.return_value = [
        {"topic_id": 1, "weight": 0.6, "words": ["修炼", "境界"], "label": "修炼主题"},
        {"topic_id": 2, "weight": 0.4, "words": [], "label": None},
    ]
    with patch("src.storage.repositories.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        out = _invoke(tools[4])

    assert "1. [topic 1，权重 0.6] 主题词：修炼、境界，标签：修炼主题" in out
    assert "2. [topic 2，权重 0.4]" in out


def test_get_topic_data_empty() -> None:
    repo = MagicMock()
    repo.fetch_topic_words.return_value = []
    with patch("src.storage.repositories.DiagnosisRepository", return_value=repo):
        tools = _build_tools()
        assert _invoke(tools[4]) == "（无主题数据）"


# ============================================================================
# get_graph_signals
# ============================================================================


def test_get_graph_signals_merges_summary_and_quality() -> None:
    with (
        patch("src.knowledge.authority.KnowledgeGraphAuthorityService") as svc_cls,
        patch("src.knowledge.authority.serialize_graph_report_signals") as serialize,
    ):
        svc_cls.from_session.return_value.build_graph_report.return_value = object()
        serialize.return_value = ({"nodes": 10}, {"quality": "high"})
        tools = _build_tools()
        out = _invoke(tools[5])

    assert "nodes: 10" in out
    assert "quality: high" in out


def test_get_graph_signals_unavailable() -> None:
    with patch("src.knowledge.authority.KnowledgeGraphAuthorityService") as svc_cls:
        svc_cls.from_session.return_value.build_graph_report.side_effect = RuntimeError("graph broken")
        tools = _build_tools()
        assert "（图谱信号不可用: graph broken）" in _invoke(tools[5])


def test_get_graph_signals_empty_signals() -> None:
    with (
        patch("src.knowledge.authority.KnowledgeGraphAuthorityService"),
        patch("src.knowledge.authority.serialize_graph_report_signals", return_value=({}, {})),
    ):
        tools = _build_tools()
        assert _invoke(tools[5]) == "（无图谱信号数据）"


# ============================================================================
# finish / revise_finish / 纯函数
# ============================================================================


def test_finish_and_revise_finish_ok() -> None:
    from src.agents.diagnosis.contract import CloudAnalysisPatch

    tools = _build_tools()
    assert _invoke(tools[6], {"analysis": _make_analysis()}) == "OK"
    assert _invoke(tools[7], {"patch": CloudAnalysisPatch(diagnosis="ok")}) == "OK"


def test_format_topic_rows_variants() -> None:
    rows = [
        {"topic_id": 1, "weight": 0.5, "words": ["修炼"], "label": "修炼"},
        {"topic_id": 2, "weight": 0.5, "words": None, "label": None},
    ]
    out = _format_topic_rows(rows)
    assert "1. [topic 1，权重 0.5] 主题词：修炼，标签：修炼" in out
    assert "2. [topic 2，权重 0.5]" in out
