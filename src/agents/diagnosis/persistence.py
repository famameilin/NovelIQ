"""通过诊断终态校验后保存正式诊断报告、叙事组织及案例交付，事务不交给工作流

报告进 diagnosis_reports（session_id 唯一）、标签/名单/评分进 analysis_assessments；
组织与完整事件由 save_diagnosis_events / save_organization 写入；重投校验按报告投影
与已保存结果比较，不覆盖。
"""

from __future__ import annotations

import unicodedata
from typing import Any, cast

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.diagnosis.schema import AgentAnalysis
from src.event_trees import storage_map as smap
from src.event_trees.organization import (
    CONTRACT_VERSION,
    NarrativeOrganization,
    close_diagnosis_execution,
    save_organization,
    snapshot_digest,
)
from src.utils.identity import stable_uuid


def _character_entity_ids(session: Session, run_id: str, names: list[str]) -> dict[str, str]:
    """诊断名单引用同 run 的正式 character；名称比较沿用 NFC/strip/casefold 身份合同"""
    from src.storage.models import GraphEntity

    if not names:
        return {}
    rows = session.scalars(
        select(GraphEntity).where(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
    )
    by_name = {
        unicodedata.normalize("NFC", row.canonical_name).strip().casefold(): row.entity_id for row in rows
    }
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        entity_id = by_name.get(unicodedata.normalize("NFC", name).strip().casefold())
        if entity_id is None:
            missing.append(name)
        else:
            resolved[name] = entity_id
    if missing:
        raise ValueError(f"诊断名单包含不属于本 run 的正式角色实体: {missing}")
    return resolved


def _save_case_warnings(session: Session, report_id: str, warnings: list[Any]) -> None:
    """正式诊断保存时的真实案例告警逐条落库，不伪造成成功交付"""
    from src.storage.models import CaseEntry

    for ordinal, item in enumerate(warnings):
        payload = item if isinstance(item, dict) else {"message": str(item)}
        reference = str(
            payload.get("case_reference")
            or payload.get("case_id")
            or payload.get("reference")
            or payload.get("code")
            or "unknown"
        )[:255]
        session.add(
            CaseEntry(
                entry_id=stable_uuid("case_save_warning", report_id, str(ordinal)),
                warning_report_id=report_id,
                warning_ordinal=ordinal,
                attempted_case_reference=reference,
                warning_message=str(payload.get("message") or payload.get("detail") or payload)[:255],
            )
        )


def save_diagnosis_report(
    session: Session, run_id: str, session_id: str, analysis: AgentAnalysis
) -> str:
    """写入正式诊断报告及标签/名单/评分条目；同一会话只允许一份报告"""
    from uuid import uuid4

    from src.storage.models import AnalysisAssessment, DiagnosisReport, Execution

    owner = session.get(Execution, session_id)
    if owner is None or owner.session_run_id != run_id:
        raise ValueError("诊断报告缺少本 run 的真实诊断会话")
    report_id = str(uuid4())
    organization = analysis.narrative_organization
    session.add(
        DiagnosisReport(
            report_id=report_id,
            session_id=session_id,
            contract_version=CONTRACT_VERSION,
            diagnosis=analysis.diagnosis,
            value_logic_type=analysis.value_logic_type,
            value_logic_reason=analysis.value_logic_reason,
            power_stance_score=analysis.power_stance_score,
            power_stance_reason=analysis.power_stance_reason,
            common_people_dignity=analysis.common_people_dignity,
            dignity_reason=analysis.dignity_reason,
            cultural_depth_score=analysis.cultural_depth_score,
            cultural_depth_reason=analysis.cultural_depth_reason,
            narrative_arc_type=analysis.narrative_arc_type,
            focus_structure=analysis.focus_structure,
            theme_color=analysis.theme_color,
            identity_snapshot=organization.identity_snapshot if organization is not None else None,
            structure_snapshot=organization.structure_snapshot if organization is not None else None,
        )
    )
    # 报告行先落库：条目的 report_id 外键不靠 ORM 表排序保证
    session.flush()

    def _assessment(**fields: Any) -> None:
        session.add(AnalysisAssessment(assessment_id=str(uuid4()), report_id=report_id, **fields))

    for ordinal, label in enumerate(analysis.genre_labels):
        _assessment(ordinal=ordinal, genre_label=label)
    for ordinal, label in enumerate(analysis.style_labels):
        _assessment(ordinal=ordinal, style_label=label)
    for topic_key, label in analysis.topic_labels.items():
        _assessment(topic_id=int(topic_key), topic_label=label)
    scores = _character_entity_ids(session, run_id, list(analysis.arc_scores))
    for name, score in analysis.arc_scores.items():
        _assessment(scored_entity_id=scores[name], character_score=float(score))
    for cast_role, members in (
        ("focus", analysis.focus_characters),
        ("main", analysis.main_characters),
        ("core", analysis.core_cast),
    ):
        resolved = _character_entity_ids(session, run_id, list(members))
        for ordinal, name in enumerate(members):
            _assessment(cast_role=cast_role, ordinal=ordinal, cast_entity_id=resolved[name])
    session.flush()
    return report_id


def _published_report(session: Session, run_id: str) -> Any:
    """本 run 的正式诊断报告（经整轮会话取得运行归属）；多份报告是数据错误"""
    from src.storage.models import DiagnosisReport, Execution

    rows = list(
        session.scalars(
            select(DiagnosisReport)
            .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
            .where(Execution.session_run_id == run_id)
        )
    )
    if len(rows) > 1:
        raise ValueError("同一运行存在多份正式诊断报告，禁止覆盖或挑选其中一份")
    return rows[0] if rows else None


def _verify_replay(session: Session, run_id: str, report: Any, analysis: AgentAnalysis) -> None:
    """提交回执不明时只核验已保存结果：报告投影、身份/结构快照与正式事件身份必须一致"""
    from src.diagnosis.read import fetch_diagnosis_payload
    from src.event_trees.organization import _run_events

    stored = fetch_diagnosis_payload(session, run_id)
    # 读取投影附带 run_id 等读取面键；重投核验只在正式合同字段上比较已保存结果
    comparable = set(AgentAnalysis.model_fields) - {"narrative_organization"}
    stored_payload = {key: value for key, value in (stored or {}).items() if key in comparable}
    incoming = {key: value for key, value in analysis.model_dump(mode="json").items() if key in comparable}
    if snapshot_digest(stored_payload) != snapshot_digest(incoming):
        raise ValueError("已保存诊断与本次提交不一致，禁止覆盖")
    # 唯一调用点已要求叙事组织非空（persist_analysis：诊断结果缺少全书叙事组织即拒绝）
    organization = cast(NarrativeOrganization, analysis.narrative_organization)
    if (
        report.identity_snapshot != organization.identity_snapshot
        or report.structure_snapshot != organization.structure_snapshot
    ):
        raise ValueError("已保存诊断的身份/结构快照与本次提交不一致，禁止覆盖")
    published = set(_run_events(session, run_id))
    if published != {item.event_id for item in organization.events}:
        raise ValueError("已保存完整事件身份与本次提交不一致，禁止覆盖")


def _save_case_writes(
    session: Session,
    run_id: str,
    output_id: str,
    *,
    graph: Any,
    writers: Any,
    candidates: list[Any],
) -> None:
    """把三类案例处置写入折入正式产物：事实图贡献与对话归因同一事务落库

    语义由标注状态原语保证，本函数只负责按案例贡献快照走 save_work 正式链与按
    候选键定位对话行。
    """
    import json

    from src.fact_graph.contributions import FactContribution

    for _case_id, (writer, author) in sorted(writers.items()):
        facts = graph.drain_ops(author)
        keys: set[str] = set()
        for op in facts["entity_ops"]:
            keys.add(graph.entity_key(op["name"], op["entity_type"]))
        for op in facts["relation_assert_ops"]:
            keys.update((str(op["from_entity"]), str(op["to_entity"])))
        for item in writer.dialogue.written_dialogues.values():
            if item.speaker:
                keys.add(graph.entity_key(item.speaker, "character"))
        facts["entities"] = {
            graph.entity_id_for_key(key): {
                "entity_id": graph.entity_id_for_key(key),
                "name": graph.display_name(key),
                "entity_type": str(graph.entity_type_by_key(key)),
            }
            for key in sorted(keys)
        }
        graph.reference_entities(author, list(facts["entities"].values()))
        frozen = FactContribution(
            run_id,
            author,
            int(writer.current_chapter_id),
            (),
            json.dumps(facts, ensure_ascii=False),
            "[]",
        )
        graph.save_work(session, frozen, output_id)
        # 案例产物折入正式结果：该案例的真实执行行同事务收口
        close_diagnosis_execution(session, execution_id=author)
        for index, item in sorted(writer.dialogue.written_dialogues.items()):
            candidate = candidates[index - 1] if 0 < index <= len(candidates) else None
            if candidate is None:
                raise ValueError(f"write_dialogue candidate_index={index} 超出候选目录")
            row = smap.dialogue_record_by_candidate(session, run_id, candidate.candidate_key)
            if row is None:
                raise ValueError(f"对话候选缺少持久化记录: {candidate.candidate_key}")
            # 当前归因及本次生产者：诊断改归因记诊断执行，原创建来源不改写
            row.current_attribution_execution_id = author
            row.speaker_entity_id = graph.entity_id(item.speaker, "character") if item.speaker else None
            row.tone = str(item.tone) if item.tone else None
            row.is_inner_monologue = item.verdict == "inner_monologue"
    session.flush()


def save_diagnosis_result(
    session: Session,
    run_id: str,
    analysis: AgentAnalysis,
    *,
    case_pool: Any = None,
    case_graph: Any = None,
    case_writers: Any = None,
    case_candidates: Any = None,
) -> None:
    """诊断 Agent 保存实际诊断结果，并把案例采纳绑定到正式报告身份"""
    from src.event_trees.diagnosis_persistence import save_diagnosis_events

    if analysis.narrative_organization is None:
        raise ValueError("诊断结果缺少全书叙事组织")
    session_id = analysis.narrative_organization.source_execution_id
    if not session_id:
        raise ValueError("完整事件保存缺少真实诊断执行来源")
    existing = _published_report(session, run_id)
    if existing is not None:
        _verify_replay(session, run_id, existing, analysis)
        from src.event_trees.read.organization import EventTreeQuery

        # 提交回执不明时只核验已保存结果，不再调用模型或重写任何候选
        EventTreeQuery(session, run_id).fetch()
        return
    authors: list[str] = []
    try:
        report_id = save_diagnosis_report(session, run_id, session_id, analysis)
        save_diagnosis_events(session, run_id, analysis.narrative_organization, report_id)
        save_organization(session, run_id, analysis.narrative_organization, report_id)
        if case_graph is not None and case_writers:
            _save_case_writes(
                session,
                run_id,
                report_id,
                graph=case_graph,
                writers=case_writers,
                candidates=case_candidates or [],
            )
        all_warnings: list[Any] = []
        if case_pool is not None:
            import json

            from src.case_pool.contributions import CaseContribution

            authors = sorted(case_pool.executions)
            for author in authors:
                frozen = CaseContribution(
                    run_id,
                    author,
                    json.dumps(
                        {
                            "created_case_ids": sorted(case_pool.created.get(author, set())),
                            "registrations": {
                                key: case_pool.cases[key] for key in case_pool.registrations.get(author, set())
                            },
                            "deliveries": case_pool.deliveries.get(author, []),
                        },
                        ensure_ascii=False,
                    ),
                )
                all_warnings.extend(case_pool.save_work(session, frozen, adopted_output_id=report_id))
            if all_warnings:
                logger.warning("diagnosis case save warnings: {}", all_warnings)
                _save_case_warnings(session, report_id, all_warnings)
        session.commit()
        if case_pool is not None:
            for author in authors:
                case_pool.confirm(author)
    except Exception:
        session.rollback()
        raise
