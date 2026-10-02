"""按文档位置重算单个语义分区，不依赖任务的到达顺序"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.agents.annotation.identity import stable_digest
from src.storage.models import SemanticCommand
from src.storage.repositories.pipeline_identity import identity_rejected_ids


def reduce_partition(
    commands: Sequence[SemanticCommand], *, dependencies: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    ordered = sorted(commands, key=lambda row: (
        row.origin_chapter_sequence or 0, row.effective_document_position.get("paragraph_id") or 0,
        int(row.command_kind in {"relation_change", "dialogue_attribution", "event_link", "character_observation"}),
        row.command_path, row.command_id,
    ))
    assertions: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, str] = {}
    for command in ordered:
        payload = command.payload
        equivalent = payload
        if command.command_kind == "case_resolution":
            equivalent = {"case_id": payload["case_id"], "state": payload["state"],
                          "resolution": payload.get("resolution", {})}
        position_key = None if command.command_kind in {
            "case_resolution", "dialogue_attribution", "event_link", "identity_binding", "entity_type_resolution",
            "identity_arbitration",
        } else command.origin_chapter_id
        key = stable_digest(command.command_kind, position_key, equivalent)
        assertion = assertions.setdefault(key, {
            "kind": command.command_kind, "payload": payload, "command_ids": [], "evidence_ids": [],
            "independence_keys": [], "chapter_sequence": command.origin_chapter_sequence,
            "chapter_id": command.origin_chapter_id, "annotation_id": command.origin_annotation_id,
            "position": command.effective_document_position,
        })
        assertion["command_ids"].append(command.command_id)
        assertion["evidence_ids"] = sorted(set(assertion["evidence_ids"]) | set(command.evidence_ids))
        assertion["independence_keys"] = sorted(set(assertion["independence_keys"]) | set(command.independence_keys))
        outcomes[command.command_id] = "accepted"
    values = list(assertions.values())
    rejected = set(identity_rejected_ids(commands))
    if dependencies is not None:
        rejected.update(dependencies.get("identity_rejected_ids", []))
    for command_id in rejected:
        if command_id in outcomes:
            outcomes[command_id] = "rejected"
    effective_values = [value for value in values if not set(value["command_ids"]).issubset(rejected)]
    resolutions = [value for value in values if value["kind"] == "case_resolution"]
    resolved_values = {stable_digest(value["payload"].get("resolution")) for value in resolutions
                       if value["payload"].get("state") == "resolved"}
    contested = len(resolved_values) > 1 or any(value["payload"].get("state") == "contested" for value in resolutions)
    mentions = [value for value in values if value["kind"] == "entity_mention"]
    selected_types = {value["payload"]["entity_type"] for value in values if value["kind"] == "entity_type_resolution"}
    contested = contested or len(selected_types or {value["payload"]["entity_type"] for value in mentions}) > 1
    identity_claims = [value for value in effective_values if value["kind"] == "identity_binding"]
    choices = {value["payload"]["selected_command_id"] for value in values if value["kind"] == "identity_arbitration"}
    contested = contested or len(choices) > 1
    same_targets = {value["payload"]["canonical_entity_id"] for value in identity_claims
                    if value["payload"]["identity_kind"] == "same"}
    different_targets = {value["payload"]["canonical_entity_id"] for value in identity_claims
                         if value["payload"]["identity_kind"] == "different"}
    contested = contested or bool(same_targets & different_targets)
    attributions = [value for value in values if value["kind"] == "dialogue_attribution"]
    for field in ("speaker_entity_id", "tone"):
        contested = contested or len({value["payload"][field] for value in attributions
                                     if field in value["payload"]}) > 1
    links = [value for value in values if value["kind"] == "event_link"]
    contested = contested or len({value["payload"].get("edge_type", "foreshadowing") for value in links}) > 1
    relation_changes = [value for value in values if value["kind"] == "relation_change"]
    changes_at_position: dict[str, set[str]] = {}
    for value in relation_changes:
        position = stable_digest(value["chapter_sequence"], value["position"])
        changes_at_position.setdefault(position, set()).add(stable_digest(value["payload"]))
    contested = contested or any(len(changes) > 1 for changes in changes_at_position.values())
    if contested:
        for value in effective_values:
            if value["kind"] in {"case_resolution", "entity_mention", "dialogue_attribution", "relation_change",
                                 "event_link", "identity_binding", "entity_type_resolution", "identity_arbitration"}:
                for command_id in value["command_ids"]:
                    outcomes[command_id] = "conflict"
    if dependencies is not None:
        entities = set(dependencies.get("entities", []))
        ambiguous_entities = set(dependencies.get("ambiguous_entities", []))
        events = set(dependencies.get("events", []))
        identity_conflict_ids = set(dependencies.get("identity_conflicts", []))
        unresolved_link_ids = set(dependencies.get("unresolved_link_ids", []))
        for value in effective_values:
            payload = value["payload"]
            missing = False
            ambiguous = False
            if value["kind"] in {"local_relation", "relation_change"}:
                ambiguous = any(payload[endpoint] in ambiguous_entities
                                for endpoint in ("from_entity_id", "to_entity_id"))
                missing = any(payload[endpoint] not in entities for endpoint in ("from_entity_id", "to_entity_id"))
            elif value["kind"] == "event_link":
                missing = any(payload[endpoint] not in events for endpoint in ("event_id", "root_event_id"))
            elif value["kind"] == "event" and payload.get("parent_node_id"):
                missing = payload["parent_node_id"] not in events
            elif value["kind"] == "character_observation":
                ambiguous = payload["entity_id"] in ambiguous_entities
                missing = payload["entity_id"] not in entities
            elif value["kind"] == "identity_binding":
                ambiguous = any(payload[field] in ambiguous_entities for field in ("entity_id", "canonical_entity_id"))
                missing = any(payload[field] not in entities for field in ("entity_id", "canonical_entity_id"))
            ambiguous = ambiguous or any(command_id in identity_conflict_ids for command_id in value["command_ids"])
            if any(command_id in unresolved_link_ids for command_id in value["command_ids"]):
                for command_id in value["command_ids"]:
                    outcomes[command_id] = "pending_dependency"
            elif ambiguous:
                contested = True
                for command_id in value["command_ids"]:
                    outcomes[command_id] = "conflict"
            elif missing and not contested:
                for command_id in value["command_ids"]:
                    outcomes[command_id] = "pending_dependency"
    for value in values:
        value["outcome"] = outcomes[value["command_ids"][0]]
    return {"assertions": values, "contested": contested,
            "pending_dependency": any(state == "pending_dependency" for state in outcomes.values())}, outcomes
