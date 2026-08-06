"""
诊断 Agent 工具（工具化自主取证）

agent 通过工具按需查询聚合指标、转折素材、人物、主题与图谱信号，
自主决定查看哪些证据，最后通过 finish 输出 CloudAnalysis
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from src.config import settings
from src.models.cloud.schema import CloudAnalysis

from .evidence import DiagnosisEvidenceLedger


def build_diagnosis_tools(
    session: Session,
    run_id: str,
    *,
    evidence_ledger: DiagnosisEvidenceLedger | None = None,
) -> list[Any]:
    """构建诊断 agent 工具集"""
    ledger = evidence_ledger or DiagnosisEvidenceLedger()

    @tool
    def get_aggregate_signals() -> str:
        """
        查询全书聚合指标（情绪曲线、张力、节奏等全局统计）。
        用于判断整体叙事节奏与情感走向。
        """
        from src.storage.repositories import StatsRepository

        ledger.record_tool_call("get_aggregate_signals")

        stats_repo = StatsRepository(session)
        stats = stats_repo.fetch_global_stats_dict(run_id)
        if not stats:
            return "（无聚合指标数据）"
        return "\n".join(f"{key}: {value}" for key, value in sorted(stats.items()))

    @tool
    def get_pivot_materials() -> str:
        """
        查询转折点/高张力/伏笔线程等诊断素材。
        用于判断叙事结构、伏笔兑现与高潮分布。
        """
        from src.storage.repositories.diagnosis_repository import DiagnosisRepository

        ledger.record_tool_call("get_pivot_materials")

        repo = DiagnosisRepository(session)
        parts: list[str] = []

        pivot_blocks = repo.fetch_pivot_blocks(run_id, limit=settings.diagnosis.pivot_blocks_limit)
        if pivot_blocks:
            parts.append("<转折块>")
            for chunk_id, chunk_text, event_type in pivot_blocks:
                preview = (chunk_text or "")[: settings.diagnosis.text_limits.pivot_block]
                parts.append(f"[chunk {chunk_id}] ({event_type}) {preview}")
            parts.append("</转折块>")

        high_tension = repo.fetch_high_tension_chunks(run_id, limit=settings.diagnosis.high_tension_limit)
        if high_tension:
            parts.append("<高张力>")
            for chunk_id, chunk_text, tension in high_tension:
                preview = (chunk_text or "")[: settings.diagnosis.text_limits.high_tension]
                parts.append(f"[chunk {chunk_id}] (tension={tension:.4f}) {preview}")
            parts.append("</高张力>")

        foreshadowing_threads = repo.fetch_foreshadowing_threads(run_id)
        if foreshadowing_threads:
            parts.append("<伏笔线程>")
            for thread in foreshadowing_threads[: settings.diagnosis.foreshadowing_limit]:
                parts.append(thread.model_dump_json() if hasattr(thread, "model_dump_json") else str(thread))
            parts.append("</伏笔线程>")

        foreshadow_expectation = repo.calculate_foreshadow_expectation(run_id)
        if foreshadow_expectation is not None:
            parts.append(f"伏笔兑现预期: {foreshadow_expectation:.2%}")

        return "\n".join(parts) if parts else "（无转折素材数据）"

    @tool
    def get_relation_changes() -> str:
        """
        查询人物关系变化事件。
        用于判断角色关系网络发展与主线羁绊。
        """
        from src.storage.repositories.diagnosis_repository import DiagnosisRepository

        ledger.record_tool_call("get_relation_changes")

        repo = DiagnosisRepository(session)
        relations = repo.fetch_relation_changes(run_id, limit=settings.diagnosis.relation_changes_limit)
        if not relations:
            return "（无关系变化数据）"
        return "\n".join(
            f"[chunk {chunk_id}] {from_char} -> {to_char} ({rel_type}, {change})"
            for chunk_id, from_char, to_char, rel_type, change in relations
        )

    @tool
    def get_character_data() -> str:
        """
        查询数据库事实图中的已确认人物节点。
        用于判断核心阵容与主配角。
        """
        from src.storage.repositories.diagnosis_repository import DiagnosisRepository

        ledger.record_tool_call("get_character_data")

        repo = DiagnosisRepository(session)
        known_characters = repo.fetch_known_characters(run_id)
        if known_characters:
            return f"已知人物: {known_characters}"
        return "（无人物数据）"

    @tool
    def get_topic_data() -> str:
        """
        查询主题词与主题分布。
        用于判断全书主题方向与话题覆盖。
        """
        from src.storage.repositories.diagnosis_repository import DiagnosisRepository

        ledger.record_tool_call("get_topic_data")

        repo = DiagnosisRepository(session)
        topic_words = repo.fetch_topic_words(run_id, top_n=settings.diagnosis.topic_words_top_n)
        if not topic_words:
            return "（无主题数据）"
        return "\n".join(f"{index}. {words}" for index, words in enumerate(topic_words, start=1))

    @tool
    def get_graph_signals() -> str:
        """
        查询人物图谱质量信号（节点数、关系数、活跃度等）。
        用于判断角色网络规模与图谱完整性。
        """
        from src.knowledge.authority import KnowledgeGraphAuthorityService, serialize_graph_report_signals

        ledger.record_tool_call("get_graph_signals")

        try:
            graph_report = KnowledgeGraphAuthorityService.from_session(session).build_graph_report(run_id)
        except Exception as exc:  # noqa: BLE001
            return f"（图谱信号不可用: {exc}）"
        summary, quality = serialize_graph_report_signals(graph_report)
        merged_signals = {**summary, **quality}
        if not merged_signals:
            return "（无图谱信号数据）"
        return "\n".join(f"{key}: {value}" for key, value in sorted(merged_signals.items()))

    @tool
    def finish(analysis: CloudAnalysis) -> str:
        """
        完成诊断：提交最终诊断报告。
        必须在完成所有取证后调用；输出必须是完整的 CloudAnalysis JSON。
        """
        return "OK"

    return [
        get_aggregate_signals,
        get_pivot_materials,
        get_relation_changes,
        get_character_data,
        get_topic_data,
        get_graph_signals,
        finish,
    ]
