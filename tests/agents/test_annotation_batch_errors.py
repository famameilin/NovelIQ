"""单记录写入拒绝测试：每条记录在写入点独立校验，失败只指向该记录（record/field/code/expected）"""

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.event_trees.models import ParticipantArg
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityNameRef
from src.fact_graph.vocabulary import DialogueVerdict, Tone


def _ledger() -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chapter_text="文本",
        allow_future_context=False,
        graph=FactGraph(),
    )


def test_relation_endpoint_rejections_are_per_record_and_localized() -> None:
    ledger = _ledger()
    records = []
    for name in ("甲", "乙"):
        with pytest.raises(AnnotationStageRejection) as error:
            ledger.apply_relation(
                from_ref=EntityNameRef(name=name, entity_type="location"),
                to_ref=EntityNameRef(name="丙", entity_type="character"),
                relation_type="师徒",
            )
        records.append(error.value.record)
        assert error.value.field == "from_entity"
        assert error.value.code == "endpoint_invalid"
        assert name in str(error.value)
    assert records == ["relation/甲-丙/师徒", "relation/乙-丙/师徒"]
    assert ledger.written_relations == {}


def test_relation_endpoint_type_rejection_points_at_the_single_record() -> None:
    """端点类型不符在写入该条边时即拒绝，record 用登记名定位（relation/丙-乙/师徒）

    apply_entity 需自定 el 键（解析后记录键仍用登记名）。
    """
    ledger = _ledger()
    numbers = {
        name: EntityNameRef(name=name, entity_type=entity_type)
        for name, entity_type in (("甲", "character"), ("乙", "character"), ("丙", "location"))
    }
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.apply_relation(
            from_ref=numbers["丙"],
            to_ref=numbers["乙"],
            relation_type="师徒",
        )

    rejection = excinfo.value
    assert rejection.record == "relation/丙-乙/师徒"
    assert rejection.field == "from_entity"
    assert rejection.code == "endpoint_invalid"
    assert ledger.written_relations == {}


def test_event_participant_rejections_are_per_record_and_localized() -> None:
    ledger = _ledger()
    ledger.apply_event(
        el="t1", title="甲乙交战", problem="明确事件问题", summary="甲乙交战", event_type="行动", status="ongoing"
    )
    for name in ("甲", "乙"):
        with pytest.raises(AnnotationStageRejection) as error:
            ledger.apply_event(
                el="t1",
                characters=[ParticipantArg(name=name, entity_type="character", role="地点")],
                title="甲乙交战",
                problem="明确事件问题",
                summary="甲乙交战",
                event_type="行动",
                status="ongoing",
            )
        assert error.value.record == f"t1/root/participant/{name}"
        assert error.value.field == "role"
        assert error.value.code == "role_type_mismatch"
    assert ledger.bound_payloads["events"][0].participants == []


def test_dialogue_speaker_rejection_points_at_the_single_record() -> None:
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chapter_text='他说："今日且走。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    with pytest.raises(AnnotationStageRejection) as error:
        ledger.apply_dialogue(
            candidate_index=1,
            verdict=DialogueVerdict.DIALOGUE,
            speaker_ref=EntityNameRef(name="山门", entity_type="location"),
            tone=Tone.CALM,
        )
    assert error.value.record == "dialogue/1"
    assert error.value.field == "speaker"
    assert error.value.code == "not_character"
    assert ledger.written_dialogues == {}
    ledger.apply_dialogue(
        candidate_index=1,
        verdict=DialogueVerdict.DIALOGUE,
        speaker_ref=EntityNameRef(name="甲", entity_type="character"),
        tone=Tone.CALM,
    )
    assert ledger.written_dialogues[1].speaker == "甲"
