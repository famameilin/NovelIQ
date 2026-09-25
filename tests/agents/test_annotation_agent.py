"""章节级标注 Agent（agent 路径，程序面）LangGraph 与 Runner 测试

2026-09-19 双路径定案：agent 路径（单块章）的模型可见面=[execute_code, finish]，模型
把工具调用写成 Python 程序提交；本文件按程序面驱动（_program_message），覆盖：

- 程序内跨领域调用全部生效、逐条独立回滚、失败不阻塞同程序 finish；
- 绑定面恒为 [execute_code, finish]（finish 也可直发，两条通道同一条收尾判定；
  分发面=完整工具表由 ProgramRuntime 执行）；
- 【进度账本】逐请求注入与临近上限收尾提醒；
- Runner 单次尝试/审计/失败回滚与章正文校验。
"""

from __future__ import annotations

import json
import unicodedata
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import NAMESPACE_DNS, uuid5

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationInvariantError,
)
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.program import ProgramRuntime, build_program_tool
from src.agents.annotation.prompts import build_chapter_message
from src.agents.annotation.runner import (
    run_annotation_agent,
    validate_bound_annotation,
)
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundDialogue,
    BoundParagraphLabel,
    ChapterMetricsInput,
    ChapterParagraphInfo,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-07 用于提供无数据库依赖的新合同查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-08-07 用于返回空案例与伏笔检索结果"""
        del query, hidden_case_ids, case_type, limit
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于返回空原文候选"""
        del query, range_name, limit
        return []

    def fetch_active_case_details(self, case_id):
        """2026-08-07 用于表示测试中没有 active 案例"""
        del case_id
        return None


class _SequenceLLM:
    """2026-08-07 用于按顺序返回 Agent 消息的测试模型（仅 ainvoke，无流式）"""

    def __init__(self, responses: list[AIMessage]) -> None:
        """2026-08-07 用于保存待返回的模型消息序列"""
        self.responses = list(responses)
        self.calls = 0
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        """2026-09-13 用于满足 LangChain 模型绑定合同"""
        return self

    async def ainvoke(self, messages):
        """2026-08-07 用于返回下一条测试模型消息并记录输入"""
        self.calls += 1
        self.captured_messages.append(list(messages))
        return self.responses.pop(0)


def _tool_message(calls: list[dict]) -> AIMessage:
    """2026-08-07 用于构造带工具调用的模型回复"""
    return AIMessage(content="", tool_calls=calls)


def _write_call(
    name: str,
    args: dict,
    *,
    call_id: str,
) -> dict:
    """2026-08-07 用于构造单个工具调用"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _entity_id(name: str) -> str:
    """2026-09-19 用于按 FactGraph 同款算法铸造实体 run 级 uuid（uuid5(run_scope+归一化名)）

    本文件的 FactGraph() 用默认 run_scope=""（uuid 命名空间键 = "novel-annotation-entity::名"）。
    """
    key = unicodedata.normalize("NFC", name).strip().casefold()
    return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity::{key}"))


# ----------------------------------------------------------------------
# 程序面驱动：模型回复=一条 execute_code 调用，code 里的语句即工具调用


def _program_message(code: str, call_id: str = "call-program") -> AIMessage:
    """2026-09-19 用于构造一条 execute_code 程序回复（程序内的语句即工具调用）"""
    return _tool_message([_write_call("execute_code", {"code": code}, call_id=call_id)])


def _entity_stmt(
    name: str = "顾霜",
    entity_type: str = "character",
    *,
    extra_args: str = "",
) -> str:
    """2026-09-19 用于构造 write_entity 程序语句（el=章内引用键）"""
    return f'write_entity(name="{name}", entity_type="{entity_type}", el="{name}"{extra_args})'


def _metrics_stmt(*, labels: bool = True) -> str:
    """2026-09-19 用于构造 write_metrics 程序语句（段落标签随本域提交）"""
    labels_arg = ', labels=[{"paragraph_id": 1, "emotion": -2}]' if labels else ""
    return f'write_metrics(summary="住手回荡", emotional_valence=0, narrative_function="铺垫"{labels_arg})'


def _event_root_stmt(
    tree_key: str = "t1",
    description: str = "顾霜喝止众人",
    action: str = "喝止",
    *,
    emotion: int = -1,
) -> str:
    """2026-09-19 用于构造 write_event 根事件程序语句"""
    return (
        f'write_event(el="{tree_key}", isroot=True, description="{description}", '
        'characters=[{"entityid": "顾霜", "role": "主体", "narrative_role": "主体", '
        f'"action": "{action}", "emotion": {emotion}}}])'
    )


def _event_child_stmt(
    tree_key: str = "t1",
    child_key: str = "e1",
    description: str = "顾霜收势",
    action: str = "收势",
    *,
    emotion: int = 0,
) -> str:
    """2026-09-19 用于构造 write_event 子事件程序语句"""
    return (
        f'write_event(el="{tree_key}/{child_key}", isroot=False, type="main", '
        f'description="{description}", '
        'characters=[{"entityid": "顾霜", "role": "主体", "narrative_role": "主体", '
        f'"action": "{action}", "emotion": {emotion}}}])'
    )


def _relation_stmt() -> str:
    """2026-09-19 用于构造 write_relation 程序语句（两端=实体引用）"""
    return 'write_relation(from_entity="顾霜", to_entity="褚大山", relation_type="敌对")'


def _dialogue_stmt() -> str:
    """2026-09-19 用于构造 write_dialogue 程序语句（第一条候选判为真实对话）"""
    return 'write_dialogue(candidate_index=1, verdict="dialogue", speaker=None, tone="平静")'


def _finish_stmt() -> str:
    """2026-09-19 用于构造 finish 收尾声明（工具体只回 pending，程序末尾结算）"""
    return "finish()"


def _serial_program_messages() -> list[AIMessage]:
    """2026-09-19 用于构造三轮程序回复：实体+指标 → 事件树 → 对话+finish"""
    return [
        _program_message("\n".join([_entity_stmt(), _metrics_stmt()])),
        _program_message("\n".join([_event_root_stmt(), _event_child_stmt()])),
        _program_message("\n".join([_dialogue_stmt(), _finish_stmt()])),
    ]


async def _invoke_graph(
    llm: _SequenceLLM,
    *,
    allow_future_context: bool,
    chapter: tuple[int, str] | None = None,
    max_iterations: int = 30,
    ledger: AnnotationToolLedger | None = None,
) -> dict:
    """2026-09-19 用于执行最小单章程序面 LangGraph（绑定面=[execute_code, finish]）"""
    resolved_chapter = chapter or (1, "“住手”回荡")
    chapter_id, chapter_text = resolved_chapter
    if ledger is None:
        ledger = AnnotationToolLedger(
            run_scope="run-1",
            current_chapter_id=1,
            current_chapter_text=chapter_text,
            allow_future_context=allow_future_context,
            graph=FactGraph(),
            paragraph_info=ChapterParagraphInfo(
                paragraph_ids=[0],
                char_spans=[(0, len(chapter_text))],
                texts=[chapter_text],
            ),
        )
    tools = build_annotation_tools(_QueryService(), ledger)
    finish_tool = {str(tool.name): tool for tool in tools}["finish"]
    program_tool = build_program_tool(ProgramRuntime(tools, ledger))
    graph = build_annotation_graph(
        llm,
        [*tools, program_tool],
        ledger=ledger,
        max_iterations=max_iterations,
        bind_tools=[program_tool, finish_tool],
        program_tool_name=str(program_tool.name),
    )
    return await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chapter_message(
                                                chapter_text=chapter_text,
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        }
    )


def _bound_annotation(*, summary: str = "顾霜进入山门") -> BoundChapterAnnotation:
    """2026-08-07 用于构造 Runner 重试测试的最小章节标注（2026-09-19 章即块拍平）"""
    return BoundChapterAnnotation(
        metrics=ChapterMetricsInput(
            summary=summary,
            emotional_valence=0,
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=[],
        events=[],
    )


def _agent_result() -> AgentRunResult:
    """2026-08-10 用于构造 Runner 重试测试的完整成功结果（新审计结构）"""
    return AgentRunResult(
        run_id="run-1",
        chapter_id=1,
        annotation=_bound_annotation(),
        resolved_cases=[],
        pushed_cases=[],
        audit=AgentRunAudit(
            allow_future_context=False,
            write_records=[],
            authorized_chapter_ids=[1],
            authorized_text_paragraph_ids=[],
        ),
    )


def _tool_receipts(captured_round: list) -> list[str]:
    """2026-08-10 用于提取某轮模型请求中的全部 ToolMessage 内容"""
    return [str(message.content) for message in captured_round if getattr(message, "type", "") == "tool"]


@pytest.mark.asyncio
async def test_second_write_entities_appends_to_catalog_not_replaces() -> None:
    """2026-08-26 回归（2026-09-04 单一写面改契约为 op log）：实体登记追加语义必须落进 FactGraph

    2026-09-13 小调用改造后一次登记一个实体（write_entity），op log 仍按提交顺序
    累积；同名重交按更新语义覆盖（tags/description 增量）。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, 4)],
            texts=["住手回荡"],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    by_name = {tool.name: tool for tool in tools}
    await by_name["search_graph"].ainvoke({"entities": ["侯飞白", "褚大山", "猴子"]})
    await by_name["write_entity"].ainvoke(
        {"name": "侯飞白", "entity_type": "character", "el": "侯飞白", "description": "贺军情报头子之子"}
    )
    await by_name["write_entity"].ainvoke({"name": "褚大山", "entity_type": "character", "el": "褚大山"})
    await by_name["write_entity"].ainvoke(
        {"name": "猴子", "entity_type": "character", "el": "猴子", "description": "侯飞白外号"}
    )
    await by_name["write_entity"].ainvoke(
        {"name": "侯飞白", "entity_type": "character", "el": "侯飞白", "tags": ["小孩"]}
    )
    assert "entities" not in ledger.bound_payloads
    ops = ledger.graph.entity_ops
    assert [op["name"] for op in ops] == ["侯飞白", "褚大山", "猴子", "侯飞白"]
    assert ops[0]["description"] == "贺军情报头子之子"
    assert ops[3]["tags"] == ["小孩"]


@pytest.mark.asyncio
async def test_entity_reregistration_same_content_is_idempotent() -> None:
    """2026-09-13 同键同内容重放返回相同 written 回执且不重复写操作日志（重试不重复造数据）"""
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
    )
    tools = {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}
    first = await tools["write_entity"].ainvoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    replay = await tools["write_entity"].ainvoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    assert json.loads(first) == json.loads(replay)
    assert len(ledger.graph.entity_ops) == 1


@pytest.mark.asyncio
async def test_cross_domain_program_statements_all_take_effect() -> None:
    """2026-09-19 程序面：同一程序里的跨领域语句全部生效（写入即生效，失败只作废该条）"""
    llm = _SequenceLLM(
        [
            _program_message(
                "\n".join(
                    [
                        _entity_stmt(extra_args=', tags=["少年"]'),
                        _dialogue_stmt(),
                        _metrics_stmt(labels=False),
                    ]
                )
            ),
            _program_message("\n".join([_event_root_stmt(), _event_child_stmt()])),
            _program_message(_finish_stmt()),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 3
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 1
    # 压缩回执：三条语句全部成功（成功明文不回显，只报条数与进度）
    assert '"applied": 3' in receipts[0]
    assert '"status": "applied"' in receipts[0]


@pytest.mark.asyncio
async def test_failed_statement_rolls_back_only_itself() -> None:
    """2026-09-19 程序面：单条语句业务失败只作废该条并出现在 failed 清单，下一轮可修正"""
    bad_program = _program_message(
        "\n".join(['write_entity(name=" ", entity_type="character", el=" ")', _metrics_stmt(labels=False)])
    )
    llm = _SequenceLLM(
        [
            bad_program,
            *_serial_program_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 1
    receipt = receipts[0]
    assert '"status": "partial"' in receipt
    assert '"applied": 1' in receipt
    assert '"tool": "write_entity"' in receipt
    assert '"code": "invalid_combination"' in receipt


@pytest.mark.asyncio
async def test_failed_entity_statement_does_not_block_same_program_metrics() -> None:
    """2026-09-19 程序面：失败语句后面的语句继续执行（失败只作废自己，不中断同程序）"""
    bad_program = _program_message(
        "\n".join(['write_entity(name=" ", entity_type="character", el=" ")', _metrics_stmt(labels=False)])
    )
    llm = _SequenceLLM([bad_program, *_serial_program_messages()])
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    receipt = _tool_receipts(llm.captured_messages[1])[0]
    # 同一程序里实体失败、指标照常落账：applied=1（指标），失败清单只含实体那一条
    assert '"applied": 1' in receipt
    assert '"tool": "write_entity"' in receipt
    assert '"tool": "write_metrics"' not in receipt


@pytest.mark.asyncio
async def test_partial_programs_do_not_auto_finalize() -> None:
    """2026-09-19 未声明 finish 时写入保持开放：下一轮可继续追加，收尾轮一次性冻结"""
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="“住手”回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, 7)],
            texts=["“住手”回荡"],
        ),
    )
    llm = _SequenceLLM(
        [
            _program_message("\n".join([_entity_stmt(), _metrics_stmt(labels=False)])),
            _program_message("\n".join([_event_root_stmt(), _event_child_stmt()])),
            _program_message(
                "\n".join(
                    [
                        _event_root_stmt(tree_key="t2", description="顾霜追击众人", action="追击"),
                        _event_child_stmt(tree_key="t2", description="众人退去", action="退去"),
                        _dialogue_stmt(),
                        _finish_stmt(),
                    ]
                )
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False, ledger=ledger)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    # 两棵树各 2 个节点（根 + 子事件）都进了同一次收尾后的最终标注
    annotation = ledger.annotation
    assert annotation is not None
    events = annotation.events
    assert [event.description for event in events] == [
        "顾霜喝止众人",
        "顾霜收势",
        "顾霜追击众人",
        "众人退去",
    ]


@pytest.mark.asyncio
async def test_three_event_trees_and_relation_in_one_program() -> None:
    """2026-09-19 程序面：同一程序写三棵事件树与一条关系，applied=7，收尾按域汇总"""
    llm = _SequenceLLM(
        [
            _program_message(
                "\n".join([_entity_stmt(), _entity_stmt(name="褚大山"), _metrics_stmt(labels=False)])
            ),
            _program_message(
                "\n".join(
                    [
                        _event_root_stmt(),
                        _event_child_stmt(),
                        _event_root_stmt(tree_key="t2", description="顾霜追击", action="追击"),
                        _event_child_stmt(tree_key="t2", description="顾霜拦截去路", action="拦截"),
                        _event_root_stmt(tree_key="t3", description="顾霜抱拳离场", action="抱拳"),
                        _event_child_stmt(tree_key="t3", description="顾霜散场", action="散去"),
                        _relation_stmt(),
                    ]
                )
            ),
            _program_message("\n".join([_dialogue_stmt(), _finish_stmt()])),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    event_round_receipts = _tool_receipts(llm.captured_messages[2])
    # 第 3 次请求携带前两轮的程序回执：turn2 = 三棵树（6 节点）+ 一条关系，applied=7
    assert len(event_round_receipts) == 2
    assert '"applied": 7' in event_round_receipts[1]
    assert '"events": 6' in event_round_receipts[1]
    assert '"relations": 1' in event_round_receipts[1]
    # 章完成由账本收尾状态驱动（finish 在程序内声明、运行时内部结算）
    assert result["phase"] == "completed"


@pytest.mark.asyncio
async def test_failed_event_statement_does_not_block_relation_in_same_program() -> None:
    """2026-09-19 程序面：事件语句失败时同程序关系语句照常生效，下一轮修正后收尾"""
    invalid_participation = (
        'write_event(el="t1/e2", isroot=False, type="main", description="顾霜拦截去路", '
        'characters=[{"entityid": "顾霜", "role": "主体", "narrative_role": "主体", '
        '"action": "拦截", "emotion": 9}])'
    )
    fixed_participation = (
        'write_event(el="t1/e2", isroot=False, type="main", description="顾霜拦截去路", '
        'characters=[{"entityid": "顾霜", "role": "主体", "narrative_role": "主体", '
        '"action": "拦截", "emotion": -1}])'
    )
    llm = _SequenceLLM(
        [
            _program_message(
                "\n".join([_entity_stmt(), _entity_stmt(name="褚大山"), _metrics_stmt(labels=False)])
            ),
            _program_message(
                "\n".join([_event_root_stmt(), _event_child_stmt(), invalid_participation, _relation_stmt()])
            ),
            _program_message("\n".join([fixed_participation, _dialogue_stmt(), _finish_stmt()])),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    event_round_receipts = _tool_receipts(llm.captured_messages[2])
    assert len(event_round_receipts) == 2
    assert '"field": "emotion"' in event_round_receipts[1]
    assert '"applied": 3' in event_round_receipts[1]


@pytest.mark.asyncio
async def test_failed_statement_in_same_program_does_not_block_finish() -> None:
    """2026-09-13 同程序失败语句不阻塞收尾：失败只回滚自己，收尾按已写入内容完成

    旧合同此处是 round_failed 拒绝（要求先修正再重交），那条规则把收尾绑到无关记录的
    成功上：末轮出现一次失败就足以让整章作废（run 1b388eb3 第 2 章实锤）。
    """
    invalid_root = (
        'write_event(el="t1", isroot=True, description="顾霜喝止众人", '
        'characters=[{"entityid": "顾霜", "role": "主体", "narrative_role": "主体", '
        '"action": "怒斥", "emotion": 9}])'
    )
    llm = _SequenceLLM(
        [
            _program_message("\n".join([_entity_stmt(), _metrics_stmt(labels=False)])),
            _program_message(
                "\n".join([_event_root_stmt(), _event_child_stmt(), invalid_root, _finish_stmt()])
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    # 末轮回执只在最终 state（captured_messages 是各次请求的历史，不含该轮自己的 ToolMessage）；
    # 程序面的失败清单在程序回执的 failed 里，finish 的结算在运行时内部完成
    receipts = _tool_receipts(result["messages"])
    rejected = [receipt for receipt in receipts if '"code": "out_of_range"' in receipt]
    assert len(rejected) == 1, "越界 emotion 的那一条必须被单独拒绝并回执"
    assert '"record": "t1/root"' in rejected[0]
    assert '"status": "partial"' in rejected[0]
    # 失败不阻塞收尾：同程序的 finish 正常结算，坏记录本来就没进载荷
    assert result["phase"] == "completed"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_truncated_tool_call_skips_program_and_feeds_error_receipt() -> None:
    """
    2026-08-11 用于验证带截断标记的工具调用不执行业务写入，
    只回喂"参数不完整"错误回执，模型补全后章节仍能完成。
    """
    truncated_program = {
        "name": "execute_code",
        "args": {},
        "id": "call-program-truncated",
        "type": "tool_call",
        "truncated": True,
        "truncated_args": '{"code": "write_entity(name="',
    }
    # 聚合器在运行时以属性赋值挂载截断标记（绕过 create_tool_call 重建），测试同样模拟
    first_message = AIMessage(content="")
    first_message.tool_calls = [truncated_program]
    llm = _SequenceLLM([first_message, *_serial_program_messages()])
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    assert len(rejected) == 1
    assert '"tool": "execute_code"' in rejected[0]


@pytest.mark.asyncio
async def test_auto_finalize_invariant_error_terminates_chapter() -> None:
    """2026-08-10 用于验证收尾后 ready_chapter 缺失时按不变量错误终止而非回环修正

    2026-09-13 变化点：不再有六域回执齐备这一判据，auto_finalize 只看
    ledger.chapter_finished；此处模拟 finish 结算通过但 ready_chapter 被破坏。
    """
    llm = _SequenceLLM(_serial_program_messages())

    class _BrokenLedger(AnnotationToolLedger):
        """2026-09-13 用于模拟已收尾但 ready_chapter 被破坏的账本"""

        def finish_chapter(self) -> dict:
            """2026-09-13 用于正常收尾后清掉 ready_chapter"""
            receipt = super().finish_chapter()
            self.ready_chapter = None
            return receipt

    chapter_text = "\u201c住手\u201d回荡"
    ledger = _BrokenLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text=chapter_text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chapter_text))],
            texts=[chapter_text],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    finish_tool = {str(tool.name): tool for tool in tools}["finish"]
    program_tool = build_program_tool(ProgramRuntime(tools, ledger))
    graph = build_annotation_graph(
        llm,
        [*tools, program_tool],
        ledger=ledger,
        max_iterations=30,
        bind_tools=[program_tool, finish_tool],
        program_tool_name=str(program_tool.name),
    )
    with pytest.raises(AnnotationInvariantError):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(
                        content=build_chapter_message(
                                                        chapter_text=chapter_text,
                            candidates=ledger.dialogue_candidates,
                        )
                    ),
                ],
                "phase": "chapter_open",
                "iterations": 0,
                "error": None,
            }
        )
    assert llm.calls == 3
    assert ledger.annotation is None
    assert ledger.completed_chapters == []


def test_validate_bound_annotation_verifies_dialogue_original_text() -> None:
    """2026-08-07 用于验证对话原文位置与内容由系统绑定且可回查"""
    annotation = _bound_annotation()
    annotation.dialogues = [
        BoundDialogue(
            candidate_index=1,
            candidate_key="dlg_1",
            content="住手",
            start=0,
            end=2,
        )
    ]
    with pytest.raises(ValueError):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            chapter_text="顾霜进入山门",
        )


@pytest.mark.asyncio
async def test_runner_single_failure_raises_without_chapter_retry() -> None:
    """2026-08-11 用于验证章节不再整章重试：单次失败直接抛异常且只使用一个只读 Session"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=RuntimeError("model failed")),
    ) as run_attempt:
        with pytest.raises(RuntimeError, match="model failed"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                chapter_text="顾霜进入山门",
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=MagicMock(),
            )
    assert run_attempt.await_count == 1


@pytest.mark.asyncio
async def test_runner_does_not_retry_authorization_errors() -> None:
    """2026-08-07 用于验证授权错误直接失败且不会进入第二次尝试"""
    session = MagicMock()
    recorder = MagicMock()

    def session_factory():
        return session

    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=AnnotationAuthorizationError("unauthorized")),
    ) as run_attempt:
        with pytest.raises(AnnotationAuthorizationError, match="unauthorized"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                chapter_text="顾霜进入山门",
                query_service_factory=lambda current: _QueryService(),
                session_factory=session_factory,
                llm=MagicMock(),
                audit_recorder=recorder,
            )
    assert run_attempt.await_count == 1
    # 2026-09-16 连接粒度：入口不再自开只读会话，工厂原样转交查询服务按次取还
    assert run_attempt.call_args.kwargs["session_factory"] is session_factory
    session.rollback.assert_not_called()
    session.close.assert_not_called()
    assert recorder.finish_invocation.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_runner_records_single_error_invocation() -> None:
    """2026-08-11 用于验证单次失败开启并收口一条 error 审计 invocation"""
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                chapter_text="顾霜进入山门",
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=recorder,
            )
    assert recorder.start_invocation.call_count == 1
    assert recorder.start_invocation.call_args.kwargs["attempt_number"] == 1
    finish_calls = recorder.finish_invocation.call_args_list
    assert len(finish_calls) == 1
    assert finish_calls[0].kwargs["status"] == "error"
    assert "boom" in str(finish_calls[0].kwargs.get("final_error", ""))


@pytest.mark.asyncio
async def test_runner_returns_result_from_single_attempt() -> None:
    """2026-08-11 用于验证单次尝试成功即返回并收口 success 审计"""
    result = _agent_result()
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=result),
    ) as run_attempt:
        actual = await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            chapter_text="顾霜进入山门",
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=recorder,
        )
    assert actual == result
    assert run_attempt.await_count == 1
    assert recorder.finish_invocation.call_args.kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_runner_rejects_empty_chapter_text() -> None:
    """2026-08-14 M7 用于校验章正文非空（2026-09-19 章即块：一章一份正文）"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=_agent_result()),
    ) as run_attempt:
        with pytest.raises(AnnotationInputError):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                chapter_text="   ",
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=MagicMock(),
            )
    assert run_attempt.await_count == 0


@pytest.mark.asyncio
async def test_invalid_change_kind_returns_failed_receipt() -> None:
    """
    2026-08-12 用于验证非法 change_kind 以失败回执回到模型继续对话，
    而不是抛出让整章失败（下游持久化只认闭合枚举）。

    2026-09-14 解决类工具并入 schema 层失败翻译：回执从 tool/error 通用形态
    收窄为 record/field/code/expected 结构化拒绝（field=change_kind、可自纠）。
    2026-09-19 程序面：拒绝进入本程序回执的 failed 清单，字段口径不变。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        graph=FactGraph(
            history_entity_types={"顾霜": "character", "顾老": "character"},
            history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        ),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len("\u201c住手\u201d回荡"))],
            texts=["\u201c住手\u201d回荡"],
        ),
    )
    llm = _SequenceLLM(
        [
            _program_message(
                'write_relation(from_entity="顾霜", to_entity="顾老", '
                'relation_type="同一人物", change_kind="强化关系")'
            ),
            *_serial_program_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False, ledger=ledger)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 1
    assert '"field": "change_kind"' in receipts[0]
    assert '"code": "invalid_value"' in receipts[0]
    assert '"tool": "write_relation"' in receipts[0]
    assert ledger.resolved_cases == []


@pytest.mark.asyncio
async def test_runner_resets_fact_graph_chapter_state_on_failure() -> None:
    """2026-08-12 用于验证章节失败路径恢复 FactGraph 历史快照，不残留当章脏状态

    2026-08-13 P1-1：begin_chapter 把章前状态并入 history_*，失败回滚恢复到
    「本章开始前」快照（上一章提交结果），而非 run 启动空状态。
    """
    graph_state = FactGraph(
        history_entity_types={"顾霜": "character"},
        history_entity_names={"顾霜": "顾霜"},
        history_relations={("顾霜", "顾老", "同一人物")},
    )
    assert graph_state.active_relations
    session = MagicMock()
    recorder = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(side_effect=RuntimeError("model failed")),
    ):
        with pytest.raises(RuntimeError, match="model failed"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                chapter_text="顾霜进入山门",
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=recorder,
                graph_state=graph_state,
            )
    # 失败后恢复到本章开始前快照：上一章提交的边与实体保留，章内追踪清空
    # （active_relations 按稳定键归一化，端点按字典序）
    assert graph_state.active_relations == {("顾老", "顾霜", "同一人物")}
    assert graph_state.chapter_added_relations == set()
    assert graph_state.entity_types == {"顾霜": "character"}


def test_validate_bound_annotation_verifies_paragraph_label_membership() -> None:
    """2026-09-14 段落级监督：自选段标签复核改段落号归属（段号没有逐字复核的对象）"""
    annotation = _bound_annotation()
    paragraph_info = ChapterParagraphInfo(
        paragraph_ids=[0, 1],
        char_spans=[(0, 4), (4, 9)],
        texts=["顾霜“住手”", "回荡"],
    )
    annotation.paragraph_labels = [BoundParagraphLabel(paragraph_id=0, emotion=0)]
    validate_bound_annotation(
        annotation,
        chapter_id=1,
        chapter_text="顾霜“住手”回荡",
        paragraph_info=paragraph_info,
    )
    annotation.paragraph_labels = [BoundParagraphLabel(paragraph_id=9, emotion=0)]
    with pytest.raises(ValueError):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            chapter_text="顾霜“住手”回荡",
            paragraph_info=paragraph_info,
        )
