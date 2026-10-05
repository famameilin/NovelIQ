"""
分区投影的语义命令派生 helpers

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 pipeline_projection.py 提取命令派生静态逻辑
（原 _dependency_manifest/_blocked_parent_ids/_conflict_target/
_derive_domain_commands/_derive_chapter_links/_append_domain_command/
_register_conflict_cases）
说明: 纯结构搬移，不改派生逻辑与防御代码；静态方法改为模块函数
（去下划线前缀），主文件 PipelineProjectionRepository 保留状态机方法，
在 seal 等处直接调用这些模块函数。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest
from src.storage.models import CaseHead, ContinuityCase, SemanticCommand
from src.storage.repositories.pipeline_cases import register_case_identity
from src.storage.repositories.pipeline_identity import identity_conflicts, identity_rejected_ids
from src.storage.repositories.pipeline_links import resolve_cross_chapter_links
from src.storage.repositories.pipeline_reducers import reduce_partition


def blocked_parent_ids(commands: list[SemanticCommand]) -> list[str]:
    groups: dict[str, list[SemanticCommand]] = defaultdict(list)
    for command in commands:
        if command.command_kind == "case_resolution":
            groups[command.partition_key].append(command)
    return sorted(command.command_id for group in groups.values() if reduce_partition(group)[0]["contested"]
                  for command in group)


def dependency_manifest(commands: list[SemanticCommand]) -> dict[str, list[str]]:
    """互斥实体类型不是可用端点；依赖方同样保留争议而不是物化悬空边"""
    entity_types: dict[str, set[str]] = defaultdict(set)
    for command in commands:
        if command.command_kind == "entity_mention":
            entity_types[command.payload["entity_id"]].add(command.payload["entity_type"])
    selections: dict[str, set[str]] = defaultdict(set)
    blocked = set(blocked_parent_ids(commands))
    active = [command for command in commands if command.parent_command_id not in blocked]
    for command in active:
        if command.command_kind == "entity_type_resolution":
            selections[command.payload["entity_id"]].add(command.payload["entity_type"])
    entity_types.update(selections)
    return {
        "entities": sorted(name for name, types in entity_types.items() if len(types) == 1),
        "ambiguous_entities": sorted(name for name, types in entity_types.items() if len(types) > 1),
        "events": sorted({command.payload["node_id"] for command in commands if command.command_kind == "event"}),
        "identity_conflicts": identity_conflicts(active),
        "identity_rejected_ids": identity_rejected_ids(active),
        "unresolved_link_ids": sorted(command.command_id
                                      for command, _reason in resolve_cross_chapter_links(active)[1]),
    }


def conflict_target(partition: str, command: SemanticCommand) -> dict[str, Any]:
    if command.command_kind == "entity_mention":
        return {"domain": "entity", "entity_id": command.payload["entity_id"], "partition_key": partition}
    if command.command_kind == "identity_binding":
        return {"domain": "entity", "entity_id": command.payload["entity_id"], "partition_key": partition}
    return {"partition_key": partition}


def append_domain_command(session: Session, parent: SemanticCommand,
                          kind: str, partition: str, payload: dict[str, Any]) -> None:
    command_id = stable_digest(parent.command_id, kind, partition, payload)
    session.execute(insert(SemanticCommand).values(
        command_id=command_id, run_id=parent.run_id, origin_annotation_id=parent.origin_annotation_id,
        origin_chapter_id=parent.origin_chapter_id, origin_chapter_sequence=parent.origin_chapter_sequence,
        command_path=f"derived/{command_id}", command_kind=kind, partition_key=partition,
        effective_document_position=parent.effective_document_position, payload=payload,
        payload_hash=stable_digest(payload), evidence_ids=parent.evidence_ids,
        independence_keys=parent.independence_keys, parent_command_id=parent.command_id,
        author_work_id=parent.author_work_id,
    ).on_conflict_do_nothing(index_elements=[SemanticCommand.command_id]))


def derive_domain_commands(session: Session, commands: list[SemanticCommand]) -> None:
    """只把已收敛案例编译成子命令；冲突双方保留原命令但不产生领域写入"""
    groups: dict[str, list[SemanticCommand]] = defaultdict(list)
    for command in commands:
        if command.command_kind == "case_resolution":
            groups[command.partition_key].append(command)
    for group in groups.values():
        projection, _ = reduce_partition(group)
        if projection["contested"]:
            continue
        for parent in group:
            domain = parent.payload.get("domain_command")
            if parent.payload["state"] != "resolved" or domain is None:
                continue
            entries = domain[2]["commands"] if domain[0] == "batch" else [domain]
            for kind, partition, payload in entries:
                append_domain_command(session, parent, kind, partition, payload)


def derive_chapter_links(session: Session, commands: list[SemanticCommand]) -> None:
    """全部章节只做确定性连接，未确定目标保存双方精确证据后正常发布"""
    resolved, unsettled = resolve_cross_chapter_links(commands)
    for parent, kind, partition, payload in resolved:
        append_domain_command(session, parent, kind, partition, payload)
    for parent, reason in unsettled:
        assert parent.origin_chapter_id is not None
        target = {**parent.payload["source_object"], "link_command_id": parent.command_id,
                  "source_ref": parent.payload["source"], "target_ref": parent.payload["target"]}
        register_case_identity(
            session, run_id=parent.run_id, case_id=stable_digest("unsettled-link", parent.command_id),
            issue_kind="跨章关联未确定", description=reason, keys=[parent.payload["record_id"]],
            target_ref=target, evidence_ids=list(parent.evidence_ids),
            annotation_id=parent.origin_annotation_id, chapter_id=parent.origin_chapter_id,
        )


def register_conflict_cases(session: Session, run_id: str, commands: list[SemanticCommand]) -> None:
    """领域冲突变成稳定案例，不以任意命令到达顺序选赢家"""
    groups: dict[str, list[SemanticCommand]] = defaultdict(list)
    blocked = set(blocked_parent_ids(commands))
    for command in commands:
        if command.parent_command_id not in blocked and command.command_kind != "case_resolution":
            groups[command.partition_key].append(command)
    dependencies = dependency_manifest(commands)
    for partition, group in groups.items():
        projection, _ = reduce_partition(group, dependencies=dependencies)
        if not projection["contested"]:
            continue
        targets = [command for command in group if command.command_kind in {"entity_mention", "identity_binding"}]
        first = min(targets or group, key=lambda row: (row.origin_chapter_sequence or 0, row.command_id))
        case_id = stable_digest("projection-conflict", run_id, partition)
        session.execute(insert(ContinuityCase).values(
            case_id=case_id, run_id=run_id, case_key=case_id, issue_kind="领域冲突",
            description=f"分区 {partition} 存在互斥主张，双方证据保留在案例池",
            search_keys=[partition], target_ref=conflict_target(partition, first),
            source_evidence=sorted({evidence_id for command in group for evidence_id in command.evidence_ids}),
            originating_annotation_id=first.origin_annotation_id,
            originating_chapter_id=first.origin_chapter_id,
        ).on_conflict_do_nothing(index_elements=[ContinuityCase.case_id]))
        session.flush()
        head = session.get(CaseHead, case_id)
        state_hash = stable_digest("contested", projection)
        if head is None:
            session.add(CaseHead(case_id=case_id, state="contested", state_hash=state_hash))
        elif head.state_hash != state_hash:
            head.state, head.state_hash = "contested", state_hash
            head.head_epoch += 1
