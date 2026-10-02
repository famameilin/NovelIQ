"""跨章关系连接只接受已确认身份、方向一致的两端"""

from __future__ import annotations

from typing import Any

import pytest

from src.agents.annotation.identity import stable_digest
from src.storage.models import SemanticCommand
from src.storage.repositories.pipeline_links import resolve_cross_chapter_links


def _command(kind: str, payload: dict[str, Any], *, chapter_id: int = 1) -> SemanticCommand:
    return SemanticCommand(command_id=stable_digest(kind, payload), command_kind=kind,
                           partition_key=stable_digest(kind), payload=payload,
                           origin_chapter_id=chapter_id, origin_chapter_sequence=chapter_id)


@pytest.mark.parametrize("mode", ["connected", "unproven", "conflicted", "bidirectional", "directional", "future"])
@pytest.mark.parametrize("reverse_commands", [False, True])
def test_relation_links_require_matching_identity_endpoints(mode: str, reverse_commands: bool) -> None:
    source_ref = {"chapter_id": 2, "paragraph_id": 20, "char_start": 0, "char_end": 6}
    target_ref = {"chapter_id": 1 if mode != "future" else 3, "paragraph_id": 10, "char_start": 0, "char_end": 6}
    relation_type = "领导" if mode == "directional" else "友情"
    source = {"domain": "relation", "from_entity_id": "a", "to_entity_id": "b", "relation_type": relation_type}
    target = {"domain": "relation", "from_entity_id": "c", "to_entity_id": "d", "relation_type": relation_type}
    if mode in {"bidirectional", "directional"}:
        target.update(from_entity_id="d", to_entity_id="c")
    commands = [
        _command("cross_chapter_link", {"kind": "relation_change", "source_object": source,
                                       "source": source_ref, "target": target_ref, "change_kind": "weaken"},
                 chapter_id=2),
        _command("object_anchor", {"object": target, "source": target_ref}, chapter_id=target_ref["chapter_id"]),
        _command("identity_binding", {"entity_id": "b", "canonical_entity_id": "d", "identity_kind": "same"}),
    ]
    if mode != "unproven":
        commands.append(_command("identity_binding", {
            "entity_id": "a", "canonical_entity_id": "c", "identity_kind": "same",
        }))
    if mode == "conflicted":
        commands.append(_command("identity_binding", {
            "entity_id": "a", "canonical_entity_id": "c", "identity_kind": "different",
        }))
    resolved, unsettled = resolve_cross_chapter_links(list(reversed(commands)) if reverse_commands else commands)
    if mode in {"connected", "bidirectional"}:
        assert not unsettled and len(resolved) == 1
        parent, kind, _, payload = resolved[0]
        assert parent.command_kind == "cross_chapter_link" and kind == "relation_change"
        assert payload["prior_relation"] == target and payload["change_kind"] == "weaken"
    else:
        assert not resolved and len(unsettled) == 1
        assert unsettled[0][0].command_kind == "cross_chapter_link"
