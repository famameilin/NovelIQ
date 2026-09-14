"""单记录写入拒绝测试（2026-09-13 取消暂存后取代旧的领域批量校验错误收集）

旧合同（write_entities / write_dialogues / write_event / write_relations 一次大载荷）
在领域结算时按 [index] 批量收集端点/参与者错误；2026-09-13 用户裁决取消暂存概念：
每个小调用写入即生效并返回真实回执（status=written），每条记录在写入点独立校验，
失败只指向该记录（record/field/code/expected）。因此本文件的验证意图不变——每次
违规都被精确拒绝并可定位到出错记录——但"整批收集 + 下标"与暂存区都没有对应物：
逐条拒绝断言与 written_* 账本断言取代批量收集/暂存断言（各测试 docstring 详述）。
"""

import pytest

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import (
    ChunkMetricsInput,
    DialogueVerdict,
    EntityInput,
    Tone,
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


def test_relation_endpoint_rejections_are_per_record_and_localized() -> None:
    """原 test_relation_endpoint_errors_collected_with_indexes：非法关系端点必须逐条可定位

    2026-09-13 变化：旧合同在 write_domain("relations", payload) 结算时按 [0]/[1]
    一次性收集两条"未登记端点"错误；新合同 apply_relation 一次一条、写入即入图，
    未登记编号在写入点即被结构化拒绝（record 指向该条边，field 指向出错的端点字段）。
    等价意图=每条违规关系都拿到指向自己的可自纠错误，且任何一条失败都不产生落账记录。
    """
    ledger = _ledger()
    rejections: list[AnnotationStageRejection] = []
    for from_number, to_number, relation_type in ((1, 2, "师徒"), (3, 4, "敌对")):
        with pytest.raises(AnnotationStageRejection) as excinfo:
            ledger.apply_relation(
                from_number=from_number,
                to_number=to_number,
                relation_type=relation_type,
            )
        rejections.append(excinfo.value)

    assert [rejection.record for rejection in rejections] == [
        "relation/1-2/师徒",
        "relation/3-4/敌对",
    ]
    for rejection, number in zip(rejections, (1, 3), strict=True):
        assert rejection.receipt()["status"] == "rejected"
        assert rejection.field == "from_entity"
        assert rejection.code == "unregistered_number"
        assert f"write_relation.from_entity 实体编号 {number} 未登记" in str(rejection)
        assert "write_entity 回执 n" in (rejection.expected or "")
    assert ledger.written_relations == {}


def test_relation_endpoint_type_rejection_points_at_the_single_record() -> None:
    """原 test_relation_endpoint_errors_collected_with_indexes 的端点类型分支

    2026-09-13 变化：旧合同对"已登记但类型不符"的端点在同一批校验里报
    "[index] relation.from_entity 端点类型必须属于 [...]"；新合同在写入该条边时
    即拒绝，record 用登记名定位（relation/丙-乙/师徒），不再有批次下标。
    """
    ledger = _ledger()
    numbers = {
        name: ledger.apply_entity(EntityInput(name=name, entity_type=entity_type))
        for name, entity_type in (("甲", "character"), ("乙", "character"), ("丙", "location"))
    }
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.apply_relation(
            from_number=numbers["丙"],
            to_number=numbers["乙"],
            relation_type="师徒",
        )

    rejection = excinfo.value
    assert rejection.record == "relation/丙-乙/师徒"
    assert rejection.field == "from_entity"
    assert rejection.code == "endpoint_invalid"
    assert "端点类型必须属于 ['character']" in str(rejection)
    assert ledger.written_relations == {}


def test_event_participant_rejections_are_per_record_and_localized() -> None:
    """原 test_event_participant_errors_collected_with_indexes：未登记参与者必须逐条可定位

    2026-09-13 变化：旧合同在一棵 WriteEventInput 组装时收集 participants.0/1 两条
    未登记错误；新合同参与者一次一条（apply_participation），未登记编号在写入点即拒绝，
    record=树/节点/参与者编号。等价意图=每个非法参与者都有自己的错误，
    且失败条目不产生半棵脏树（根事件保留、未登记参与者不落进事件树）。
    """
    ledger = _ledger()
    ledger.apply_event_root(
        tree_key="t1",
        description="甲乙交战",
        cause_tree_id=None,
        isforeshadowing=False,
        expected_payoff_family=None,
        payoff_likelihood=None,
    )

    records: list[str] = []
    for number in (1, 2):
        with pytest.raises(AnnotationStageRejection) as excinfo:
            ledger.apply_participation(
                tree_key="t1",
                node_key="root",
                entity_number=number,
                role="主体",
                narrative_role="主体",
                action="出手救人",
                emotion=2,
                character=True,
            )
        records.append(excinfo.value.record or "")
        assert excinfo.value.field == "entity"
        assert excinfo.value.code == "unregistered_number"
        assert "实体编号" in str(excinfo.value)
    assert records == ["t1/root/participant/1", "t1/root/participant/2"]
    assert ledger.bound_payloads["events"][0].participants == []
    assert ledger.observation_by_record == {}


def test_dialogue_speaker_rejection_points_at_the_single_record() -> None:
    """原 test_dialogue_speaker_error_collected_with_index：未登记说话人必须被拒绝并指向该记录

    2026-09-13 变化：说话人从实体名称改为运行期编号；旧合同在整批对话结算时按 [index]
    报"未声明名称"，新合同 apply_dialogue 一次一个候选，未登记编号在写入点结构化拒绝
    （record=dialogue/<序号>、field=speaker）。等价意图=错误定位到唯一可修记录，
    修正该条后按同序号重交即可，失败条目不产生落账记录。
    """
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text='他说："今日且走，来日方长。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.apply_dialogue(
            candidate_index=1,
            verdict=DialogueVerdict.DIALOGUE,
            speaker_number=99,
            tone=Tone.CALM,
        )

    rejection = excinfo.value
    assert rejection.record == "dialogue/1"
    assert rejection.field == "speaker"
    assert rejection.code == "unregistered_number"
    assert "speaker 实体编号 99 未登记" in str(rejection)
    assert ledger.written_dialogues == {}

    # 修正路径：同一候选序号用已登记编号重交即写入（失败不封锁该记录的修复）
    number = ledger.apply_entity(EntityInput(name="甲", entity_type="character"))
    ledger.apply_dialogue(
        candidate_index=1,
        verdict=DialogueVerdict.DIALOGUE,
        speaker_number=number,
        tone=Tone.CALM,
    )
    assert ledger.written_dialogues[1].speaker == "甲"


def test_dialogue_coverage_missing_candidates_defaults_to_not_dialogue() -> None:
    """原测试保留：未提交候选在收尾时默认按 not_dialogue 处理并留痕

    2026-09-13 变化：旧合同对话域由完整域提交（含空列表）收尾，未提交候选在域结算时
    补默认；新合同取消逐域 finish，补默认判定推迟到唯一 finish_chunk 的收尾校验里，
    因此本测试直接走 ledger.finish_chunk()。语义不变的部分：未提交候选默认
    not_dialogue + dialogue_missing_indexes 留痕 + bound_payloads 对话落账视图为空；
    回执形状按新合同断言（dialogue_defaulted 列出默认序号，records 计入默认后的条数）。
    """
    ledger = AnnotationToolLedger(
        run_scope="r",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text='他说："今日且走，来日方长。"',
        allow_future_context=False,
        graph=FactGraph(),
    )
    # 收尾硬前提是指标已提交（缺指标按 missing_record 拒绝），与本用例的对话默认判定无关
    ledger.apply_metrics(
        ChunkMetricsInput(summary="短块", emotional_valence=0, narrative_function="铺垫")
    )
    result = ledger.finish_chunk()

    assert result["status"] == "completed"
    assert result["chunk_id"] == 1
    assert result["records"]["dialogues"] == 1
    assert result["dialogue_defaulted"] == [1]
    assert ledger.dialogue_missing_indexes == [1]
    assert ledger.written_dialogues[1].verdict == DialogueVerdict.NOT_DIALOGUE
    assert ledger.bound_payloads["dialogues"] == []
    assert ledger.chunk_finished is True
