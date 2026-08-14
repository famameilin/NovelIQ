from src.models.local.character_reference_policy import (
    collect_reference_slots_from_names,
    decide_character_reference,
    filter_global_character_names,
    is_global_character_surface_name,
    is_reference_slot_name,
)


def test_reference_policy_blocks_raw_pronoun_from_global_character() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 锁定 raw 代词默认不能进入 global character 主链。
    """
    decision = decide_character_reference("我", chunk_id=7)

    assert decision.reference_kind == "pov_slot"
    assert decision.reference_slot == "POV_SLOT_C7_我"
    assert decision.can_enter_global_character is False
    assert decision.resolved_global_name is None


def test_reference_policy_allows_explicit_global_name() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 显式实名仍应直接进入角色榜、图谱和 diagnosis 主链。
    """
    decision = decide_character_reference("汪淼")

    assert decision.reference_kind == "global_character"
    assert decision.can_enter_global_character is True
    assert decision.resolved_global_name == "汪淼"


def test_reference_policy_allows_resolved_pronoun_as_global_target_only() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 已解析代词只能用 resolved_global_name 进入主链，surface 本身不能变成全局实体。
    """
    decision = decide_character_reference("我", resolved_global_name="汪淼")

    assert decision.reference_kind == "pov_slot"
    assert decision.can_enter_global_character is True
    assert decision.resolved_global_name == "汪淼"
    assert decision.reference_slot == "POV_SLOT_我"


def test_filter_global_character_names_dedupes_and_filters_references() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 各读侧共享 helper 需要同时覆盖去重和代词过滤。
    """
    result = filter_global_character_names(["我", "叶文洁", "叶文洁", "大史"])

    assert result == ["叶文洁", "大史"]


def test_reference_policy_recognizes_explicit_reference_slot_as_non_global_name() -> None:
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: slot 前缀必须被显式识别，避免 Phase4 / graph / diagnosis 把 slot 当成正式角色名。
    """
    slot_name = "POV_SLOT_C7_我"

    assert is_reference_slot_name(slot_name) is True
    assert is_global_character_surface_name(slot_name) is False

    decision = decide_character_reference(slot_name)
    assert decision.reference_kind == "pov_slot"
    assert decision.reference_slot == slot_name
    assert decision.resolved_global_name is None


def test_collect_reference_slots_from_names_dedupes_surfaces_and_existing_slots() -> None:
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: Phase4 request 组装需要稳定 dedupe 现有 slot 与 raw pronoun surface，避免重复 slot 污染 prompt。
    """
    slots = collect_reference_slots_from_names(
        ["我", "POV_SLOT_C3_我", "她", "LOCAL_REF_C3_她", "汪淼"],
        chunk_id=3,
    )

    assert slots == ["POV_SLOT_C3_我", "LOCAL_REF_C3_她"]
