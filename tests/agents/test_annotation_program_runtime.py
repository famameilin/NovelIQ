"""当前正式工具面的受限解释器测试，覆盖安全边界、按条回滚与收尾"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.annotation import program_contract
from src.agents.annotation.ledger import AnnotationToolLedger
from src.fact_graph.graph import FactGraph, entity_key
from src.fact_graph.inputs import ChapterParagraphInfo
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.annotation_work_tools import build_program_test_runtime as ProgramRuntime


class _QueryService:
    async def search_text(self, query: str, *, range_name: str, limit: int = 50) -> list:
        return []

    async def read_paragraph(self, paragraph_id: int, *, allow_future_context: bool) -> dict[str, Any]:
        assert allow_future_context and paragraph_id == 20
        return {"chapter_id": 2, "paragraph_id": 20, "text": "顾霜就是阿青。"}


def _ledger() -> AnnotationToolLedger:
    text = "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text=text,
        allow_future_context=True,
        graph=FactGraph(run_scope="run-1"),
        paragraph_info=ChapterParagraphInfo(paragraph_ids=[1], char_spans=[(0, len(text))], texts=[text]),
    )


def _runtime(ledger: AnnotationToolLedger) -> ProgramRuntime:
    return ProgramRuntime(build_annotation_tools(_QueryService(), ledger), ledger)


async def _run(runtime: ProgramRuntime, code: str) -> dict[str, Any]:
    return json.loads(await runtime.execute(code))


@pytest.mark.asyncio
async def test_receipt_omits_success_record_content() -> None:
    ledger = _ledger()
    receipt = await _run(
        _runtime(ledger), 'write_entity(el="a1", name="顾霜", entity_type="character", description="唯一描述串XYZ")'
    )
    assert receipt["applied"] == 1
    assert "唯一描述串XYZ" not in json.dumps(receipt, ensure_ascii=False)
    assert ledger.written_entities[entity_key("顾霜", "character")].description == "唯一描述串XYZ"


@pytest.mark.asyncio
async def test_json_literals_true_false_null_are_accepted() -> None:
    ledger = _ledger()
    receipt = await _run(
        _runtime(ledger),
        (
            "write_metrics(summary='伏笔埋设', emotional_valence=1, narrative_func"
            "tion='铺垫', pivot_moment=false, cliffhanger=true)\n"
            "write_entity(el='a1', name='顾霜', entity_type='character', descrip"
            "tion=null)\n"
            "write_event(el='t1', evidence=1, isforeshadowing=true, confidence"
            "='low', title='埋设', problem='明确事件问题', summary='埋设', event_type='行"
            "动', status='ongoing')"
        ),
    )
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 3
    assert ledger.metrics_payload.cliffhanger is True
    assert ledger.metrics_payload.pivot_moment is False
    assert ledger.written_entities[entity_key("顾霜", "character")].description is None
    assert next(iter(ledger.event_trees.values()))["isforeshadowing"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "error_code"),
    [
        ('write_entity(el="a1", name=unknown, entity_type="character")', "undefined_name"),
        ("import os", "unsupported_statement"),
        ("value = {'a': 1}.keys()", "unsupported_expression"),
        ("value = [item for item in (1, 2)]", "unsupported_expression"),
        ('value = f"{1}"', "unsupported_expression"),
        ("while True:\n    pass", "unsupported_statement"),
        ("write_entity = 1", "name_reserved"),
        ("len = 1", "name_reserved"),
        ("_tmp = 1", "name_reserved"),
        ("value = write_metrics(*[1])", "bad_call"),
        ("left, right = (1, 2, 3)", "bad_assignment"),
        ("first, *rest = (1, 2, 3)", "bad_assignment"),
        ("for item in 'abc':\n    pass", "unsupported_expression"),
        ("count = len(1)", "runtime_error"),
        ("unit = 1 / 0", "runtime_error"),
    ],
)
async def test_unsafe_or_invalid_programs_return_structured_errors(code: str, error_code: str) -> None:
    ledger = _ledger()
    receipt = await _run(_runtime(ledger), code)
    assert receipt["status"] == "runtime_error"
    assert receipt["error"]["type"] == error_code
    assert receipt["applied"] == 0
    assert ledger.written_entities == {}


@pytest.mark.asyncio
async def test_syntax_size_and_empty_programs_are_rejected() -> None:
    runtime = _runtime(_ledger())
    for code, error_code in [
        ("   ", "empty_program"),
        ("write_entity(el=", "syntax_error"),
        ("value = " + "0" * (program_contract.PROGRAM_MAX_CODE_CHARS + 1), "program_too_large"),
    ]:
        receipt = await _run(runtime, code)
        assert receipt["status"] == "rejected"
        assert receipt["error"]["type"] == error_code
        assert receipt["applied"] == 0


@pytest.mark.asyncio
async def test_single_op_failure_rolls_back_only_that_op() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
write_entity(el="a1", name="侯飞白", entity_type="character")
write_entity(el="a2", name="贺府", entity_type="location")
write_relation(
    from_entity={"name": "侯飞白", "entity_type": "character"},
    to_entity={"name": "贺府", "entity_type": "location"},
    relation_type="隶属",
)
write_metrics(summary="贺府夜谈", emotional_valence=0, narrative_function="冲突")
""",
    )
    assert receipt["status"] == "partial"
    assert receipt["applied"] == 3
    (failure,) = receipt["failed"]
    assert failure["op"] == 3 and failure["line"] == 4
    assert failure["tool"] == "write_relation"
    assert failure["field"] == "to_entity"
    assert failure["code"] == "endpoint_invalid"
    assert set(ledger.written_entities) == {
        entity_key("侯飞白", "character"),
        entity_key("贺府", "location"),
    }
    assert ledger.written_relations == {}
    assert ledger.metrics_payload is not None
    assert runtime.ops[2]["error_code"] == "endpoint_invalid"


@pytest.mark.asyncio
async def test_failed_dialogue_does_not_change_prior_judgment() -> None:
    ledger = _ledger()
    receipt = await _run(
        _runtime(ledger),
        """
write_entity(el="a1", name="贺府", entity_type="location")
write_dialogue(candidate_index=1, verdict="not_dialogue")
write_dialogue(candidate_index=2, verdict="dialogue", speaker={"name": "贺府", "entity_type": "location"})
""",
    )
    assert receipt["applied"] == 2
    assert receipt["failed"][0]["code"] == "not_character"
    assert set(ledger.written_dialogues) == {1}


@pytest.mark.asyncio
async def test_variables_persist_across_programs() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    first = await _run(runtime, 'person = write_entity(el="a1", name="贺伯安", entity_type="character")')
    assert first["applied"] == 1
    second = await _run(
        runtime,
        (
            "write_metrics(summary='离火反噬', emotional_valence=-2, narrative_fun"
            "ction='转折')\n"
            "write_event(el='t1', evidence=1, characters=[{'name': person['con"
            "tent']['name'], 'entity_type': person['content']['entity_type'], "
            "'role': '客体', 'narrative_role': '客体', 'action': '承受反噬', 'emotion'"
            ": -2}], title='离火反噬', problem='明确事件问题', summary='离火反噬', event_typ"
            "e='行动', status='ongoing')\n"
            "for candidate in [1, 2]:\n"
            "    write_dialogue(candidate_index=candidate, verdict='dialogue',"
            " speaker={'name': person['content']['name'], 'entity_type': perso"
            "n['content']['entity_type']})\n"
            "finish()"
        ),
    )
    assert second["status"] == "applied"
    root = ledger.bound_payloads["events"][0]
    assert [ledger.graph.display_name(participant.entity) for participant in root.participants] == ["贺伯安"]
    assert runtime.ops[-1]["program_id"] == "p2"


@pytest.mark.asyncio
async def test_for_loop_iterates_dict_keys_in_insertion_order() -> None:
    """字典按键遍历与 Python 语义一致：有界、插入序稳定"""
    runtime = _runtime(_ledger())
    receipt = await _run(
        runtime,
        'counts = {"a": 1, "b": 2}\nkey_list = []\nfor key in counts:\n    key_list = key_list + [key]',
    )
    assert receipt["status"] == "applied"
    assert runtime.env["key_list"] == ["a", "b"]


@pytest.mark.asyncio
async def test_limits_keep_applied_ops_and_allow_next_program(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    monkeypatch.setattr(program_contract, "PROGRAM_MAX_LOOP_ITEMS", 2)
    loop = await _run(runtime, "for item in [1, 2, 3]:\n    pass")
    assert loop["error"]["type"] == "loop_too_long" and loop["applied"] == 0
    monkeypatch.setattr(program_contract, "PROGRAM_MAX_OPS", 2)
    ops = await _run(
        runtime,
        """
write_entity(el="a1", name="顾霜", entity_type="character")
write_entity(el="a2", name="贺府", entity_type="organization")
write_relation(
    from_entity={"name": "顾霜", "entity_type": "character"},
    to_entity={"name": "贺府", "entity_type": "organization"},
    relation_type="隶属",
)
""",
    )
    assert ops["error"]["type"] == "too_many_ops"
    assert ops["applied"] == 2
    assert set(ledger.written_entities) == {
        entity_key("顾霜", "character"),
        entity_key("贺府", "organization"),
    }
    retry = await _run(
        runtime,
        (
            'write_relation(from_entity={"name": "顾霜", "entity_type": "charact'
            'er"}, to_entity={"name": "贺府", "entity_type": "organization"}, re'
            'lation_type="隶属")'
        ),
    )
    assert retry["applied"] == 1
    monkeypatch.setattr(program_contract, "PROGRAM_MAX_STEPS", 3)
    steps = await _run(runtime, "for item in [1, 2]:\n    pass")
    assert steps["error"]["type"] == "too_many_steps"


@pytest.mark.asyncio
async def test_deadline_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(program_contract, "PROGRAM_DEADLINE_S", -1.0)
    receipt = await _run(_runtime(_ledger()), "value = 1")
    assert receipt["error"]["type"] == "deadline_exceeded"
    assert receipt["applied"] == 0


@pytest.mark.asyncio
async def test_language_supports_if_tuple_unpacking_and_comparisons() -> None:
    ledger = _ledger()
    receipt = await _run(
        _runtime(ledger),
        """
left, right = (1, 2)
if left in [1, 2]:
    write_metrics(summary="条件成立", emotional_valence=0, narrative_function="铺垫")
if left != right:
    write_dialogue(candidate_index=1, verdict="not_dialogue")
if left == 1:
    write_dialogue(candidate_index=2, verdict="not_dialogue")
""",
    )
    assert receipt["applied"] == 3
    assert ledger.metrics_payload.summary == "条件成立"
    assert set(ledger.written_dialogues) == {1, 2}


@pytest.mark.asyncio
async def test_language_supports_conditionals_boolean_and_unpacking() -> None:
    """放行常见语法：条件表达式/and-or-not/链式与序比较/is/*、** 解包"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
numbers = [*[1, 2], 3]
scale = "多" if len(numbers) > 2 else "少"
if scale == "多" and 1 < 2 < 3 and numbers[0] != 9 and 9 not in numbers:
    write_metrics(summary="常见语法", emotional_valence=0, narrative_function="铺垫")
row = {"el": "a1", "name": "顾霜", "entity_type": "character"}
extra = {"description": None}
write_entity(**row, **extra)
if scale == "少" or not (numbers[-1] >= 3 and numbers[-1] is not None):
    write_dialogue(candidate_index=1, verdict="not_dialogue")
""",
    )
    assert receipt["applied"] == 2, receipt
    assert ledger.metrics_payload.summary == "常见语法"
    assert entity_key("顾霜", "character") in ledger.written_entities
    assert runtime.env["numbers"] == [1, 2, 3]
    assert set(ledger.written_dialogues) == set()


@pytest.mark.asyncio
async def test_language_supports_basic_builtin_functions() -> None:
    """放行基础函数：len/str/int/float/bool/min/max/abs/sum/sorted/enumerate"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
values = sorted([3, 1, 2])
total = sum(values)
widest = max(values) - min(values)
count = len(values)
ratio = total / count
floored = total // count
remainder = total % count
parsed = int("3") + int(1.5) + int(True)
negated = abs(-widest)
if bool(count) and str(count) == "3" and ratio == 2.0 and floored == 2:
    if remainder == 0 and parsed == 5 and negated == 2 and values[0] == 1:
        write_metrics(summary="基础函数", emotional_valence=0, narrative_function="铺垫")
for index, item in enumerate(values, 1):
    if index == 1 and item == 1:
        write_dialogue(candidate_index=2, verdict="not_dialogue")
""",
    )
    assert receipt["applied"] == 2, receipt
    assert ledger.metrics_payload.summary == "基础函数"
    assert set(ledger.written_dialogues) == {2}


@pytest.mark.asyncio
async def test_anchor_accepts_bare_tree_key_as_root_record() -> None:
    """裸树键补全：模型按自然形态拿树键当记录键时统一指到它的根记录"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        (
            "write_event(el='t1', evidence=1, title='顾霜拔剑', problem='明确事件问题', "
            "summary='顾霜拔剑', event_type='行动', status='ongoing')\n"
            "local = read_text(paragraph_id=1, quote='顾霜')\n"
            "anchor_record(record_id='t1', source_ref=local['source_ref'])"
        ),
    )

    assert receipt["status"] == "applied", receipt
    assert ledger.source_anchors["t1/root"]


@pytest.mark.asyncio
async def test_repeat_failed_batch_guard_hints_then_fails_program() -> None:
    """重复失败批守卫（两级）：同一失败批第 2 次注入聚合提示、第 3 次判程序失败"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    # 越界候选已在程序执行前拦截，守卫用仍会逐项拒绝的未知实体引用验证
    code = "\n".join(['write_relation(from_entity="unread", to_entity="other", relation_type="盟友")'] * 5)

    first = await _run(runtime, code)
    assert first["status"] == "partial"
    assert len(first["failed"]) == 5
    assert "note" not in first

    second = await _run(runtime, code)
    assert second["status"] == "partial"
    assert "原样重发不会通过" in second["note"]

    third = await _run(runtime, code)
    assert third["status"] == "runtime_error"
    assert third["error"]["type"] == "repeat_failed_batch"

    # 真正修改取值后计数复位，恢复正常回执
    fourth = await _run(runtime, 'write_dialogue(candidate_index=1, verdict="not_dialogue")')
    assert fourth["status"] == "applied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        'write_dialogue(candidate_index=1, verdict="not_dialogue")\n'
        'write_dialogue(candidate_index=3, verdict="not_dialogue")',
        'indices = [1, 2, 3]\nfor index in indices:\n    write_dialogue(candidate_index=index, verdict="not_dialogue")',
        'rows = [{"index": 1}, {"index": 99}]\nfor row in rows:\n'
        '    write_dialogue(candidate_index=row["index"], verdict="not_dialogue")',
        'for index, verdict in [(1, "not_dialogue"), (99, "not_dialogue")]:\n'
        "    write_dialogue(candidate_index=index, verdict=verdict)",
        'write_dialogue(candidate_index="99", verdict="not_dialogue")',
        'if write_dialogue(candidate_index=99, verdict="not_dialogue"):\n    pass',
        'for value in [write_dialogue(candidate_index=99, verdict="not_dialogue")]:\n    pass',
    ],
)
async def test_dialogue_batch_out_of_range_is_rejected_before_any_write(code: str) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        'write_metrics(summary="尚未写入", emotional_valence=0, narrative_function="铺垫")\n' + code + "\nfinish()",
    )
    assert receipt["status"] == "rejected", receipt
    assert receipt["applied"] == 0
    assert receipt["error"]["type"] == "candidate_index_out_of_range"
    assert "total=2" in receipt["error"]["message"]
    assert "candidate_index=" in receipt["error"]["message"]
    assert "line" in receipt["error"]
    assert not ledger.written_dialogues and ledger.metrics_payload is None
    assert runtime.ops == [] and runtime.env == {}
    assert not ledger.chapter_finished


@pytest.mark.asyncio
async def test_dialogue_preflight_respects_branches_assignments_and_preserves_prior_state() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    await _run(runtime, 'indices = [1, 2]\nwrite_dialogue(candidate_index=1, verdict="not_dialogue")')
    rejected = await _run(
        runtime,
        'indices = [1, 99]\nfor index in indices:\n    write_dialogue(candidate_index=index, verdict="not_dialogue")',
    )
    assert rejected["status"] == "rejected"
    assert runtime.env["indices"] == [1, 2]
    assert set(ledger.written_dialogues) == {1}
    repaired = await _run(
        runtime,
        "for index in indices:\n"
        "    if index in [1, 2]:\n"
        '        write_dialogue(candidate_index=index, verdict="not_dialogue")\n'
        'if False:\n    write_dialogue(candidate_index=99, verdict="not_dialogue")',
    )
    assert repaired["status"] == "applied", repaired
    assert set(ledger.written_dialogues) == {1, 2}


@pytest.mark.asyncio
async def test_dialogue_preflight_does_not_use_stale_values_from_unknown_tool_results() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    await _run(runtime, "index = 99")
    receipt = await _run(
        runtime,
        "value = read_text(paragraph_id=1)\n"
        'if value:\n    index = 1\nwrite_dialogue(candidate_index=index, verdict="not_dialogue")',
    )
    assert receipt["status"] == "applied", receipt
    assert receipt["applied"] == 2
    assert len(ledger.text_references) == 1
    assert set(ledger.written_dialogues) == {1}


@pytest.mark.asyncio
async def test_dynamic_candidate_value_is_checked_once_at_real_write_boundary() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        "text = read_text(paragraph_id=20)\n"
        'write_dialogue(candidate_index=text["paragraph_id"], verdict="not_dialogue")',
    )
    assert receipt["status"] == "partial", receipt
    assert receipt["applied"] == 1
    assert receipt["failed"][0]["record"] == "dialogue/20"
    assert receipt["failed"][0]["code"] == "out_of_range"
    assert len(ledger.text_references) == 1
    assert not ledger.written_dialogues


@pytest.mark.asyncio
async def test_dialogue_preflight_keeps_assignment_faults_at_original_execution_point() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        'write_metrics(summary="已接受指标", emotional_valence=0, narrative_function="铺垫")\n'
        'left, right = [1]\nwrite_dialogue(candidate_index=1, verdict="not_dialogue")',
    )
    assert receipt["status"] == "runtime_error", receipt
    assert receipt["error"]["type"] == "bad_assignment"
    assert receipt["applied"] == 1
    assert ledger.metrics_payload is not None
    assert not ledger.written_dialogues
