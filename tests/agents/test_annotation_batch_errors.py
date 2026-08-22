"""领域批量校验错误收集测试"""

import pytest

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import (
    CharacterObservationInput,
    DialogueInput,
    DialogueVerdict,
    EmotionalValence,
    RelationInput,
    RoleFunction,
)
from src.agents.annotation.tools import AnnotationToolLedger


def _ledger() -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="文本",
        allow_future_context=False,
        graph=FactGraph(),
    )


def test_relation_endpoint_errors_collected_with_indexes() -> None:
    ledger = _ledger()
    payload = [
        RelationInput(from_entity="甲", to_entity="乙", relation_type="师徒"),
        RelationInput(from_entity="丙", to_entity="丁", relation_type="敌对"),
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger.write_domain("relations", payload, tool_name="write_relations")
    message = str(excinfo.value)
    assert "relations 校验失败" in message
    assert "[0] relation.from_entity 未在当前 chunk 的 write_entities 中声明: 甲" in message
    assert "[1] relation.from_entity 未在当前 chunk 的 write_entities 中声明: 丙" in message


def test_character_observation_errors_collected_with_indexes() -> None:
    ledger = _ledger()
    payload = [
        CharacterObservationInput(
            character="甲",
            role_function=RoleFunction.SUBJECT,
            action="出手救人",
            emotion=EmotionalValence.STRONG_POSITIVE,
        ),
        CharacterObservationInput(
            character="乙",
            role_function=RoleFunction.OPPONENT,
            action="拦路截杀",
            emotion=EmotionalValence.STRONG_NEGATIVE,
        ),
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger.write_domain(
            "character_observations",
            payload,
            tool_name="write_character_observations",
        )
    message = str(excinfo.value)
    assert "character_observations 校验失败" in message
    assert "[0] character_observation.character 未在当前 chunk 的 write_entities 中声明: 甲" in message
    assert "[1] character_observation.character 未在当前 chunk 的 write_entities 中声明: 乙" in message


def test_dialogue_speaker_error_collected_with_index() -> None:
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text='他说："今日且走，来日方长。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    payload = [
        DialogueInput(
            candidate_index=1,
            verdict=DialogueVerdict.DIALOGUE,
            speaker="甲",
            tone="平静",
        ),
    ]
    with pytest.raises(ValueError) as excinfo:
        ledger.write_domain("dialogues", payload, tool_name="write_dialogues")
    message = str(excinfo.value)
    assert "dialogues 校验失败" in message
    assert "[0] dialogue.speaker 未在当前 chunk 的 write_entities 中声明: 甲" in message


def test_dialogue_coverage_missing_candidates_defaults_to_not_dialogue() -> None:
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text='他说："今日且走，来日方长。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    result = ledger.write_domain("dialogues", [], tool_name="write_dialogues")
    assert result["accepted"] is True
    assert result["defaulted_not_dialogue"] == [1]
    assert ledger.dialogue_missing_indexes == [1]
    assert ledger.bound_payloads["dialogues"] == []
