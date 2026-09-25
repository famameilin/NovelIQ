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
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import (
    ChapterMetricsInput,
    DialogueVerdict,
    EntityInput,
    ParticipantArg,
    Tone,
)
from src.agents.annotation.tools import AnnotationToolLedger


def _ledger() -> AnnotationToolLedger:
    return AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chapter_text="文本",
        allow_future_context=False,
        graph=FactGraph(),
    )


def test_relation_endpoint_rejections_are_per_record_and_localized() -> None:
    """原 test_relation_endpoint_errors_collected_with_indexes：非法关系端点必须逐条可定位

    2026-09-13 变化：旧合同在 write_domain("relations", payload) 结算时按 [0]/[1]
    一次性收集两条"未登记端点"错误；新合同 apply_relation 一次一条、写入即入图，
    未登记引用在写入点即被结构化拒绝（record 指向该条边，field 指向出错的端点字段）。
    2026-09-19 id 纪律：EntityRef 只有 str（run 级 uuid id 或 el 键）；未知 uuid 的
    拒绝文案带"label 实体 id 未登记"与已登记 id 示例，expected 指向 write_entity /
    search_graph 回执的 id 来源。等价意图=每条违规关系都拿到指向自己的可自纠错误，
    且任何一条失败都不产生落账记录。
    """
    ledger = _ledger()
    unknown_a = "00000000-0000-0000-0000-000000000001"
    unknown_b = "00000000-0000-0000-0000-000000000003"
    rejections: list[AnnotationStageRejection] = []
    for from_id, to_id, relation_type in (
        (unknown_a, "00000000-0000-0000-0000-000000000002", "师徒"),
        (unknown_b, "00000000-0000-0000-0000-000000000004", "敌对"),
    ):
        with pytest.raises(AnnotationStageRejection) as excinfo:
            ledger.apply_relation(
                from_ref=from_id,
                to_ref=to_id,
                relation_type=relation_type,
            )
        rejections.append(excinfo.value)

    assert [rejection.record for rejection in rejections] == [
        f"relation/{unknown_a}-00000000-0000-0000-0000-000000000002/师徒",
        f"relation/{unknown_b}-00000000-0000-0000-0000-000000000004/敌对",
    ]
    for rejection, entity_id in zip(rejections, (unknown_a, unknown_b), strict=True):
        assert rejection.receipt()["status"] == "rejected"
        assert rejection.field == "from_entity"
        assert rejection.code == "unknown_entity_id"
        assert entity_id in str(rejection)
        assert ".from_entity" in str(rejection)
        assert "write_entity" in (rejection.expected or "")
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
        name: ledger.apply_entity(EntityInput(name=name, entity_type=entity_type), el=name)
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
    """原 test_event_participant_errors_collected_with_indexes：未登记参与者必须逐条可定位

    2026-09-13 变化：旧合同在一棵 WriteEventInput 组装时收集 participants.0/1 两条
    未登记错误；新合同参与者随 write_event 逐条调用提交（2026-09-14 characters
    数组并入 apply_event），未登记引用在写入点即拒绝，
    record=树/节点/参与者键（entityid 原值）。等价意图=每个非法参与者都有自己的错误，
    且失败条目不产生半棵脏树（根事件保留、未登记参与者不落进事件树）。
    """
    ledger = _ledger()
    ledger.apply_event(
        el="t1",
        isroot=True,
        description="甲乙交战",
    )

    unknown_ids = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")
    records: list[str] = []
    for entity_id in unknown_ids:
        with pytest.raises(AnnotationStageRejection) as excinfo:
            ledger.apply_event(
                el="t1",
                isroot=True,
                description="甲乙交战",
                characters=[
                    ParticipantArg(
                        entityid=entity_id,
                        role="主体",
                        narrative_role="主体",
                        action="出手救人",
                        emotion=2,
                    )
                ],
            )
        records.append(excinfo.value.record or "")
        assert excinfo.value.field == "entityid"
        assert excinfo.value.code == "unknown_entity_id"
        assert entity_id in str(excinfo.value)
    assert records == [
        f"t1/root/participant/{unknown_ids[0]}",
        f"t1/root/participant/{unknown_ids[1]}",
    ]
    assert ledger.bound_payloads["events"][0].participants == []
    assert ledger.observation_by_record == {}


def test_dialogue_speaker_rejection_points_at_the_single_record() -> None:
    """原 test_dialogue_speaker_error_collected_with_index：未登记说话人必须被拒绝并指向该记录

    2026-09-19 id 纪律：说话人是 EntityRef（run 级 uuid id 或 el 键）；未登记 uuid
    在写入点结构化拒绝（record=dialogue/<序号>、field=speaker、code=unknown_entity_id）。
    等价意图=错误定位到唯一可修记录，修正该条后按同序号重交即可，失败条目不产生落账记录。
    """
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chapter_text='他说："今日且走，来日方长。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    unknown_id = "00000000-0000-0000-0000-000000000099"
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.apply_dialogue(
            candidate_index=1,
            verdict=DialogueVerdict.DIALOGUE,
            speaker_ref=unknown_id,
            tone=Tone.CALM,
        )

    rejection = excinfo.value
    assert rejection.record == "dialogue/1"
    assert rejection.field == "speaker"
    assert rejection.code == "unknown_entity_id"
    assert ledger.written_dialogues == {}

    # 修正路径：同一候选序号用已登记 id 重交即写入（失败不封锁该记录的修复）
    number = ledger.apply_entity(EntityInput(name="甲", entity_type="character"), el="甲")
    ledger.apply_dialogue(
        candidate_index=1,
        verdict=DialogueVerdict.DIALOGUE,
        speaker_ref=number,
        tone=Tone.CALM,
    )
    assert ledger.written_dialogues[1].speaker == "甲"


def test_dialogue_coverage_missing_candidates_defaults_to_not_dialogue() -> None:
    """原测试保留：未提交候选在收尾时默认按 not_dialogue 处理并留痕

    2026-09-13 变化：旧合同对话域由完整域提交（含空列表）收尾，未提交候选在域结算时
    补默认；新合同取消逐域 finish，补默认判定推迟到唯一收尾里，2026-09-14 收尾更名
    finish（ledger.chunk_finished→chapter_finished），因此本测试直接走
    ledger.finish_chapter()。语义不变的部分：未提交候选默认 not_dialogue +
    dialogue_missing_indexes 留痕 + bound_payloads 对话落账视图为空；
    回执形状按新合同断言（dialogue_defaulted 列出默认序号，records 计入默认后的条数）。
    """
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chapter_text='他说："今日且走，来日方长。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    # 收尾硬前提是指标已提交（缺指标按 missing_record 拒绝），与本用例的对话默认判定无关
    ledger.apply_metrics(
        ChapterMetricsInput(summary="短块", emotional_valence=0, narrative_function="铺垫")
    )
    result = ledger.finish_chapter()

    assert result["status"] == "completed"
    assert result["chapter_id"] == 1
    assert result["records"]["dialogues"] == 1
    assert result["dialogue_defaulted"] == [1]
    assert ledger.dialogue_missing_indexes == [1]
    assert ledger.written_dialogues[1].verdict == DialogueVerdict.NOT_DIALOGUE
    assert ledger.bound_payloads["dialogues"] == []
    assert ledger.chapter_finished is True
