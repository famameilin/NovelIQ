"""当前正式工具面的受限解释器测试，覆盖安全边界、按条回滚与收尾"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents.annotation import program as program_module
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.program import ProgramRuntime
from src.agents.annotation.schema import ChapterParagraphInfo
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


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
async def test_program_writes_domains_and_returns_compressed_receipt() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(runtime, """
person = write_entity(el="a1", name="顾霜", entity_type="character")
write_metrics(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")
write_event(el="t1", isroot=true, description="喝止", evidence=1, characters=[
    {"entityid": person["id"], "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1}
])
for candidate in [1, 2]:
    write_dialogue(candidate_index=candidate, verdict="not_dialogue")
finish()
""")
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 6
    assert "failed" not in receipt and "reads" not in receipt and "refs" not in receipt
    assert receipt["progress"]["entities"] == 1
    assert receipt["progress"]["dialogues"] == 2
    assert ledger.chapter_finished and ledger.ready_chapter is not None
    assert runtime.ops[0]["program_id"] == "p1"
    assert runtime.ops[0]["op_index"] == 1
    assert runtime.ops[0]["tool_name"] == "write_entity"
    assert runtime.ops[0]["status"] == "success"
    assert runtime.ops[0]["record"] == "entity/顾霜"
    assert runtime.ops[0]["source_line"] == 2
    assert runtime.ops[-1]["tool_name"] == "finish"


@pytest.mark.asyncio
async def test_receipt_omits_success_record_content() -> None:
    ledger = _ledger()
    receipt = await _run(_runtime(ledger),
                         'write_entity(el="a1", name="顾霜", entity_type="character", description="唯一描述串XYZ")')
    assert receipt["applied"] == 1
    assert "唯一描述串XYZ" not in json.dumps(receipt, ensure_ascii=False)
    assert ledger.written_entities["顾霜"].description == "唯一描述串XYZ"


@pytest.mark.asyncio
async def test_json_literals_true_false_null_are_accepted() -> None:
    ledger = _ledger()
    receipt = await _run(_runtime(ledger), """
write_metrics(summary="伏笔埋设", emotional_valence=1, narrative_function="铺垫", pivot_moment=false, cliffhanger=true)
write_entity(el="a1", name="顾霜", entity_type="character", description=null)
write_event(el="t1", isroot=true, description="埋设", evidence=1, isforeshadowing=true, confidence="low")
""")
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 3
    assert ledger.metrics_payload.cliffhanger is True
    assert ledger.metrics_payload.pivot_moment is False
    assert ledger.written_entities["顾霜"].description is None
    assert next(iter(ledger.event_trees.values()))["isforeshadowing"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "error_code"), [
    ('write_entity(el="a1", name=unknown, entity_type="character")', "undefined_name"),
    ("import os", "unsupported_statement"),
    ("value = {'a': 1}.keys()", "unsupported_expression"),
    ("while True:\n    pass", "unsupported_statement"),
    ("write_entity = 1", "name_reserved"),
    ("_tmp = 1", "name_reserved"),
    ("value = write_metrics(*[1])", "bad_call"),
    ("left, right = (1, 2, 3)", "bad_assignment"),
    ("for item in 'abc':\n    pass", "unsupported_expression"),
    ("value = 1 if True else 2", "unsupported_expression"),
])
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
        ("value = " + "0" * (program_module._PROGRAM_MAX_CODE_CHARS + 1), "program_too_large"),
    ]:
        receipt = await _run(runtime, code)
        assert receipt["status"] == "rejected"
        assert receipt["error"]["type"] == error_code
        assert receipt["applied"] == 0


@pytest.mark.asyncio
async def test_single_op_failure_rolls_back_only_that_op() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(runtime, """
write_entity(el="a1", name="侯飞白", entity_type="character")
write_entity(el="a2", name="贺府", entity_type="location")
write_relation(from_entity="a1", to_entity="a2", relation_type="隶属")
write_metrics(summary="贺府夜谈", emotional_valence=0, narrative_function="冲突")
""")
    assert receipt["status"] == "partial"
    assert receipt["applied"] == 3
    failure, = receipt["failed"]
    assert failure["op"] == 3 and failure["line"] == 4
    assert failure["tool"] == "write_relation"
    assert failure["field"] == "to_entity"
    assert failure["code"] == "endpoint_invalid"
    assert set(ledger.written_entities) == {"侯飞白", "贺府"}
    assert ledger.written_relations == {}
    assert ledger.metrics_payload is not None
    assert runtime.ops[2]["error_code"] == "endpoint_invalid"


@pytest.mark.asyncio
async def test_failed_dialogue_does_not_change_prior_judgment() -> None:
    ledger = _ledger()
    receipt = await _run(_runtime(ledger), """
write_entity(el="a1", name="贺府", entity_type="location")
write_dialogue(candidate_index=1, verdict="not_dialogue")
write_dialogue(candidate_index=2, verdict="dialogue", speaker="a1")
""")
    assert receipt["applied"] == 2
    assert receipt["failed"][0]["code"] == "not_character"
    assert set(ledger.written_dialogues) == {1}


@pytest.mark.asyncio
async def test_variables_persist_across_programs() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    first = await _run(runtime, 'person = write_entity(el="a1", name="贺伯安", entity_type="character")')
    assert first["applied"] == 1
    second = await _run(runtime, """
write_metrics(summary="离火反噬", emotional_valence=-2, narrative_function="转折")
write_event(el="t1", isroot=true, description="离火反噬", evidence=1, characters=[
    {"entityid": person["id"], "role": "客体", "narrative_role": "客体", "action": "承受反噬", "emotion": -2}
])
for candidate in [1, 2]:
    write_dialogue(candidate_index=candidate, verdict="dialogue", speaker=person["id"])
finish()
""")
    assert second["status"] == "applied"
    root = ledger.bound_payloads["events"][0]
    assert [participant.entity for participant in root.participants] == ["贺伯安"]
    assert runtime.ops[-1]["program_id"] == "p2"


@pytest.mark.asyncio
async def test_limits_keep_applied_ops_and_allow_next_program(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_LOOP_ITEMS", 2)
    loop = await _run(runtime, "for item in [1, 2, 3]:\n    pass")
    assert loop["error"]["type"] == "loop_too_long" and loop["applied"] == 0
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_OPS", 2)
    ops = await _run(runtime, """
write_entity(el="a1", name="顾霜", entity_type="character")
write_entity(el="a2", name="贺府", entity_type="organization")
write_relation(from_entity="a1", to_entity="a2", relation_type="隶属")
""")
    assert ops["error"]["type"] == "too_many_ops"
    assert ops["applied"] == 2
    assert set(ledger.written_entities) == {"顾霜", "贺府"}
    retry = await _run(runtime, 'write_relation(from_entity="a1", to_entity="a2", relation_type="隶属")')
    assert retry["applied"] == 1
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_STEPS", 3)
    steps = await _run(runtime, "for item in [1, 2]:\n    pass")
    assert steps["error"]["type"] == "too_many_steps"


@pytest.mark.asyncio
async def test_deadline_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(program_module, "_PROGRAM_DEADLINE_S", -1.0)
    receipt = await _run(_runtime(_ledger()), "value = 1")
    assert receipt["error"]["type"] == "deadline_exceeded"
    assert receipt["applied"] == 0


@pytest.mark.asyncio
async def test_language_supports_if_tuple_unpacking_and_comparisons() -> None:
    ledger = _ledger()
    receipt = await _run(_runtime(ledger), """
left, right = (1, 2)
if left in [1, 2]:
    write_metrics(summary="条件成立", emotional_valence=0, narrative_function="铺垫")
if left != right:
    write_dialogue(candidate_index=1, verdict="not_dialogue")
if left == 1:
    write_dialogue(candidate_index=2, verdict="not_dialogue")
""")
    assert receipt["applied"] == 3
    assert ledger.metrics_payload.summary == "条件成立"
    assert set(ledger.written_dialogues) == {1, 2}


@pytest.mark.asyncio
async def test_finish_settles_after_remaining_statements() -> None:
    ledger = _ledger()
    receipt = await _run(_runtime(ledger),
                         'finish()\nwrite_metrics(summary="尾部指标", emotional_valence=0, narrative_function="铺垫")\n'
                         'for candidate in [1, 2]:\n'
                         '    write_dialogue(candidate_index=candidate, verdict="dialogue")')
    assert receipt["status"] == "applied" and receipt["applied"] == 4
    assert ledger.chapter_finished
    assert ledger.ready_chapter.metrics.summary == "尾部指标"


@pytest.mark.asyncio
async def test_error_after_finish_does_not_freeze_chapter() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(runtime,
                         'write_metrics(summary="当前指标", emotional_valence=0, narrative_function="铺垫")\n'
                         'finish()\nvalue = undefined')
    assert receipt["error"]["type"] == "undefined_name"
    assert receipt["applied"] == 1
    assert not ledger.chapter_finished and ledger.ready_chapter is None
    retry = await _run(runtime, 'for candidate in [1, 2]:\n'
                               '    write_dialogue(candidate_index=candidate, verdict="dialogue")\nfinish()')
    assert retry["status"] == "applied" and ledger.chapter_finished


@pytest.mark.asyncio
async def test_program_reads_source_anchors_links_and_cases_within_chapter_task() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(runtime, """
person = write_entity(el="a1", name="顾霜", entity_type="character")
local = read_text(paragraph_id=1, quote="顾霜")
other = read_text(paragraph_id=20, quote="顾霜")
anchor_record(record_id=person["record"], source_ref=local["source_ref"])
write_link(record_id=person["record"], source_ref=local["source_ref"],
           target_ref=other["source_ref"], kind="same_entity")
push_case(description="阿青的其他称呼尚未确定", keys=["阿青"], type="身份未确定", record_id=person["record"],
          evidence_refs=[local["source_ref"], other["source_ref"]])
write_metrics(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")
for candidate in [1, 2]:
    write_dialogue(candidate_index=candidate, verdict="dialogue", speaker=person["id"])
finish()
""")
    assert receipt["status"] == "applied"
    assert ledger.chapter_finished and ledger.ready_chapter is not None
    assert len(ledger.cross_chapter_links) == 1
    link = ledger.cross_chapter_links[0]
    assert (link.source.chapter_id, link.target.chapter_id, link.kind) == (1, 2, "same_entity")
    assert link.source in ledger.source_anchors["entity/顾霜"]
    assert ledger.authorized_text_paragraph_ids == {1, 20}
    assert len(ledger.pushed_cases) == 1
    assert {item["chapter_id"] for item in ledger.pushed_cases[0].target_ref["source_refs"]} == {1, 2}
    assert {row["tool_name"] for row in runtime.ops} >= {"read_text", "anchor_record", "write_link", "push_case"}


@pytest.mark.asyncio
async def test_program_rejects_unread_or_other_chapter_source_without_mutating_links() -> None:
    ledger = _ledger()
    runtime = _runtime(ledger)
    await _run(runtime, """
person = write_entity(el="a1", name="顾霜", entity_type="character")
other = read_text(paragraph_id=20, quote="顾霜")
""")
    receipt = await _run(runtime, """
anchor_record(record_id=person["record"], source_ref=other["source_ref"])
write_link(record_id=person["record"], source_ref="invented-ref", target_ref=other["source_ref"], kind="same_entity")
push_case(description="没有读取的证据", keys=["顾霜"], type="未确定", evidence_refs=["invented-ref"])
""")
    assert receipt["status"] == "partial" and receipt["applied"] == 0
    assert len(receipt["failed"]) == 3
    assert ledger.source_anchors == {} and ledger.cross_chapter_links == [] and ledger.pushed_cases == []
