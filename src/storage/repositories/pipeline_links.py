"""原文锚点连接独立章节结果，不调用模型或改写章节载荷"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.agents.annotation.identity import stable_digest
from src.agents.annotation.schema import RELATION_DEFINITIONS
from src.storage.models import SemanticCommand
from src.storage.repositories.pipeline_identity import identity_conflicts, identity_rejected_ids

DomainLink = tuple[SemanticCommand, str, str, dict[str, Any]]


def _endpoint_identity(
    commands: list[SemanticCommand], links: list[DomainLink],
) -> tuple[dict[str, str], set[str]]:
    """关系连接只使用无争议的身份结论，名称相同不构成身份依据"""
    identities = {command.command_id: command for command in commands}
    for parent, kind, partition, payload in links:
        if kind == "identity_binding":
            command_id = stable_digest(parent.command_id, kind, partition, payload)
            identities[command_id] = SemanticCommand(
                command_id=command_id, command_kind=kind, partition_key=partition, payload=payload,
            )
    values = list(identities.values())
    blocked = set(identity_conflicts(values))
    rejected = set(identity_rejected_ids(values))
    contested: set[str] = set()
    parents: dict[str, str] = {}

    def root(identifier: str) -> str:
        while identifier in parents and parents[identifier] != identifier:
            identifier = parents[identifier]
        return identifier

    for command in values:
        payload = command.payload
        endpoints = None
        if command.command_kind == "identity_binding":
            endpoints = payload["entity_id"], payload["canonical_entity_id"]
            same = payload["identity_kind"] == "same"
        elif command.command_kind in {"local_relation", "relation_change"}:
            endpoints = payload["from_entity_id"], payload["to_entity_id"]
            same = payload["relation_type"] == "同一人物" and payload.get("change_kind", "assert") not in {
                "break", "retract",
            }
        if endpoints is None or command.command_id in rejected:
            continue
        if command.command_id in blocked:
            contested.update(endpoints)
        elif same:
            source_root, target_root = (root(identifier) for identifier in endpoints)
            if source_root != target_root:
                parents[max(source_root, target_root)] = min(source_root, target_root)
    return {identifier: root(identifier) for identifier in parents}, contested


def resolve_cross_chapter_links(
    commands: list[SemanticCommand],
) -> tuple[list[DomainLink], list[tuple[SemanticCommand, str]]]:
    """只连接同领域唯一原文目标；缺失或歧义保留为案例，不选任意赢家"""
    anchors: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
    entities: dict[str, dict[str, Any]] = {}
    events: dict[str, SemanticCommand] = {}
    sequences = {command.origin_chapter_id: command.origin_chapter_sequence for command in commands
                 if command.origin_chapter_id is not None}
    for command in commands:
        payload = command.payload
        if command.command_kind == "object_anchor":
            reference = payload["source"]
            anchors[reference["chapter_id"], reference["paragraph_id"], payload["object"]["domain"]].append(payload)
        elif command.command_kind == "entity_mention":
            entities[payload["entity_id"]] = payload
        elif command.command_kind == "event":
            events[payload["node_id"]] = command

    resolved: list[DomainLink] = []
    unsettled: list[tuple[SemanticCommand, str]] = []
    relations: list[tuple[SemanticCommand, dict[str, Any]]] = []
    for command in commands:
        if command.command_kind != "cross_chapter_link":
            continue
        payload = command.payload
        source = payload["source_object"]
        reference = payload["target"]
        matches: dict[str, dict[str, Any]] = {}
        for anchor in anchors[reference["chapter_id"], reference["paragraph_id"], source["domain"]]:
            span = anchor["source"]
            if reference["char_start"] <= span["char_start"] < span["char_end"] <= reference["char_end"]:
                matches[stable_digest(anchor["object"])] = anchor["object"]
        if len(matches) != 1:
            unsettled.append((command, "目标原文没有对应对象" if not matches else "目标原文对应多个对象"))
            continue
        target = next(iter(matches.values()))
        kind = payload["kind"]
        if kind in {"same_entity", "different_entity"}:
            if source["domain"] != "entity":
                raise ValueError("身份关联必须引用实体")
            source_id, target_id = sorted((source["entity_id"], target["entity_id"]))
            if kind == "same_entity" and entities[source_id]["entity_type"] != entities[target_id]["entity_type"]:
                unsettled.append((command, "同一实体两端的类型互斥"))
                continue
            resolved.append((command, "identity_binding", f"alias:{source_id}", {
                "entity_id": source_id, "canonical_entity_id": target_id,
                "identity_kind": "same" if kind == "same_entity" else "different", "origin": "chapter_link",
            }))
        elif kind in {"causal", "foreshadowing"}:
            if source["domain"] != "event":
                raise ValueError("因果与伏笔关联必须引用事件")
            first, second = sorted((events[source["event_id"]], events[target["event_id"]]),
                                   key=lambda row: row.origin_chapter_sequence or 0)
            if kind == "foreshadowing" and not first.payload.get("is_foreshadow_setup"):
                unsettled.append((command, "照应的前端不是伏笔埋设事件"))
                continue
            source_id, target_id = first.payload["node_id"], second.payload["node_id"]
            partition = f"event_edge:{stable_digest(source_id, target_id)}"
            resolved.append((command, "event_link", partition, {
                "root_event_id": source_id, "event_id": target_id,
                "edge_type": kind, "origin": "chapter_link",
            }))
        elif kind == "relation_change":
            relations.append((command, target))
        else:
            raise ValueError("未知跨章关联类型")
    identity, contested = _endpoint_identity(commands, resolved) if relations else ({}, set())
    for command, target in relations:
        payload = command.payload
        source = payload["source_object"]
        if source["domain"] != "relation" or source["relation_type"] != target["relation_type"]:
            unsettled.append((command, "关系变化两端的关系类型不一致"))
            continue
        source_ids = tuple(source[field] for field in ("from_entity_id", "to_entity_id"))
        target_ids = tuple(target[field] for field in ("from_entity_id", "to_entity_id"))
        if contested.intersection((*source_ids, *target_ids)):
            unsettled.append((command, "关系变化端点的身份存在互斥判断"))
            continue
        source_pair = tuple(identity.get(identifier, identifier) for identifier in source_ids)
        target_pair = tuple(identity.get(identifier, identifier) for identifier in target_ids)
        if RELATION_DEFINITIONS[source["relation_type"]]["directionality"] == "bidirectional":
            source_pair, target_pair = tuple(sorted(source_pair)), tuple(sorted(target_pair))
        if source_pair != target_pair:
            unsettled.append((command, "关系变化两端未确认是同一关系"))
            continue
        if (sequences[payload["source"]["chapter_id"]] or 0) <= (sequences[payload["target"]["chapter_id"]] or 0):
            unsettled.append((command, "关系变化没有指向此前章节的关系"))
            continue
        relationship = {key: value for key, value in source.items() if key != "domain"}
        partition = f"relation:{stable_digest(source['from_entity_id'], source['to_entity_id'],
                                             source['relation_type'], fold_text=True)}"
        resolved.append((command, "relation_change", partition, {
            **relationship, "change_kind": payload["change_kind"],
            "prior_relation": target, "origin": "chapter_link",
        }))
    return resolved, unsettled
