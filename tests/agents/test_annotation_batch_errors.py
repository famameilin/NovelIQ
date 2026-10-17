"""单记录写入拒绝测试（2026-09-14 写入面重构后取代旧的领域批量校验错误收集）

旧合同（write_entities / write_dialogues / write_event / write_relations 一次大载荷）
在领域结算时按 [index] 批量收集端点/参与者错误；2026-09-13 取消暂存概念：
每个小调用写入即生效并返回真实回执（status=written），每条记录在写入点独立校验，
失败只指向该记录（record/field/code/expected）。2026-09-14 写入面再收敛为五工具：
参与者并入 write_event 的 characters 数组（记录键 "<节点记录>/participant/<entityid原值>"）、
实体引用统一 EntityRef（编号 n 或本章的 el 键）、收尾更名 finish。
因此本文件的验证意图不变——每次违规都被精确拒绝并可定位到出错记录，好记录照常落账；
逐条拒绝断言与 written_* 账本断言取代批量收集/暂存断言（各测试 docstring 详述）。
"""

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
    """原 test_relation_endpoint_errors_collected_with_indexes 的端点类型分支

    2026-09-13 变化：旧合同对"已登记但类型不符"的端点在同一批校验里报
    "[index] relation.from_entity 端点类型必须属于 [...]"；新合同在写入该条边时
    即拒绝，record 用登记名定位（relation/丙-乙/师徒），不再有批次下标。
    2026-09-14 apply_entity 需自定 el 键（解析后记录键仍用登记名）。
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
