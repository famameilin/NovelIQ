"""event_trees 与冻结 35 表结构之间的读写映射（2026-10-16 全库 3NF 改造）

本模块只做结构映射，不含业务规则：

- 运行归属投影：执行行直接携带 run（调用形状）或 session_run_id（整轮会话形状），
  标注与诊断都从执行自身取归属，不互相冒充、不经 work 推导
- 证据读写：source_evidence 的九个所有者列恰一，读回按 ordinal 还原原文引用，
  哈希由不可变原文切片重算
- 声明/完整事件读取：声明经记录（chapter_annotations 自带 run/章）取得运行归属；
  完整事件经真实生产者执行取得；当前阶段是 MAX(stage_index)，不由时间或章号猜
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage import Storage


def run_declaration_ids(session: Storage, run_id: Any) -> Any:
    """本 run 的章级声明：记录自身带运行归属"""
    return session.narrative.run_declaration_ids(run_id)


def run_events(session: Storage, run_id: Any) -> Any:
    """本 run 的完整事件：经真实生产执行取得运行归属"""
    return session.narrative.run_events(run_id)


def declaration_sources(session: Storage, record_ids: Any) -> Any:
    """声明的来源章节：记录自身的章归属与 chapters，返回 record_id→(章号, 章序)"""
    return session.narrative.declaration_sources(record_ids)


def declaration_record_source(session: Storage, record_id: Any) -> Any:
    """声明来源记录的真实上下文：执行号、run_id、章号、章序（不存在返回 None）"""
    return session.narrative.declaration_record_source(record_id)


def dialogue_candidate_rows(session: Storage, run_id: Any) -> Any:
    """对话候选目录：按章序与候选键稳定排序，正文从所属章节区间投影"""
    return session.narrative.dialogue_candidate_rows(run_id)


def dialogue_record_by_candidate(session: Storage, run_id: Any, candidate_key: Any) -> Any:
    """按候选键定位本 run 的对话记录（记录自身带运行归属）"""
    return session.narrative.dialogue_record_by_candidate(run_id, candidate_key)


def execution_in_run(session: Storage, execution_id: Any, run_id: Any) -> Any:
    """真实执行的本 run 归属（调用形状带 run，整轮会话形状带 session_run）"""
    return session.narrative.execution_in_run(execution_id, run_id)


def annotation_chapter_of_execution(session: Storage, execution_id: Any) -> Any:
    """标注执行的来源章：章号取执行自身归属列，章序从 chapters 取得"""
    return session.narrative.annotation_chapter_of_execution(execution_id)


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


def fetch_evidence(session: Storage, owner_column: Any, owner_ids: Any) -> Any:
    """按所有者列批量读取证据行，返回 owner→有序证据"""
    return session.narrative.fetch_evidence(owner_column, owner_ids)


def write_evidence_rows(session: Storage, owner: Any, evidence: Any) -> Any:
    """证据逐条按原顺序写入 source_evidence；owner 恰一由目标表 CHECK 保证"""
    return session.narrative.write_evidence_rows(owner, evidence)


def conflict_payloads(session: Storage, run_id: Any) -> Any:
    """本 run 的冲突读取形状：主体类型、逐条陈述及各自证据"""
    return session.narrative.conflict_payloads(run_id)


def stage_chain(session: Storage, event_ids: Any) -> Any:
    """事件阶段链：按显式 stage_index 升序读取，链尾为当前阶段"""
    return session.narrative.stage_chain(event_ids)


def revision_contents(session: Storage, revisions: Any) -> Any:
    """阶段内容：绑定声明取不可变声明正文，独立 origin 取 origin_* 列"""
    return session.narrative.revision_contents(revisions)


def run_execution_ids(session: Storage, run_id: str) -> list[str]:
    """本 run 的真实执行：整轮会话行与直接携带 run 的调用行"""
    return session.narrative.execution_ids(run_id)
