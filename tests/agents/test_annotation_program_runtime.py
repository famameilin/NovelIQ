"""2026-09-18 subagent 程序面（CodeAct）解释器语义测试

2026-09-19 双路径定案：`program.py` 的受限 AST 解释器基座有两个子类——
`ProgramRuntime`（agent 路径写者面，程序内直调正式工具）与
`subagent_program.SubagentProgramRuntime`（subagent 面，构造器写入生效）。
本文件针对两个子类共用的解释器语义（以 subagent 面为载体），覆盖：

- 语法白名单与非白名单节点的结构化拒绝（一律不裸抛）；
- 变量跨程序保留、True/False/None 与 true/false/null 等价；
- 硬限（程序字符数/内层操作数/循环项数/步数）越限可续跑、越限前的 op 保留；
- 压缩回执 status/applied/failed/reads/refs/progress 的形状与口径（refs 恒空）；
- 构造器写入生效：成功回执 {status:written, record, ref}，被拒是生产面的记录级
  拒绝（record/field/code/expected）且只作废该条；
- read 投影回显（reads）与逐 op 审计记录。

模型可见面 = 4 个检索 + 5 个案例 + finish + 八类构造器；五个 write_* 不在可见面
（程序里写它们报 unknown_tool）。工具面与账本用测试桩（无数据库依赖），执行路径
走生产 `graph._execute_call`。
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation import program as program_module
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import ChapterParagraphInfo, SearchResult
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.agents.annotation.subagent_program import SubagentProgramRuntime
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-09-18 用于提供无数据库依赖的查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-18 用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """2026-09-18 用于返回空正文命中"""
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        """2026-09-18 用于返回空历史事件树"""
        del query, limit
        return []

    def fetch_active_case_details(self, case_id):
        """2026-09-18 用于表示没有 active 案例"""
        del case_id
        return None


def _chapter_text() -> str:
    """2026-09-18 用于提供含两个对话候选的单段章文本"""
    return "“住手！”顾霜喝道。“退下。”众人散去，夜色渐深。"


def _ledger(**overrides) -> AnnotationToolLedger:
    """2026-09-18 用于构造带事实图与段落坐标的账本（三个 subagent 共享的章级账本）"""
    text = _chapter_text()
    kwargs = {
        "run_scope": "run-1",
        "current_chapter_id": 1,
        "current_chapter_text": text,
        "allow_future_context": False,
        "graph": FactGraph(),
        "paragraph_info": ChapterParagraphInfo(
            paragraph_ids=[1],
            char_spans=[(0, len(text))],
            texts=[text],
        ),
    }
    kwargs.update(overrides)
    return AnnotationToolLedger(**kwargs)


def _runtime(ledger: AnnotationToolLedger, *, role: str = "structure") -> SubagentProgramRuntime:
    """2026-09-18 用于按生产装配方式构造 subagent 程序面执行器（工具表 + 共享章级账本）"""
    tool_map = {str(tool.name): tool for tool in build_annotation_tools(_QueryService(), ledger)}
    return SubagentProgramRuntime(tool_map, ledger, SubagentAnnotation(role=role))


async def _run(runtime: SubagentProgramRuntime, code: str) -> dict:
    """2026-09-18 用于执行程序并解析压缩回执"""
    return json.loads(await runtime.execute(code))


@pytest.mark.asyncio
async def test_program_writes_domains_and_returns_compressed_receipt() -> None:
    """2026-09-18 程序内多域构造 + 收尾：回执只给成功条数/进度/失败清单，refs 恒空"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
a1 = entity(id="a1", name="顾霜", entity_type="character", evidence=1)
metric(summary="顾霜喝止众人", emotional_valence=0, narrative_function="冲突")
event(el="t1", isroot=True, description="喝止", evidence=1)
participants(
    el="t1",
    items=[
        {"entity_id": a1["ref"]["id"], "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1}
    ],
)
for i in [1, 2]:
    dialogue(candidate_index=i, verdict="not_dialogue")
finish()
""",
    )

    assert receipt["status"] == "applied"
    # 六条构造 + 一条收尾
    assert receipt["applied"] == 7
    assert "failed" not in receipt
    assert "reads" not in receipt
    # 句柄引用表（写者面遗留）已随写者面删净：本面回执不出现 refs 键
    assert "refs" not in receipt
    assert receipt["progress"]["entities"] == 1
    assert receipt["progress"]["dialogues"] == 2
    assert receipt["progress"]["relations"] == 0
    assert runtime.subagent.finished

    # 逐 op 记录：program_id/op_index/source_line/tool_name/status/record
    first = runtime.ops[0]
    assert first["program_id"] == "p1"
    assert first["op_index"] == 1
    assert first["tool_name"] == "entity"
    assert first["status"] == "success"
    assert first["record"] == "structure/entity/a1"
    assert first["source_line"] == 2
    assert runtime.ops[-1]["tool_name"] == "finish"
    assert runtime.ops[-1]["record"] == "structure/finish"


@pytest.mark.asyncio
async def test_receipt_omits_success_record_content() -> None:
    """2026-09-18 成功记录明细留在账本：回执不含 description 这类明细"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        'entity(id="a1", name="顾霜", entity_type="character", evidence=1, description="唯一描述串XYZ")',
    )
    assert receipt["applied"] == 1
    assert "唯一描述串XYZ" not in json.dumps(receipt, ensure_ascii=False)
    assert ledger.written_entities["顾霜"].description == "唯一描述串XYZ"


@pytest.mark.asyncio
async def test_json_literals_true_false_null_are_accepted() -> None:
    """2026-09-18 实验 ch5 的 KeyError: 'true' 消除：JSON 字面量与 Python 常量等价"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
metric(
    summary="伏笔埋设",
    emotional_valence=1,
    narrative_function="铺垫",
    pivot_moment=false,
    cliffhanger=true,
)
entity(id="a1", name="顾霜", entity_type="character", evidence=1, description=null)
event(el="t1", isroot=true, description="埋设", evidence=1, isforeshadowing=true, confidence="low")
""",
    )
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 3
    assert ledger.metrics_payload is not None
    assert ledger.metrics_payload.cliffhanger is True
    assert ledger.metrics_payload.pivot_moment is False
    assert ledger.written_entities["顾霜"].description is None
    assert ledger.event_trees[ledger.tree_key_index["structure:t1"]]["isforeshadowing"] is True


@pytest.mark.asyncio
async def test_undefined_name_returns_structured_error() -> None:
    """2026-09-18 未定义名称（如把 true 写进变量位）结构化回执，不再裸抛 KeyError"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        'entity(id="a1", name=gu, entity_type="character", evidence=1)',
    )
    assert receipt["status"] == "runtime_error"
    assert receipt["applied"] == 0
    assert receipt["error"]["type"] == "undefined_name"
    assert receipt["error"]["line"] == 1
    assert ledger.written_entities == {}


@pytest.mark.asyncio
async def test_unsupported_nodes_are_rejected_not_raised() -> None:
    """2026-09-18 非白名单语法（import/属性访问/while）一律结构化拒绝，不裸抛异常"""
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
async def test_write_tools_are_not_in_model_visible_surface() -> None:
    """2026-09-18 写者面五个 write_* 已退出可见面：程序里写它们一律 unknown_tool"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    for name in ("write_entity", "write_event", "write_relation", "write_dialogue", "write_metrics"):
        receipt = await _run(runtime, f"{name}()")
        assert receipt["status"] == "runtime_error", name
        assert receipt["error"]["type"] == "unknown_tool", name
        assert receipt["applied"] == 0, name
    assert ledger.written_entities == {}


@pytest.mark.asyncio
async def test_syntax_and_size_and_empty_programs_are_rejected() -> None:
    """2026-09-18 未进入执行的失败标成 rejected：语法错误/超长/空程序"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    empty = await _run(runtime, "   ")
    assert (empty["status"], empty["error"]["type"]) == ("rejected", "empty_program")

    broken = await _run(runtime, "entity(id=")
    assert (broken["status"], broken["error"]["type"]) == ("rejected", "syntax_error")
    assert broken["error"]["line"] == 1

    oversized = await _run(runtime, "x = " + "0" * (program_module._PROGRAM_MAX_CODE_CHARS + 1))
    assert (oversized["status"], oversized["error"]["type"]) == ("rejected", "program_too_large")


@pytest.mark.asyncio
async def test_single_op_failure_rolls_back_only_that_op() -> None:
    """2026-09-18 单条业务错误只回滚该条：失败清单带 op/行号/record/field/code/expected"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
entity(id="hfb", name="侯飞白", entity_type="character", evidence=1)
entity(id="hf", name="贺府", entity_type="location", evidence=1)
relation(from_id="hfb", to_id="hf", relation_type="隶属", evidence=1)
metric(summary="贺府夜谈", emotional_valence=0, narrative_function="冲突")
""",
    )

    assert receipt["status"] == "partial"
    assert receipt["applied"] == 3
    assert len(receipt["failed"]) == 1
    failure = receipt["failed"][0]
    assert failure["op"] == 3
    assert failure["line"] == 4
    assert failure["tool"] == "relation"
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
    """2026-09-18 被判失败的那条不留账本痕迹（重写同记录不重复计数）"""
    ledger = _ledger()
    runtime = _runtime(ledger, role="evidence")
    receipt = await _run(
        runtime,
        """
entity(id="hf", name="贺府", entity_type="location", evidence=1)
dialogue(candidate_index=1, verdict="not_dialogue")
for i in [2]:
    dialogue(candidate_index=i, verdict="dialogue", evidence=1, speaker_id="hf")
""",
    )
    # 首条对话成功；说话人不是 character 的那条被生产面拒绝，不进账本
    assert receipt["applied"] == 2
    assert len(receipt["failed"]) == 1
    assert all(item["code"] for item in receipt["failed"])
    assert receipt["failed"][0]["code"] == "not_character"
    assert set(ledger.written_dialogues) == {1}


@pytest.mark.asyncio
async def test_variables_persist_across_programs() -> None:
    """2026-09-18 变量跨程序保留：第二段程序直接复用第一段构造器回执里的引用键"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    first = await _run(runtime, 'hba = entity(id="hba", name="贺伯安", entity_type="character", evidence=1)')
    assert first["applied"] == 1

    second = await _run(
        runtime,
        """
metric(summary="离火反噬", emotional_valence=-2, narrative_function="转折")
event(el="t1", isroot=True, description="离火反噬", evidence=1)
participants(
    el="t1",
    items=[
        {"entity_id": hba["ref"]["id"], "role": "客体", "narrative_role": "客体", "action": "承受反噬", "emotion": -2}
    ],
)
finish()
""",
    )
    assert second["status"] == "applied"
    tree = ledger.event_trees[ledger.tree_key_index["structure:t1"]]
    root = next(event for event in ledger.bound_payloads["events"] if event.node_id == tree["root_node_id"])
    assert [participant.entity for participant in root.participants] == ["贺伯安"]


@pytest.mark.asyncio
async def test_limits_are_structured_and_keep_applied_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-09-18 限额结构化拒绝：循环项数/内层操作数/步数越限均可续跑"""
    ledger = _ledger()
    runtime = _runtime(ledger, role="evidence")
    monkeypatch.setattr(program_module, "_PROGRAM_MAX_LOOP_ITEMS", 2)
    loop = await _run(runtime, "for i in [1, 2, 3]:\n    dialogue(candidate_index=1, verdict='not_dialogue')")
    assert loop["error"]["type"] == "loop_too_long"
    assert loop["applied"] == 0

    monkeypatch.setattr(program_module, "_PROGRAM_MAX_OPS", 2)
    ops = await _run(
        runtime,
        """
entity(id="hfb", name="侯飞白", entity_type="character", evidence=1)
entity(id="hf", name="贺府", entity_type="organization", evidence=1)
relation(from_id="hfb", to_id="hf", relation_type="隶属", evidence=1)
""",
    )
    assert ops["error"]["type"] == "too_many_ops"
    # 越限前的两条写入保留（程序错误只中断后续语句）
    assert ops["applied"] == 2
    assert set(ledger.written_entities) == {"侯飞白", "贺府"}

    monkeypatch.setattr(program_module, "_PROGRAM_MAX_STEPS", 3)
    steps = await _run(runtime, "for i in [1, 2]:\n    entity(id='a1', name='甲', entity_type='character', evidence=1)")
    assert steps["error"]["type"] == "too_many_steps"


@pytest.mark.asyncio
async def test_language_surface_if_tuple_and_unpacking() -> None:
    """2026-09-18 程序面语言边界：if/== 与 in 比较、元组、等长解包可执行"""
    ledger = _ledger()
    runtime = _runtime(ledger, role="evidence")
    receipt = await _run(
        runtime,
        """
use_root = True
pair = (1, 2)
left, right = pair
if use_root == True:
    metric(summary="条件成立", emotional_valence=0, narrative_function="铺垫")
if left in [1, 2]:
    dialogue(candidate_index=1, verdict="not_dialogue")
if left != right:
    dialogue(candidate_index=2, verdict="not_dialogue")
""",
    )
    assert receipt["applied"] == 3
    assert ledger.metrics_payload.summary == "条件成立"
    assert set(ledger.written_dialogues) == {1, 2}


@pytest.mark.asyncio
async def test_reserved_names_and_bad_calls_are_structured() -> None:
    """2026-09-18 覆盖构造器名/下划线前缀变量、非具名参数、解包长度不符一律结构化拒绝"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    cases = {
        "entity = 1": "name_reserved",
        "_tmp = 1": "name_reserved",
        "x = metric(*[1])": "bad_call",
        "a, b = (1, 2, 3)": "bad_assignment",
        "for i in 'abc':\n    pass": "unsupported_expression",
        "x = 1 if True else 2": "unsupported_expression",
    }
    for code, expected_code in cases.items():
        receipt = await _run(runtime, code)
        assert receipt["error"]["type"] == expected_code, code


@pytest.mark.asyncio
async def test_field_and_limit_type_errors_are_structured() -> None:
    """2026-09-18 fields/limit 类型错误走同一条结构化拒绝（不是裸类型错误）"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    bad_fields = await _run(runtime, 'search_text(query="顾霜", fields="content")')
    assert bad_fields["failed"][0]["code"] == "invalid_value"
    assert bad_fields["failed"][0]["field"] == "fields"

    bad_limit = await _run(runtime, 'search_text(query="顾霜", limit=true)')
    assert bad_limit["failed"][0]["code"] == "invalid_value"
    assert bad_limit["failed"][0]["field"] == "limit"


@pytest.mark.asyncio
async def test_read_projection_is_echoed_in_receipt_reads() -> None:
    """2026-09-18 程序内检索的读结果回显在 reads（构造器写入仍只回句柄）"""
    ledger = _ledger()
    runtime = _runtime(ledger)
    receipt = await _run(
        runtime,
        """
search_text(query="顾霜")
entity(id="a1", name="顾霜", entity_type="character", evidence=1)
""",
    )
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 2
    reads = receipt["reads"]
    assert len(reads) == 1
    assert reads[0]["op"] == 1
    assert reads[0]["tool"] == "search_text"
    assert reads[0]["line"] == 2
    assert json.loads(reads[0]["result"]) == []
    assert all(item["tool"] != "entity" for item in reads)
