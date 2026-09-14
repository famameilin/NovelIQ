"""2026-09-15 程序面（CodeAct）执行器合同测试

覆盖落地方案裁定的必要边界：程序内工具调用复用生产单条事务（成功保留、单条失败
只回滚该条、后续独立操作继续、依赖失败返回依赖错误）、变量跨程序保留、
True/False/None 与 true/false/null 等价、非白名单节点结构化拒绝（不裸抛）、
限额（程序字符数/内层操作数/循环项数）、finish_chapter 在程序末结算且仍以
missing_record 拒绝缺指标、压缩回执只给 applied/refs/progress/failed 而不回显
成功记录明细。

工具面与账本用测试桩（无数据库依赖），执行路径走生产 graph._execute_call。
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation import program as program_module
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.program import PROGRAM_TOOL_NAME, ProgramRuntime, build_program_tool
from src.agents.annotation.schema import ChunkMetricsInput, ChunkParagraphInfo, SearchResult
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-09-15 用于提供无数据库依赖的查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-15 用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """2026-09-15 用于返回空正文命中"""
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        """2026-09-15 用于返回空历史事件树"""
        del query, limit
        return []

    def fetch_active_case_details(self, case_id):
        """2026-09-15 用于表示没有 active 案例"""
        del case_id
        return None


def _chunk_text() -> str:
    """2026-09-15 用于提供含两个对话候选的单段章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _ledger(**overrides) -> AnnotationToolLedger:
    """2026-09-15 用于构造带事实图与段落坐标的账本"""
    text = _chunk_text()
    kwargs = {
        "run_scope": "run-1",
        "current_chapter_id": 1,
        "current_chunk_id": 1,
        "current_chunk_text": text,
        "allow_future_context": False,
        "graph": FactGraph(),
        "paragraph_info": ChunkParagraphInfo(
            paragraph_ids=[1],
            char_spans=[(0, len(text))],
            texts=[text],
        ),
    }
    kwargs.update(overrides)
    return AnnotationToolLedger(**kwargs)


def _runtime(ledger: AnnotationToolLedger, **kwargs) -> ProgramRuntime:
    """2026-09-15 用于按生产装配方式构造程序执行器"""
    return ProgramRuntime(build_annotation_tools(_QueryService(), ledger), ledger, **kwargs)


async def _run(runtime: ProgramRuntime, code: str) -> dict:
    """2026-09-15 用于执行程序并解析压缩回执"""
    return json.loads(await runtime.execute(code))


@pytest.mark.asyncio
async def test_program_writes_domains_and_returns_compressed_receipt() -> None:
    """2026-09-15 程序内多域写入 + 收尾：回执只给成功条数/句柄/进度/失败清单"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
gs = write_entity(name="顾霜", entity_type="character", el="gs", description="剑客")
write_metrics(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")
write_event(
    el="t1",
    isroot=True,
    description="喝止",
    characters=[
        {"entityid": gs["n"], "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1}
    ],
)
for i in [1, 2]:
    write_dialogue(candidate_index=i, verdict="not_dialogue")
finish_chapter()
""",
    )

    assert receipt["status"] == "applied"
    # 五条写入 + 一条收尾结算
    assert receipt["applied"] == 6
    assert "failed" not in receipt
    assert receipt["refs"]["gs"] == {"n": ledger.graph.entity_number("顾霜")}
    assert set(receipt["refs"]["t1"]) == {"node_id", "tree_id"}
    assert receipt["progress"]["entities"] == 1
    assert receipt["progress"]["dialogues"] == 2
    assert receipt["progress"]["relations"] == 0
    assert ledger.chapter_finished

    # 逐 op 记录：program_id/op_index/source_line/tool_name/status/record
    first = runtime.ops[0]
    assert first["program_id"] == "p1"
    assert first["op_index"] == 1
    assert first["tool_name"] == "write_entity"
    assert first["status"] == "success"
    assert first["record"] == "entity/顾霜"
    assert first["source_line"] == 2
    assert runtime.ops[-1]["tool_name"] == "finish_chapter"


@pytest.mark.asyncio
async def test_receipt_omits_success_record_content() -> None:
    """2026-09-15 成功记录的完整描述留在运行时状态：回执不含实体 description 等明细"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        'write_entity(name="顾霜", entity_type="character", el="gs", description="唯一描述串XYZ")',
    )
    assert receipt["applied"] == 1
    assert "唯一描述串XYZ" not in json.dumps(receipt, ensure_ascii=False)
    assert ledger.written_entities["顾霜"].description == "唯一描述串XYZ"


@pytest.mark.asyncio
async def test_json_literals_true_false_null_are_accepted() -> None:
    """2026-09-15 实验 ch5 的 KeyError: 'true' 消除：JSON 字面量与 Python 常量等价"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
write_metrics(
    summary="伏笔埋设",
    emotional_valence=1,
    narrative_function="铺垫",
    pivot_moment=false,
    cliffhanger=true,
)
write_entity(name="顾霜", entity_type="character", el="gs", description=null)
write_event(el="t1", isroot=true, description="埋设", isforeshadowing=true, confidence="low")
""",
    )
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 3
    assert ledger.metrics_payload is not None
    assert ledger.metrics_payload.cliffhanger is True
    assert ledger.metrics_payload.pivot_moment is False
    assert ledger.written_entities["顾霜"].description is None
    assert ledger.event_trees[ledger.tree_key_index["t1"]]["isforeshadowing"] is True


@pytest.mark.asyncio
async def test_undefined_name_returns_structured_error() -> None:
    """2026-09-15 未定义名称（如把 true 写进变量位）结构化回执，不再裸抛 KeyError"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        'write_entity(name=gu, entity_type="character", el="gs")',
    )
    assert receipt["status"] == "runtime_error"
    assert receipt["applied"] == 0
    assert receipt["error"]["type"] == "undefined_name"
    assert receipt["error"]["line"] == 1
    assert "未定义的名称" in receipt["error"]["message"]
    assert ledger.written_entities == {}


@pytest.mark.asyncio
async def test_unsupported_nodes_are_rejected_not_raised() -> None:
    """2026-09-15 非白名单语法（import/属性访问/while）一律结构化拒绝，不裸抛异常"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    cases = {
        "import os": "unsupported_statement",
        "x = {'a': 1}.keys()": "unsupported_expression",
        "while True:\n    pass": "unsupported_statement",
    }
    for code, expected_code in cases.items():
        receipt = await _run(runtime, code)
        assert receipt["status"] == "runtime_error", code
        assert receipt["error"]["type"] == expected_code, code
        assert receipt["applied"] == 0


@pytest.mark.asyncio
async def test_syntax_and_size_and_empty_programs_are_rejected() -> None:
    """2026-09-15 未进入执行的失败标成 rejected：语法错误/超长/空程序"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    empty = await _run(runtime, "   ")
    assert (empty["status"], empty["error"]["type"]) == ("rejected", "empty_program")

    broken = await _run(runtime, "write_entity(name=")
    assert (broken["status"], broken["error"]["type"]) == ("rejected", "syntax_error")
    assert broken["error"]["line"] == 1

    oversized = await _run(runtime, "x = " + "0" * (program_module._PROGRAM_MAX_CODE_CHARS + 1))
    assert (oversized["status"], oversized["error"]["type"]) == ("rejected", "program_too_large")


@pytest.mark.asyncio
async def test_single_op_failure_rolls_back_only_that_op() -> None:
    """2026-09-15 单条业务错误只回滚该条：失败清单带 op/行号/record/field/code/expected"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
write_entity(name="侯飞白", entity_type="character", el="hfb")
write_entity(name="贺府", entity_type="location", el="hf")
write_relation(from_entity="hfb", to_entity="hf", relation_type="隶属")
write_metrics(summary="贺府夜谈", emotional_valence=0, narrative_function="冲突")
""",
    )

    assert receipt["status"] == "partial"
    assert receipt["applied"] == 3
    assert len(receipt["failed"]) == 1
    failure = receipt["failed"][0]
    assert failure["op"] == 3
    assert failure["line"] == 4
    assert failure["tool"] == "write_relation"
    assert failure["field"] == "to_entity"
    assert failure["code"] == "endpoint_invalid"
    assert "organization" in (failure["expected"] or "")
    # 失败只影响该条：前两条实体写入与后续写入照常生效，关系没有进图
    assert set(ledger.written_entities) == {"侯飞白", "贺府"}
    assert ledger.written_relations == {}
    assert ledger.metrics_payload is not None
    assert runtime.ops[2]["error_code"] == "endpoint_invalid"


@pytest.mark.asyncio
async def test_failed_op_rolls_back_its_own_ledger_effect() -> None:
    """2026-09-15 被判失败的那条不留账本痕迹（重写同记录不重复计数）"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
write_entity(name="侯飞白", entity_type="character", el="hfb")
write_dialogue(candidate_index=1, verdict="dialogue")
for i in [2, 3]:
    write_dialogue(candidate_index=i, verdict="dialogue", speaker="不存在的键")
""",
    )
    # 首条对话成功，后两条同因失败（speaker 未登记）；失败条不进账本
    assert receipt["applied"] == 2
    assert len(receipt["failed"]) == 2
    assert all(item["code"] for item in receipt["failed"])
    assert set(ledger.written_dialogues) == {1}


@pytest.mark.asyncio
async def test_variables_persist_across_programs() -> None:
    """2026-09-15 变量跨程序保留：第二段程序直接复用第一段登记的实体编号"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    first = await _run(runtime, 'hba = write_entity(name="贺伯安", entity_type="character", el="hba")')
    assert first["applied"] == 1

    second = await _run(
        runtime,
        """
write_metrics(summary="离火反噬", emotional_valence=-2, narrative_function="转折")
write_event(
    el="t1",
    isroot=True,
    description="离火反噬",
    characters=[
        {"entityid": hba["n"], "role": "客体", "narrative_role": "客体", "action": "承受反噬", "emotion": -2}
    ],
)
finish_chapter()
""",
    )
    assert second["status"] == "applied"
    tree = ledger.event_trees[ledger.tree_key_index["t1"]]
    root = next(event for event in ledger.bound_payloads["events"] if event.node_id == tree["root_node_id"])
    assert [participant.entity for participant in root.participants] == ["贺伯安"]


@pytest.mark.asyncio
async def test_limits_are_structured_and_keep_applied_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-09-15 限额结构化拒绝：循环项数/内层操作数/步数越限均可续跑"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_LOOP_ITEMS", 2)
    loop = await _run(runtime, "for i in [1, 2, 3]:\n    write_dialogue(candidate_index=1, verdict='not_dialogue')")
    assert loop["error"]["type"] == "loop_too_long"
    assert loop["applied"] == 0

    monkeypatch.setattr(program_module, "_PROGRAM_MAX_OPS", 2)
    ops = await _run(
        runtime,
        """
write_entity(name="侯飞白", entity_type="character", el="hfb")
write_entity(name="贺府", entity_type="organization", el="hf")
write_relation(from_entity="hfb", to_entity="hf", relation_type="隶属")
""",
    )
    assert ops["error"]["type"] == "too_many_ops"
    # 越限前的两条写入保留（程序错误只中断后续语句）
    assert ops["applied"] == 2
    assert set(ledger.written_entities) == {"侯飞白", "贺府"}

    monkeypatch.setattr(program_module, "_PROGRAM_MAX_STEPS", 3)
    steps = await _run(runtime, "for i in [1, 2]:\n    write_entity(name='甲', entity_type='character', el='ab')")
    assert steps["error"]["type"] == "too_many_steps"


@pytest.mark.asyncio
async def test_finish_chapter_settles_at_program_end() -> None:
    """2026-09-15 收尾意图在程序末尾结算：finish 之后同程序内的写入照常生效"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
write_metrics(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")
finish_chapter()
write_entity(name="顾霜", entity_type="character", el="gs")
""",
    )
    assert receipt["status"] == "applied"
    assert ledger.chapter_finished
    assert "顾霜" in ledger.written_entities


@pytest.mark.asyncio
async def test_finish_chapter_without_metrics_is_reported_in_failed() -> None:
    """2026-09-15 缺指标收尾仍被拒：失败清单给出 missing_record，本章不冻结、不丢已写入"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
write_entity(name="顾霜", entity_type="character", el="gs")
finish_chapter()
""",
    )
    assert receipt["status"] == "partial"
    assert receipt["applied"] == 1
    finish = [item for item in receipt["failed"] if item["tool"] == "finish_chapter"]
    assert finish and finish[0]["code"] == "missing_record"
    assert ledger.chapter_finished is False
    assert "顾霜" in ledger.written_entities


@pytest.mark.asyncio
async def test_language_surface_if_tuple_and_unpacking() -> None:
    """2026-09-15 程序面语言边界：if/== 与 in 比较、元组、等长解包可执行"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
use_root = True
pair = (1, 2)
left, right = pair
if use_root == True:
    write_metrics(summary="条件成立", emotional_valence=0, narrative_function="铺垫")
if left in [1, 2]:
    write_dialogue(candidate_index=1, verdict="not_dialogue")
if left != right:
    write_dialogue(candidate_index=2, verdict="not_dialogue")
""",
    )
    assert receipt["applied"] == 3
    assert ledger.metrics_payload.summary == "条件成立"
    assert set(ledger.written_dialogues) == {1, 2}


@pytest.mark.asyncio
async def test_reserved_names_and_bad_calls_are_structured() -> None:
    """2026-09-15 覆盖工具名/下划线前缀变量、非具名参数、解包长度不符一律结构化拒绝"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    cases = {
        "write_entity = 1": "name_reserved",
        "_tmp = 1": "name_reserved",
        "x = write_metrics(*[1])": "bad_call",
        "a, b = (1, 2, 3)": "bad_assignment",
        "for i in 'abc':\n    pass": "unsupported_expression",
        "x = 1 if True else 2": "unsupported_expression",
    }
    for code, expected_code in cases.items():
        receipt = await _run(runtime, code)
        assert receipt["error"]["type"] == expected_code, code


@pytest.mark.asyncio
async def test_field_and_limit_type_errors_are_structured() -> None:
    """2026-09-15 fields/limit 类型错误走同一条结构化拒绝（不是裸类型错误）"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    bad_fields = await _run(runtime, 'search_text(query="顾霜", fields="content")')
    assert bad_fields["failed"][0]["code"] == "invalid_value"
    assert bad_fields["failed"][0]["field"] == "fields"

    bad_limit = await _run(runtime, 'search_text(query="顾霜", limit=true)')
    assert bad_limit["failed"][0]["code"] == "invalid_value"
    assert bad_limit["failed"][0]["field"] == "limit"


@pytest.mark.asyncio
async def test_fault_after_finish_intent_does_not_freeze_chapter() -> None:
    """2026-09-15 程序被中断时不结算收尾意图：冻结不可逆，留着章给下一轮补完"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    broken = await _run(
        runtime,
        """
write_metrics(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")
finish_chapter()
x = {'a': 1}.keys()
""",
    )
    assert broken["status"] == "runtime_error"
    assert broken["error"]["line"] == 4
    assert ledger.chapter_finished is False

    recovered = await _run(runtime, "finish_chapter()")
    assert recovered["status"] == "applied"
    assert ledger.chapter_finished


@pytest.mark.asyncio
async def test_program_tool_schema_is_code_only() -> None:
    """2026-09-15 对外合同只有 execute_code(code)：绑定面 args_schema 仅一个字符串参数"""
    ledger = _ledger()
    tool = build_program_tool(_runtime(ledger))
    assert tool.name == PROGRAM_TOOL_NAME
    assert set(tool.args_schema.model_fields) == {"code"}
    assert tool.args_schema.model_fields["code"].annotation is str


def test_program_receipt_progress_uses_ledger_counts() -> None:
    """2026-09-15 回执 progress 与 finish_chapter 回执同源（_written_counts 键集）"""
    ledger = _ledger()
    ledger.apply_metrics(
        ChunkMetricsInput(summary="摘要", emotional_valence=0, narrative_function="冲突"),
    )
    runtime = _runtime(ledger)
    counts = ledger._written_counts()
    assert counts["metrics"] == 1
    assert set(counts) == {
        "entities",
        "metrics",
        "events",
        "relations",
        "dialogues",
        "character_observations",
        "paragraph_labels",
    }
    assert runtime._receipt(status="applied", applied=0, failed=[], error=None)["progress"] == counts
