"叙事来源的具名物理记录操作"

from __future__ import annotations

from typing import Any

from src.storage.input_boundary import plain_inputs
from src.storage.repositories import narrative_records as _records


@plain_inputs
class NarrativeAccess:
    def __init__(self, runner):
        self._runner = runner

    def check_contribution(self, request) -> bool:
        "在包内读取并核对声明关系与有序证据"
        from src.storage.repositories.declaration_writes import check_declaration_contribution

        return self._runner.run(lambda session: check_declaration_contribution(session, request), read_only=True)

    def run_declaration_ids(self, run_id: Any) -> Any:
        "本 run 的章级声明：记录自身带运行归属"
        return self._runner.run(lambda session: _records.run_declaration_ids(session, run_id), read_only=True)

    def run_events(self, run_id: Any) -> Any:
        "本 run 的完整事件：经真实生产执行取得运行归属"
        return self._runner.run(lambda session: _records.run_events(session, run_id), read_only=True)

    def declaration_sources(self, record_ids: Any) -> Any:
        "声明的来源章节：记录自身的章归属与 chapters，返回 record_id→(章号, 章序)"
        return self._runner.run(lambda session: _records.declaration_sources(session, record_ids), read_only=True)

    def declaration_record_source(self, record_id: Any) -> Any:
        "声明来源记录的真实上下文：执行号、run_id、章号、章序（不存在返回 None）"
        return self._runner.run(lambda session: _records.declaration_record_source(session, record_id), read_only=True)

    def dialogue_candidate_rows(self, run_id: Any) -> Any:
        "对话候选目录：按章序与候选键稳定排序，正文从所属章节区间投影"
        return self._runner.run(lambda session: _records.dialogue_candidate_rows(session, run_id), read_only=True)

    def dialogue_record_by_candidate(self, run_id: Any, candidate_key: Any) -> Any:
        "按候选键定位本 run 的对话记录（记录自身带运行归属）"
        return self._runner.run(
            lambda session: _records.dialogue_record_by_candidate(session, run_id, candidate_key), read_only=True
        )

    def execution_in_run(self, execution_id: Any, run_id: Any) -> Any:
        "真实执行的本 run 归属（调用形状带 run，整轮会话形状带 session_run）"
        return self._runner.run(
            lambda session: _records.execution_in_run(session, execution_id, run_id), read_only=True
        )

    def annotation_chapter_of_execution(self, execution_id: Any) -> Any:
        "标注执行的来源章：章号取执行自身归属列，章序从 chapters 取得"
        return self._runner.run(
            lambda session: _records.annotation_chapter_of_execution(session, execution_id), read_only=True
        )

    def chapter_offsets(self, run_id: Any, chapter_ids: Any) -> Any:
        "章正文全文起点；空正文章节无切片，其段落也不存在证据"
        return self._runner.run(lambda session: _records.chapter_offsets(session, run_id, chapter_ids), read_only=True)

    def paragraph_rows(self, run_id: Any, paragraph_ids: Any) -> Any:
        "paragraph_rows"
        return self._runner.run(lambda session: _records.paragraph_rows(session, run_id, paragraph_ids), read_only=True)

    def global_positions(self, run_id: Any, paragraph_ids: Any) -> Any:
        "段落全文起点 = 所属章节正文起点 + 章内起点"
        return self._runner.run(
            lambda session: _records.global_positions(session, run_id, paragraph_ids), read_only=True
        )

    def evidence_payloads(self, run_id: Any, rows: Any) -> Any:
        "证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"
        return self._runner.run(lambda session: _records.evidence_payloads(session, run_id, rows), read_only=True)

    def fetch_evidence(self, owner_column: Any, owner_ids: Any) -> Any:
        "按所有者列批量读取证据行，返回 owner→有序证据"
        if owner_column not in {
            "graph_fact_id",
            "declaration_id",
            "complete_event_id",
            "narrative_group_id",
            "narrative_link_id",
            "foreshadow_action_id",
            "conflict_id",
            "claim_id",
            "check_id",
        }:
            raise ValueError("无效的证据所有者类型")
        return self._runner.run(
            lambda session: _records.fetch_evidence(session, getattr(_records.SourceEvidence, owner_column), owner_ids),
            read_only=True,
        )

    def write_evidence_rows(self, owner: Any, evidence: Any) -> Any:
        "证据逐条按原顺序写入 source_evidence；owner 恰一由目标表 CHECK 保证"
        return self._runner.run(lambda session: _records.write_evidence_rows(session, owner, evidence), read_only=False)

    def conflict_payloads(self, run_id: Any) -> Any:
        "本 run 的冲突读取形状：主体类型、逐条陈述及各自证据"
        return self._runner.run(lambda session: _records.conflict_payloads(session, run_id), read_only=True)

    def stage_chain(self, event_ids: Any) -> Any:
        "事件阶段链：按显式 stage_index 升序读取，链尾为当前阶段"
        return self._runner.run(lambda session: _records.stage_chain(session, event_ids), read_only=True)

    def revision_contents(self, revisions: Any) -> Any:
        "阶段内容：绑定声明取不可变声明正文，独立 origin 取 origin_* 列"
        return self._runner.run(lambda session: _records.revision_contents(session, revisions), read_only=True)

    def execution_ids(self, run_id: str) -> list[str]:
        "本 run 的直接执行及整轮会话身份列表"
        return self._runner.run(
            lambda session: list(session.scalars(_records.run_execution_ids(run_id))), read_only=True
        )
