"""冻结诊断报告、叙事组织与案例贡献，交给 Storage 完整发布并确认内存状态"""

from __future__ import annotations

import unicodedata
from typing import Any, cast

from loguru import logger

from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import CONTRACT_VERSION, NarrativeOrganization, snapshot_digest
from src.storage import Storage


def _character_entity_ids(session: Storage, run_id: str, names: list[str]) -> dict[str, str]:
    """诊断名单引用同 run 的正式 character；名称比较沿用 NFC/strip/casefold 身份合同"""
    if not names:
        return {}
    rows = session.reads.agents_diagnosis_persistence_character_entity_ids_1(run_id)
    by_name = {unicodedata.normalize("NFC", row.canonical_name).strip().casefold(): row.entity_id for row in rows}
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


def _published_report(session: Storage, run_id: str) -> Any:
    """本 run 的正式诊断报告（经整轮会话取得运行归属）；多份报告是数据错误"""
    rows = list(session.reads.agents_diagnosis_persistence_published_report_1(run_id))
    if len(rows) > 1:
        raise ValueError("同一运行存在多份正式诊断报告，禁止覆盖或挑选其中一份")
    return rows[0] if rows else None


def _verify_replay(session: Storage, run_id: str, report: Any, analysis: AgentAnalysis) -> None:
    """提交回执不明时只核验已发布结果：报告投影、冻结快照与正式事件身份必须一致"""
    from src.diagnosis.read import fetch_diagnosis_payload
    from src.event_trees.organization import _run_events

    stored = fetch_diagnosis_payload(session, run_id)
    comparable = set(AgentAnalysis.model_fields) - {"narrative_organization"}
    stored_payload = {key: value for key, value in (stored or {}).items() if key in comparable}
    incoming = {key: value for key, value in analysis.model_dump(mode="json").items() if key in comparable}
    if snapshot_digest(stored_payload) != snapshot_digest(incoming):
        raise ValueError("已发布诊断与冻结贡献不一致，禁止覆盖")
    organization = cast(NarrativeOrganization, analysis.narrative_organization)
    if (
        report.identity_snapshot != organization.identity_snapshot
        or report.structure_snapshot != organization.structure_snapshot
    ):
        raise ValueError("已发布诊断的冻结快照与本次提交不一致，禁止覆盖")
    published = set(_run_events(session, run_id))
    if published != {item.event_id for item in organization.events}:
        raise ValueError("已发布完整事件身份与本次提交不一致，禁止覆盖")


def _save_case_writes(
    session: Storage, run_id: str, output_id: str, *, graph: Any, writers: Any, candidates: list[Any]
) -> tuple[tuple, tuple]:
    """冻结案例的事实图贡献与对话归因，使用正式候选身份定位对话"""
    import json

    from src.fact_graph.contributions import FactContribution

    fact_inputs, changes = [], []
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
            run_id, author, int(writer.current_chapter_id), (), json.dumps(facts, ensure_ascii=False), "[]"
        )
        fact_inputs.append(graph.prepare_save(frozen))
        for index, item in sorted(writer.dialogue.written_dialogues.items()):
            candidate = candidates[index - 1] if 0 < index <= len(candidates) else None
            if candidate is None:
                raise ValueError(f"write_dialogue candidate_index={index} 超出候选目录")
            changes.append(
                {
                    "candidate_key": candidate.candidate_key,
                    "current_attribution_execution_id": author,
                    "speaker_entity_id": graph.entity_id(item.speaker, "character") if item.speaker else None,
                    "tone": str(item.tone) if item.tone else None,
                    "is_inner_monologue": item.verdict == "inner_monologue",
                }
            )
    return tuple(fact_inputs), tuple(changes)


def save_diagnosis_result(
    session: Storage,
    run_id: str,
    analysis: AgentAnalysis,
    *,
    case_pool=None,
    case_graph=None,
    case_writers=None,
    case_candidates=None,
) -> None:
    """诊断 Agent 保存实际诊断结果，并把案例采纳绑定到正式报告身份"""
    import json

    from src.event_trees.organization import run_declaration_ids, validate_organization
    from src.storage import new_id
    from src.storage.records.cases import CaseSave
    from src.storage.records.diagnosis_save import DiagnosisPublish

    organization = analysis.narrative_organization
    if organization is None or not organization.source_execution_id:
        raise ValueError("诊断结果缺少全书叙事组织或真实会话身份")
    existing = _published_report(session, run_id)
    if existing is not None:
        _verify_replay(session, run_id, existing, analysis)
        from src.event_trees.read.organization import EventTreeQuery

        EventTreeQuery(session, run_id).fetch()
        if case_pool is not None:
            warnings = session.diagnosis.saved_case_warnings(run_id, existing.report_id)
            for author in sorted(case_pool.executions):
                case_pool.save_warnings[author] = warnings.get(author, [])
                case_pool.confirm(author)
        return
    validate_organization(session, run_id, organization)
    report_id = new_id()
    keys = (
        "diagnosis",
        "value_logic_type",
        "value_logic_reason",
        "power_stance_score",
        "power_stance_reason",
        "common_people_dignity",
        "dignity_reason",
        "cultural_depth_score",
        "cultural_depth_reason",
        "narrative_arc_type",
        "focus_structure",
        "theme_color",
    )
    record = {
        "report_id": report_id,
        "session_id": organization.source_execution_id,
        "contract_version": CONTRACT_VERSION,
        "identity_snapshot": organization.identity_snapshot,
        "structure_snapshot": organization.structure_snapshot,
        **{key: getattr(analysis, key) for key in keys},
    }
    assessments = []

    def entry(**fields):
        assessments.append({"assessment_id": new_id(), "report_id": report_id, **fields})

    for ordinal, label in enumerate(analysis.genre_labels):
        entry(ordinal=ordinal, genre_label=label)
    for ordinal, label in enumerate(analysis.style_labels):
        entry(ordinal=ordinal, style_label=label)
    for topic_id, label in analysis.topic_labels.items():
        entry(topic_id=int(topic_id), topic_label=label)
    scores = _character_entity_ids(session, run_id, list(analysis.arc_scores))
    for name, score in analysis.arc_scores.items():
        entry(scored_entity_id=scores[name], character_score=float(score))
    for cast_role, members in (
        ("focus", analysis.focus_characters),
        ("main", analysis.main_characters),
        ("core", analysis.core_cast),
    ):
        resolved = _character_entity_ids(session, run_id, list(members))
        for ordinal, name in enumerate(members):
            entry(cast_role=cast_role, ordinal=ordinal, cast_entity_id=resolved[name])
    facts, updates = (
        _save_case_writes(
            session, run_id, report_id, graph=case_graph, writers=case_writers, candidates=case_candidates or []
        )
        if case_graph is not None and case_writers
        else ((), ())
    )
    authors = sorted(case_pool.executions) if case_pool is not None else []
    cases = tuple(
        CaseSave(
            run_id,
            author,
            json.dumps(
                {
                    "created_case_ids": sorted(case_pool.created.get(author, set())),
                    "registrations": {key: case_pool.cases[key] for key in case_pool.registrations.get(author, set())},
                    "deliveries": case_pool.deliveries.get(author, []),
                },
                ensure_ascii=False,
            ),
        )
        for author in authors
    )
    request = DiagnosisPublish(
        run_id,
        organization.source_execution_id,
        record,
        tuple(assessments),
        organization.model_dump_json(),
        frozenset(run_declaration_ids(session, run_id)),
        facts,
        updates,
        cases,
    )
    result = session.diagnosis.publish(request)
    if result["warnings"]:
        logger.warning("diagnosis case save warnings: {}", result["warnings"])
    if case_pool is not None:
        for author in authors:
            case_pool.save_warnings[author] = result["warnings_by_author"][author]
            case_pool.confirm(author)
