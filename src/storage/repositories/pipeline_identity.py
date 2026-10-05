"""别名身份约束的确定性收敛，不按到达顺序选择绑定目标"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from src.agents.annotation.identity import stable_digest
from src.storage.models import SemanticCommand


def identity_rejected_ids(commands: Sequence[SemanticCommand]) -> list[str]:
    """已领取冲突案例的显式选择只撤回派生绑定，不删除旧主张"""
    by_id = {command.command_id: command for command in commands}
    selections: dict[str, set[str]] = defaultdict(set)
    for command in commands:
        if command.command_kind == "identity_arbitration":
            selected = by_id.get(command.payload["selected_command_id"])
            if selected is not None:
                selections[command.partition_key].add(stable_digest(
                    selected.payload["entity_id"], selected.payload["canonical_entity_id"],
                    selected.payload["identity_kind"],
                ))
    return sorted(command.command_id for command in commands
                  if command.command_kind == "identity_binding" and len(selections[command.partition_key]) == 1
                  and stable_digest(command.payload["entity_id"], command.payload["canonical_entity_id"],
                                    command.payload["identity_kind"]) not in selections[command.partition_key])


def identity_conflicts(commands: Sequence[SemanticCommand]) -> list[str]:
    """互斥 surface 绑定及同一/不同的传递矛盾保留全部 Evidence"""
    rejected = set(identity_rejected_ids(commands))
    bindings = [command for command in commands
                if command.command_kind == "identity_binding" and command.command_id not in rejected]
    by_surface: dict[str, list[SemanticCommand]] = defaultdict(list)
    for command in bindings:
        by_surface[command.payload["entity_id"]].append(command)
    blocked: set[str] = set()
    for group in by_surface.values():
        same_targets = {command.payload["canonical_entity_id"] for command in group
                        if command.payload["identity_kind"] == "same"}
        different_targets = {command.payload["canonical_entity_id"] for command in group
                             if command.payload["identity_kind"] == "different"}
        if same_targets & different_targets:
            blocked.update(command.command_id for command in group)

    parents: dict[str, str] = {}

    def root(identifier: str) -> str:
        while parents.get(identifier, identifier) != identifier:
            identifier = parents[identifier]
        return identifier

    positives: list[tuple[str, str, str]] = []
    negatives: list[tuple[str, str, str]] = []
    for command in bindings:
        if command.command_id in blocked:
            continue
        payload = command.payload
        entry = payload["entity_id"], payload["canonical_entity_id"], command.command_id
        if payload["identity_kind"] == "same":
            positives.append(entry)
        elif payload["identity_kind"] == "different":
            negatives.append(entry)
    for command in commands:
        if (command.command_kind in {"local_relation", "relation_change"}
                and command.payload.get("relation_type") == "同一人物"
                and command.payload.get("change_kind", "assert") not in {"break", "retract"}):
            positives.append((command.payload["from_entity_id"], command.payload["to_entity_id"],
                              command.command_id))
    for source, target, _command_id in positives:
        source_root, target_root = root(source), root(target)
        if source_root != target_root:
            parents[target_root] = source_root
    conflicting_roots = {root(source) for source, target, _command_id in negatives if root(source) == root(target)}
    for source, target, command_id in [*positives, *negatives]:
        if root(source) in conflicting_roots and root(target) == root(source):
            blocked.add(command_id)
    return sorted(blocked)
