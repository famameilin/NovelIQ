"""API、聚合、诊断与导出共享的 released cutoff 读边界"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import (
    AnalysisCutoff,
    AnalysisRun,
    ContinuityCase,
    CutoffPartition,
    Paragraph,
    TextEvidenceRecord,
)


def released_cutoff(session: Session, run_id: str) -> AnalysisCutoff | None:
    return session.execute(
        select(AnalysisCutoff)
        .where(
            AnalysisCutoff.run_id == run_id,
            AnalysisCutoff.state == "released",
        )
        .order_by(AnalysisCutoff.released_at.desc(), AnalysisCutoff.cutoff_hash)
        .limit(1)
    ).scalar_one_or_none()


def require_released_cutoff(session: Session, run_id: str) -> AnalysisCutoff:
    """读期间持共享 run 锁，阻止另一个释放事务切换半途可见边界"""
    run = session.get(AnalysisRun, run_id, with_for_update={"read": True})
    cutoff = released_cutoff(session, run_id)
    if run is None or cutoff is None or run.annotation_cutoff_hash != cutoff.cutoff_hash:
        raise ValueError("分析结果尚未完成发布")
    return cutoff


def require_released_cutoff_short(run_id: str) -> AnalysisCutoff:
    """2026-10-03 短事务版边界检查：检查完立即提交、共享锁随事务结束释放

    aggregate/diagnose 的编排器 session 是长活事务（跨整个阶段）——在其上取 FOR SHARE
    会把 analysis_runs 行锁持有整个阶段（run 4a6c268c 实证：diagnose 期间任务心跳的
    UPDATE 连续等满 2 分钟语句超时）。检查只需要瞬时一致：专用短会话锁住、读、提交还锁。
    阶段中后到的新释放事务不再被本检查拦截——当前产品里释放只发生在 run_annotate 的
    串行流程内（aggregate/diagnose 之前），无并发释放可言。
    """
    from src.storage.db import get_session

    with get_session() as check_session:
        return require_released_cutoff(check_session, run_id)


def cutoff_view(session: Session, cutoff: AnalysisCutoff) -> dict[str, Any]:
    partitions = list(
        session.execute(
            select(CutoffPartition).where(
                CutoffPartition.cutoff_hash == cutoff.cutoff_hash,
            )
        ).scalars()
    )
    states = dict.fromkeys(("pending", "resolved", "deferred", "contested"), 0)
    by_partition = {row.partition_key: row.projection for row in partitions}
    formal_events = {
        item["payload"]["node_id"]: item
        for row in partitions
        for item in row.projection.get("assertions", [])
        if item["kind"] == "event"
    }
    formal_entities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in partitions:
        for item in row.projection.get("assertions", []):
            if item["kind"] == "entity_mention":
                formal_entities[item["payload"]["entity_id"]].append(item)
    cases: list[dict[str, Any]] = []
    case_records = {
        row.case_id: row
        for row in session.execute(
            select(ContinuityCase).where(
                ContinuityCase.run_id == cutoff.run_id,
                ContinuityCase.case_id.in_([item["case_id"] for item in cutoff.manifest["cases"]]),
            )
        ).scalars()
    }
    for case in cutoff.manifest["cases"]:
        states[case["state"]] += 1
        projection = by_partition.get(f"case:{case['case_id']}", {})
        record = case_records[case["case_id"]]
        cases.append(
            {
                **case,
                "description": record.description,
                "type": record.issue_kind,
                "target_ref": record.target_ref,
                "source_evidence": record.source_evidence,
                "continuity_claims": projection.get("assertions", []),
            }
        )
    domain_values = []
    pending_dependency_count = 0
    contested_partition_count = 0
    for row in partitions:
        pending_dependency_count += int(bool(row.projection.get("pending_dependency")))
        contested_partition_count += int(bool(row.projection.get("contested")))
        assertions = row.projection.get("assertions", [])
        formal = [
            item
            for item in assertions
            if item["kind"]
            in {
                "dialogue",
                "local_relation",
                "event",
                "entity_mention",
                "character_observation",
            }
        ]
        continuity = [
            item
            for item in assertions
            if item["kind"]
            in {
                "dialogue_attribution",
                "relation_change",
                "event_link",
                "identity_binding",
                "entity_type_resolution",
                "identity_arbitration",
                "cross_chapter_link",
            }
        ]
        event_links = [item for item in continuity if item["kind"] == "event_link"]
        if event_links:
            event_ids = {item["payload"][field] for item in event_links for field in ("event_id", "root_event_id")}
            formal = [formal_events[event_id] for event_id in sorted(event_ids) if event_id in formal_events]
        identity_claims = [item for item in continuity if item["kind"] == "identity_binding"]
        if identity_claims:
            entity_ids = {
                item["payload"][field] for item in identity_claims for field in ("entity_id", "canonical_entity_id")
            }
            formal = [mention for entity_id in sorted(entity_ids) for mention in formal_entities.get(entity_id, [])]
        if continuity or row.projection.get("contested") or row.projection.get("pending_dependency"):
            domain_values.append(
                {
                    "target": row.partition_key,
                    "formal_values": formal,
                    "continuity_values": continuity,
                    "state": "contested"
                    if row.projection["contested"]
                    else ("pending_dependency" if row.projection.get("pending_dependency") else "resolved"),
                    "projection_hash": row.projection_hash,
                }
            )
    evidence_ids = {
        evidence_id
        for case in cases
        for assertion in case["continuity_claims"]
        for evidence_id in assertion["evidence_ids"]
    }
    evidence_ids.update(evidence_id for case in cases for evidence_id in case["source_evidence"])
    evidence_ids.update(
        evidence_id
        for domain in domain_values
        for assertion in [*domain["formal_values"], *domain["continuity_values"]]
        for evidence_id in assertion["evidence_ids"]
    )
    evidence = []
    if evidence_ids:
        records = session.execute(
            select(TextEvidenceRecord, Paragraph.text)
            .join(
                Paragraph,
                (
                    (Paragraph.run_id == TextEvidenceRecord.run_id)
                    & (Paragraph.paragraph_id == TextEvidenceRecord.paragraph_id)
                ),
            )
            .where(TextEvidenceRecord.evidence_id.in_(sorted(evidence_ids)), TextEvidenceRecord.run_id == cutoff.run_id)
        ).all()
        evidence = [
            {
                "evidence_id": row.TextEvidenceRecord.evidence_id,
                "chapter_id": row.TextEvidenceRecord.chapter_id,
                "paragraph_id": row.TextEvidenceRecord.paragraph_id,
                "char_start": row.TextEvidenceRecord.char_start,
                "char_end": row.TextEvidenceRecord.char_end,
                "text_hash": row.TextEvidenceRecord.text_hash,
                "text": row.text[row.TextEvidenceRecord.char_start : row.TextEvidenceRecord.char_end],
            }
            for row in records
        ]
    return {
        "cutoff_hash": cutoff.cutoff_hash,
        "round_kind": cutoff.round_kind,
        "round_number": cutoff.round_number,
        "released_at": cutoff.released_at.isoformat() if cutoff.released_at is not None else None,
        "formal_count": len(cutoff.manifest["formal"]),
        "case_states": states,
        "cases": cases,
        "domain_values": domain_values,
        "pending_dependency_count": pending_dependency_count,
        "contested_partition_count": contested_partition_count,
        "evidence": evidence,
        "formal_policy": "章节基于同一全书原文独立标注；跨章关联随本章提交，未确定及互斥判断进入案例池",
    }


def dialogue_continuity(session: Session, run_id: str) -> dict[str, dict[str, Any]]:
    """消费已释放边界下的有效归因；有争议时不把任一方伪装成确认值"""
    cutoff = released_cutoff(session, run_id)
    if cutoff is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in session.execute(
        select(CutoffPartition).where(
            CutoffPartition.cutoff_hash == cutoff.cutoff_hash,
            CutoffPartition.partition_key.startswith("dialogue:"),
        )
    ).scalars():
        claims = [item for item in row.projection["assertions"] if item["kind"] == "dialogue_attribution"]
        if not claims:
            continue
        value: dict[str, Any] = {}
        for claim in claims:
            if claim["outcome"] == "accepted" and not row.projection["contested"]:
                value.update(
                    {
                        field: claim["payload"][field]
                        for field in ("speaker_entity_id", "tone")
                        if field in claim["payload"]
                    }
                )
        result[row.partition_key.removeprefix("dialogue:")] = {
            "value": value,
            "state": "contested" if row.projection["contested"] else "resolved",
            "claims": claims,
            "cutoff_hash": cutoff.cutoff_hash,
        }
    return result
