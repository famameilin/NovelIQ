"章级事件、全书事件及其来源归属的存储映射"

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage import Storage


def run_annotation_event_ids(session: Storage, run_id: Any) -> Any:
    """本 run 的章级事件：记录自身带运行归属"""
    return session.narrative.run_annotation_event_ids(run_id)


def run_events(session: Storage, run_id: Any) -> Any:
    """本 run 的完整事件：经真实生产执行取得运行归属"""
    return session.narrative.run_events(run_id)


def annotation_sources(session: Storage, record_ids: Any) -> Any:
    """事件的来源章节：记录自身的章归属与 chapters，返回 record_id→(章号, 章序)"""
    return session.narrative.annotation_sources(record_ids)


def annotation_record_source(session: Storage, record_id: Any) -> Any:
    """事件来源记录的真实上下文：执行号、run_id、章号、章序（不存在返回 None）"""
    return session.narrative.annotation_record_source(record_id)


def dialogue_candidate_rows(session: Storage, run_id: Any) -> Any:
    """对话候选目录：按章序与候选键稳定排序，正文从所属章节区间投影"""
    return session.narrative.dialogue_candidate_rows(run_id)


def dialogue_record_by_candidate(session: Storage, run_id: Any, candidate_key: Any) -> Any:
    """按候选键定位本 run 的对话记录（记录自身带运行归属）"""
    return session.narrative.dialogue_record_by_candidate(run_id, candidate_key)


def execution_in_run(session: Storage, agent_id: Any, run_id: Any) -> Any:
    """真实执行的本 run 归属（调用形状带 run，整轮会话形状带 session_run）"""
    return session.narrative.execution_in_run(agent_id, run_id)


def annotation_chapter_of_execution(session: Storage, agent_id: Any) -> Any:
    """标注执行的来源章：章号取执行自身归属列，章序从 chapters 取得"""
    return session.narrative.annotation_chapter_of_execution(agent_id)


def chapter_offsets(session: Storage, run_id: Any, chapter_ids: Any) -> Any:
    """章正文全文起点；空正文章节无切片，其段落也不存在证据"""
    return session.narrative.chapter_offsets(run_id, chapter_ids)


def paragraph_rows(session: Storage, run_id: Any, paragraph_ids: Any) -> Any:
    """paragraph_rows"""
    return session.narrative.paragraph_rows(run_id, paragraph_ids)


def global_positions(session: Storage, run_id: Any, paragraph_ids: Any) -> Any:
    """段落全文起点 = 所属章节正文起点 + 章内起点"""
    return session.narrative.global_positions(run_id, paragraph_ids)


def evidence_payloads(session: Storage, run_id: Any, rows: Any) -> Any:
    """证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"""
    return session.narrative.evidence_payloads(run_id, rows)


def evidence_payload_groups(session: Storage, run_id: Any, groups: Any) -> Any:
    """批量重组多个所有者的证据行；段落一次读取"""
    return session.narrative.evidence_payload_groups(run_id, groups)


def fetch_evidence(session: Storage, owner_column: Any, owner_ids: Any) -> Any:
    """按所有者列批量读取证据行，返回 owner→有序证据"""
    return session.narrative.fetch_evidence(owner_column, owner_ids)


def write_evidence_rows(session: Storage, owner: Any, evidence: Any) -> Any:
    """证据逐条按原顺序写入 paragraph_evidence；owner 恰一由目标表 CHECK 保证"""
    return session.narrative.write_evidence_rows(owner, evidence)


def run_execution_ids(session: Storage, run_id: str) -> list[str]:
    """本 run 的真实执行：整轮会话行与直接携带 run 的调用行"""
    return session.narrative.execution_ids(run_id)
