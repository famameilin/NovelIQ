"""分区重算的乱序、等价归并、互斥主张和依赖状态"""

from itertools import permutations

from src.storage.models import SemanticCommand
from src.storage.repositories.pipeline_reducers import reduce_partition


def _command(identifier: str, kind: str, payload: dict, *, chapter: int = 1) -> SemanticCommand:
    return SemanticCommand(command_id=identifier, command_kind=kind, payload=payload,
                           origin_chapter_sequence=chapter, origin_chapter_id=chapter,
                           effective_document_position={}, command_path=identifier,
                           evidence_ids=[f"evidence:{identifier}"], independence_keys=[f"chapter:{chapter}"])


def test_partition_is_identical_for_every_arrival_order() -> None:
    commands = [_command("late", "entity_mention", {"name": "顾霜", "entity_type": "character"}, chapter=3),
                _command("early", "entity_mention", {"name": "顾霜", "entity_type": "character"}),
                _command("middle", "entity_mention", {"name": "顾霜", "entity_type": "character"}, chapter=2)]
    expected = reduce_partition(commands)
    for order in permutations(commands):
        assert reduce_partition(order) == expected
    assert len(expected[0]["assertions"]) == 3


def test_same_case_value_merges_evidence_not_reason_wording() -> None:
    commands = [_command("first", "case_resolution", {"case_id": "case", "state": "resolved",
                                                      "resolution": {"conclusion": "已确认"}, "reason": "证据一"}),
                _command("second", "case_resolution", {"case_id": "case", "state": "resolved",
                                                       "resolution": {"conclusion": "已确认"}, "reason": "证据二"})]
    projection, outcomes = reduce_partition(commands)
    assert not projection["contested"]
    assert len(projection["assertions"]) == 1
    assert projection["assertions"][0]["evidence_ids"] == ["evidence:first", "evidence:second"]
    assert set(outcomes.values()) == {"accepted"}


def test_exclusive_attribution_is_contested_not_last_writer_wins() -> None:
    projection, outcomes = reduce_partition([
        _command("first", "dialogue_attribution", {"speaker_entity_id": "one"}),
        _command("second", "dialogue_attribution", {"speaker_entity_id": "two"}),
    ])
    assert projection["contested"]
    assert set(outcomes.values()) == {"conflict"}


def test_source_event_dependency_can_arrive_later() -> None:
    command = _command("link", "event_link", {"event_id": "target", "root_event_id": "source"})
    pending, outcomes = reduce_partition([command], dependencies={"events": ["target"]})
    assert pending["pending_dependency"]
    assert outcomes["link"] == "pending_dependency"
    resolved, outcomes = reduce_partition([command], dependencies={"events": ["target", "source"]})
    assert not resolved["pending_dependency"]
    assert outcomes["link"] == "accepted"


def test_ambiguous_entity_dependency_is_conflict_not_unreleasable_missing_endpoint() -> None:
    relation = _command("relation", "local_relation", {"from_entity_id": "顾霜", "to_entity_id": "林渡"})
    projection, outcomes = reduce_partition([relation], dependencies={
        "entities": ["林渡"], "ambiguous_entities": ["顾霜"],
    })
    assert projection["contested"] and not projection["pending_dependency"]
    assert outcomes == {"relation": "conflict"}
