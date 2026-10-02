"""
创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分 src/workflows/pipeline_materialization.py（领域物化段）
说明: 承接 CutoffMaterializer 的三个领域物化方法——身份合并（含 root/merge
      闭包）、事件树（含事件边登记与拓扑环检测）与关系物化——以 materializer
      实例为首个参数的模块函数实现；主类同名方法改为薄委托，行为、调用
      时序与事务语义完全不变。
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

from src.agents.annotation.identity import stable_uuid
from src.agents.annotation.schema import RELATION_DEFINITIONS
from src.storage.models import EventEdge, EventNode, GraphEntity, GraphRelation, RelationState
from src.storage.repositories.event_order import event_position
from src.storage.repositories.graph.identity import relation_id as stable_relation_id

if TYPE_CHECKING:
    from src.workflows.pipeline_materialization import CutoffMaterializer


def materialize_identity(m: CutoffMaterializer) -> None:
    """全 cutoff 只选举一次代表；正式名称、UUID 与事实不随绑定变化"""
    by_id = {entity.entity_id: entity for entity in m.entities.values()}
    parents = {identifier: identifier for identifier in by_id}
    assertions = [assertion for partition in m.partitions for assertion in partition.projection["assertions"]
                  if assertion["kind"] == "identity_binding"]
    contested = {identifier for assertion in assertions if assertion["outcome"] == "conflict"
                 for identifier in (assertion["payload"]["entity_id"], assertion["payload"]["canonical_entity_id"])}
    contested.update(entity.entity_id for entity in by_id.values()
                     if entity.attributes.get("identity_status") == "contested")

    def root(identifier: str) -> str:
        while parents[identifier] != identifier:
            identifier = parents[identifier]
        return identifier

    def merge(source: str, target: str) -> None:
        if source not in parents or target not in parents or source in contested or target in contested:
            return
        source_root, target_root = root(source), root(target)
        if source_root != target_root:
            parents[source_root] = target_root

    # 身份只能读取本 cutoff 的 Agent 主张，不能继承上次物化的关系状态
    for partition in m.partitions:
        if not partition.partition_key.startswith("relation:"):
            continue
        active = False
        endpoints: tuple[str, str] | None = None
        for assertion in partition.projection["assertions"]:
            payload = assertion["payload"]
            if (assertion["kind"] not in {"local_relation", "relation_change"}
                or assertion["outcome"] != "accepted" or payload["relation_type"] != "同一人物"):
                continue
            endpoints = payload["from_entity_id"], payload["to_entity_id"]
            change = payload.get("change_kind", "assert")
            if change in {"break", "retract"}:
                active = False
            elif change != "weaken":
                active = True
        if active and endpoints is not None:
            source, target = sorted(endpoints, reverse=True)
            merge(source, target)
    different: dict[str, set[str]] = defaultdict(set)
    evidence: dict[str, set[str]] = defaultdict(set)
    for assertion in assertions:
        payload = assertion["payload"]
        source, target = payload["entity_id"], payload["canonical_entity_id"]
        if assertion["outcome"] != "accepted" or source not in by_id or target not in by_id:
            continue
        if payload["identity_kind"] == "same":
            merge(source, target)
        elif payload["identity_kind"] == "different":
            different[source].add(target)
            different[target].add(source)
        evidence[source].update(assertion["evidence_ids"])
        evidence[target].update(assertion["evidence_ids"])
        m.fact(assertion, domain="identity", predicate=payload["identity_kind"],
               subject=by_id[source], target=by_id[target], content=payload)
    clusters: dict[str, list[str]] = defaultdict(list)
    for identifier in parents:
        clusters[root(identifier)].append(identifier)
    for members in clusters.values():
        representative = min(members, key=lambda identifier: (
            m.chapters[by_id[identifier].first_seen_chapter].sequence,
            identifier,
        ))
        for identifier in members:
            entity = by_id[identifier]
            entity.attributes = {**entity.attributes,
                "canonical_entity_id": representative, "identity_cutoff": m.cutoff.cutoff_hash,
                "is_representative": len(members) > 1 and identifier == representative,
                "identity_status": "contested" if identifier in contested else (
                    "resolved" if evidence[identifier] else "known"
                ), "different_entity_ids": sorted(different[identifier]),
                "identity_evidence_ids": sorted(evidence[identifier]),
            }


def materialize_events(m: CutoffMaterializer) -> None:
    for partition in m.partitions:
        if not partition.partition_key.startswith("event_tree:"):
            continue
        for assertion in partition.projection["assertions"]:
            if assertion["kind"] != "event" or assertion["outcome"] != "accepted":
                continue
            payload = assertion["payload"]
            event_id = payload["node_id"]
            if event_id not in m.events:
                anchor = m.paragraphs.get(payload.get("evidence_paragraph_id"))
                if anchor is None or anchor.chapter_id != assertion["chapter_id"]:
                    raise ValueError("正式事件必须绑定本章段落证据")
                root = payload.get("is_foreshadow_setup", False)
                row = EventNode(
                    event_id=event_id, run_id=m.cutoff.run_id, chapter_id=assertion["chapter_id"],
                    chapter_order=m.orders[assertion["chapter_id"]], description=payload["description"],
                    participants=[{"role": item["role"], "entity": m.descriptor(m.entity(item["entity_id"]))}
                                  for item in payload.get("participants", [])],
                    anchor_paragraph_ids=[anchor.paragraph_id], char_start=anchor.local_start_char,
                    char_end=anchor.local_end_char, evidence=m.text_evidence(assertion), causal_event_refs=[],
                    tree_id=payload["tree_id"], cause_role=payload["cause_role"], is_foreshadowing_root=root,
                    foreshadowing_status="open" if root else None,
                    payoff_likelihood=payload.get("payoff_likelihood"), strength=payload.get("payoff_likelihood"),
                    annotation_id=m.annotations[assertion["chapter_id"]].annotation_id,
                    source_kind="annotation", payload_path=f"commands/{assertion['command_ids'][0]}",
                )
                m.session.add(row)
                m.events[event_id] = row
            m.events[event_id].participants = [
                {"role": item["role"], "entity": m.descriptor(m.entity(item["entity_id"]))}
                for item in payload.get("participants", [])
            ]
            m.fact(assertion, domain="event", predicate="event", content={
                "description": payload["description"],
                "anchor_paragraph_ids": m.events[event_id].anchor_paragraph_ids,
            }, value={"description": payload["description"]}, event_id=event_id)
    m.session.flush()
    for partition in m.partitions:
        for assertion in partition.projection["assertions"]:
            if assertion["outcome"] != "accepted":
                continue
            payload = assertion["payload"]
            if assertion["kind"] == "event_link":
                m.event_edge(assertion, payload["root_event_id"], payload["event_id"],
                             payload.get("edge_type", "foreshadowing"))
            elif assertion["kind"] == "event" and payload.get("parent_node_id"):
                m.event_edge(assertion, payload["parent_node_id"], payload["node_id"], "causal")
    adjacency: dict[str, list[str]] = defaultdict(list)
    degree = dict.fromkeys(m.events, 0)
    for source_id, target_id in m.active_edge_keys:
        adjacency[source_id].append(target_id)
        degree[target_id] += 1
    ready = [event_id for event_id, count in degree.items() if count == 0]
    visited = 0
    while ready:
        event_id = ready.pop()
        visited += 1
        for target_id in adjacency[event_id]:
            degree[target_id] -= 1
            if degree[target_id] == 0:
                ready.append(target_id)
    if visited != len(degree):
        raise ValueError("事件依赖包含环，不能释放截止快照")
    for key, edge in m.edges.items():
        edge.is_active = key in m.active_edge_keys


def event_edge(
    m: CutoffMaterializer, assertion: dict[str, Any], source_id: str, target_id: str, edge_type: str
) -> None:
    source, target = m.events[source_id], m.events[target_id]
    if source_id == target_id:
        raise ValueError("事件不能自依赖")
    if event_position(source, m.event_ordinals) >= event_position(target, m.event_ordinals):
        raise ValueError("事件依赖与文档偏序不一致")
    key = source_id, target_id
    if key in m.active_edge_keys and m.edges[key].edge_type != edge_type:
        raise ValueError("同一事件依赖端点存在互斥边类型")
    m.active_edge_keys.add(key)
    if key not in m.edges:
        row = EventEdge(
            edge_id=stable_uuid(m.cutoff.run_id, "event-edge", source_id, target_id),
            run_id=m.cutoff.run_id, edge_type=edge_type, source_event_id=source_id, target_event_id=target_id,
            source_chapter_id=source.chapter_id, target_chapter_id=target.chapter_id, is_active=True,
            evidence=m.text_evidence(assertion), annotation_id=target.annotation_id,
            payload_path=f"commands/{assertion['command_ids'][0]}",
        )
        m.session.add(row)
        m.edges[key] = row
    if edge_type == "foreshadowing":
        source.foreshadowing_status = "reinforced"


def materialize_relations(m: CutoffMaterializer) -> None:
    effective_state_keys: set[tuple[int, str]] = set()
    grouped: dict[str, tuple[GraphEntity, GraphEntity, str, list[dict[str, Any]]]] = {}
    for partition in m.partitions:
        if not partition.partition_key.startswith("relation:"):
            continue
        assertions = [item for item in partition.projection["assertions"]
                      if item["kind"] in {"local_relation", "relation_change"} and item["outcome"] == "accepted"]
        if not assertions:
            continue
        first = assertions[0]["payload"]
        source, target = m.entity(first["from_entity_id"]), m.entity(first["to_entity_id"])
        if source is None or target is None:
            raise ValueError("已 ACK 关系缺少实体依赖")
        relation_type = first["relation_type"]
        definition = RELATION_DEFINITIONS[relation_type]
        if definition["semantics"] != "same_character":
            source = cast(GraphEntity, m.canonical_entity(source))
            target = cast(GraphEntity, m.canonical_entity(target))
            if source.entity_id == target.entity_id:
                continue
        relation_id = stable_relation_id(m.cutoff.run_id, source.entity_id, target.entity_id,
                                   relation_type, str(definition["directionality"]))
        if relation_id not in grouped:
            grouped[relation_id] = source, target, relation_type, []
        grouped[relation_id][3].extend(assertions)
    for relation_id, (source, target, relation_type, assertions) in sorted(grouped.items()):
        definition = RELATION_DEFINITIONS[relation_type]
        assertions.sort(key=lambda item: (item["chapter_sequence"],
            item["kind"] == "relation_change", item["command_ids"][0]))
        relation = m.relations.get(relation_id)
        if relation is None:
            relation = GraphRelation(relation_id=relation_id, run_id=m.cutoff.run_id,
                                     from_entity_id=source.entity_id, to_entity_id=target.entity_id,
                                     directionality=definition["directionality"],
                                     relation_semantics=definition["semantics"])
            m.session.add(relation)
            m.relations[relation_id] = relation
        attributes: dict[str, Any] = {}
        active = False
        states: dict[int, tuple[dict[str, Any], bool]] = {}
        changes: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for assertion in assertions:
            payload = assertion["payload"]
            chapter_id = assertion["chapter_id"]
            change = payload.get("change_kind", "assert")
            if assertion["kind"] == "local_relation" and active:
                change = "noop"
            before = {"attributes": dict(attributes), "is_active": active, "relation_type": relation_type}
            attributes.update(payload.get("attributes", {}))
            if change in {"assert", "reinforce", "refine", "supersede", "noop"}:
                active = True
                attributes["support_count"] = int(attributes.get("support_count", 0)) + int(change != "noop")
            elif change in {"break", "retract"}:
                active = False
            elif change == "weaken":
                attributes["strength"] = int(attributes.get("strength", 0)) - 1
            fact = m.fact(assertion, domain="relation", predicate=relation_type, subject=source, target=target,
                          content={"relation_id": relation_id, "relation_type": relation_type,
                                   "change_kind": change})
            if assertion["kind"] == "relation_change":
                attributes["continuity_cutoff"] = m.cutoff.cutoff_hash
            changes[chapter_id].append({"change_kind": change, "before": before,
                                       "after": {"attributes": dict(attributes), "is_active": active,
                                                 "relation_type": relation_type}, "fact_id": fact.fact_id,
                                       "chapter_id": chapter_id, "source_kind": fact.source_kind})
            states[chapter_id] = dict(attributes), active
        m.session.flush()
        for chapter_id, chapter_changes in changes.items():
            state_attributes, state_active = states[chapter_id]
            effective_state_keys.add((chapter_id, relation_id))
            row = m.relation_states.get((chapter_id, relation_id))
            if row is None:
                m.session.add(RelationState(run_id=m.cutoff.run_id, chapter_id=chapter_id,
                                           relation_id=relation_id, relation_type=relation_type,
                                           attributes=state_attributes, is_active=state_active,
                                           changes=chapter_changes))
            else:
                row.attributes, row.is_active, row.changes = state_attributes, state_active, chapter_changes
    for key, row in m.relation_states.items():
        if key not in effective_state_keys:
            row.is_active = False
            row.attributes = {**row.attributes, "projection_state": "contested"}
