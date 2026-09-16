"""章节级标注 Agent 逐 chunk LangGraph 与 Runner 测试（独立提交 + 上下文上界）"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.annotation.errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationInvariantError,
)
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.prompts import build_chunk_message
from src.agents.annotation.runner import (
    run_annotation_agent,
    validate_bound_annotation,
)
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundParagraphLabel,
    CaseSearchResult,
    ChunkMetricsInput,
    ChunkParagraphInfo,
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
        self.captured_tool_names: list[list[str]] = []

    def bind_tools(self, tools):
        """2026-08-30 用于记录每个模型回合实际绑定的工具合同"""
        self.captured_tool_names.append([tool.name for tool in tools])
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


# 2026-09-14 写入面重构：五个写入小调用（write_entity/write_metrics/write_event/
# write_relation/write_dialogue）+ 唯一 finish_chapter 收尾（工具面按此顺序装配）
_ALL_WRITE_TOOLS = (
    "write_entity",
    "write_metrics",
    "write_event",
    "write_relation",
    "write_dialogue",
)
_WRITE_TOOLS = frozenset(_ALL_WRITE_TOOLS)


def _finish_chapter_call(call_id: str = "call-finish-chapter") -> dict:
    """2026-09-14 用于构造唯一收尾声明（工具体只回 pending，收尾判定在本回合调用处理完后执行）"""
    return _write_call("finish_chapter", {}, call_id=call_id)


def _metrics_calls(call_id: str = "call-metrics", labels: list[dict] | None = None) -> list[dict]:
    """2026-09-14 用于构造 write_metrics 小调用（指标整域一次提交，段落标签随本域提交）"""
    args: dict = {"summary": "住手回荡", "emotional_valence": 0, "narrative_function": "铺垫"}
    if labels is not None:
        args["labels"] = labels
    return [_write_call("write_metrics", args, call_id=call_id)]


def _entity_calls(
    *,
    name: str = "顾霜",
    entity_type: str = "character",
    el: str | None = None,
    call_id: str = "call-entity",
) -> list[dict]:
    """2026-09-14 用于构造 write_entity 小调用（一次登记一个实体，el=章内引用键）"""
    return [
        _write_call(
            "write_entity",
            {"name": name, "entity_type": entity_type, "el": el if el is not None else name},
            call_id=call_id,
        )
    ]


def _relation_calls(
    *,
    from_entity: int = 1,
    to_entity: int = 2,
    relation_type: str = "敌对",
    call_id: str = "call-relation",
) -> list[dict]:
    """2026-09-13 用于构造 write_relation 小调用（两端用运行期编号，写入即入图）"""
    return [
        _write_call(
            "write_relation",
            {
                "from_entity": from_entity,
                "to_entity": to_entity,
                "relation_type": relation_type,
            },
            call_id=call_id,
        )
    ]


def _dialogue_calls(call_id: str = "call-dialogue") -> list[dict]:
    """2026-09-13 用于构造 write_dialogue 小调用（第一条候选判为真实对话）"""
    return [
        _write_call(
            "write_dialogue",
            {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": "平静"},
            call_id=call_id,
        )
    ]


def _event_calls(
    *,
    tree_key: str = "t1",
    description: str = "顾霜喝止众人",
    action: str = "喝止",
    child_key: str = "e1",
    child_description: str = "顾霜收势",
    child_action: str = "收势",
    call_id: str = "call-events",
) -> list[dict]:
    """2026-09-14 用于构造一棵事件树的小调用组（write_event 根 + 子事件，参与者内联 characters）

    根 el=树键、子 el=树键/节点键；树内先后=调用顺序（无序号参数）。
    同一 chunk 内 (人物, 动作) 不得重复（人物动态状态唯一），多棵树同轮提交时
    各处的 action 必须互不相同。
    """
    return [
        _write_call(
            "write_event",
            {
                "el": tree_key,
                "isroot": True,
                "description": description,
                "characters": [
                    {
                        "entityid": 1,
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": action,
                        "emotion": -1,
                    }
                ],
            },
            call_id=f"{call_id}-root",
        ),
        _write_call(
            "write_event",
            {
                "el": f"{tree_key}/{child_key}",
                "isroot": False,
                "type": "main",
                "description": child_description,
                "characters": [
                    {
                        "entityid": 1,
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": child_action,
                        "emotion": 0,
                    }
                ],
            },
            call_id=f"{call_id}-child",
        ),
    ]


def _serial_write_messages(*, dialogues: list[dict] | None = None) -> list[AIMessage]:
    """2026-09-14 用于构造三轮正式写入回复（写者面全放开，分轮只是测试编排）

    一轮=多个小调用（整轮计一个模型回合）：第一轮登记实体并提交指标（段落标签随
    write_metrics 一起交），第二轮用 write_event 按序写完事件树，第三轮写入对话并
    以唯一 finish_chapter 收尾（收尾判定在本回合全部调用处理完后执行）。工具面每轮
    都是全集，分轮不再对应任何解锁边界。
    """
    resolved_dialogues = dialogues if dialogues is not None else _dialogue_calls()
    return [
        _tool_message([*_entity_calls(), *_metrics_calls(labels=[{"paragraph_id": 0, "emotion": -2}])]),
        _tool_message([*_event_calls()]),
        _tool_message([*resolved_dialogues, _finish_chapter_call()]),
    ]


async def _invoke_graph(
    llm: _SequenceLLM,
    *,
    allow_future_context: bool,
    chunk: tuple[int, str] | None = None,
    max_iterations: int = 30,
) -> dict:
    """2026-08-10 用于执行最小单 chunk 章节 LangGraph（消息链累积合同）"""
    resolved_chunk = chunk or (1, "“住手”回荡")
    chunk_id, chunk_text = resolved_chunk
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=chunk_id,
        current_chunk_text=chunk_text,
        allow_future_context=allow_future_context,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chunk_text))],
            texts=[chunk_text],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=max_iterations,
    )
    return await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chunk_message(
                        chunk_index=1,
                        chunk_total=1,
                        chunk_text=chunk_text,
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )


def _bound_annotation(*, summary: str = "顾霜进入山门") -> BoundChapterAnnotation:
    """2026-08-07 用于构造 Runner 重试测试的最小章节标注"""
    return BoundChapterAnnotation(
        chapter_summary=summary,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=1,
                metrics=ChunkMetricsInput(
                    summary="顾霜进入山门",
                    emotional_valence=0,
                    narrative_function="铺垫",
                ),
                character_observations=[],
                dialogues=[],
                events=[],
            )
        ],
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


def _progress(messages: list) -> str:
    """2026-09-14 用于取某轮模型请求中注入的【进度账本】块文本"""
    blocks = [m for m in messages if isinstance(m, HumanMessage) and "进度账本" in str(m.content)]
    assert len(blocks) == 1, "每次请求应恰好携带一条【进度账本】注入"
    return str(blocks[0].content)


@pytest.mark.asyncio
async def test_second_write_entities_appends_to_catalog_not_replaces() -> None:
    """2026-08-26 回归（2026-09-04 单一写面改契约为 op log）：实体登记追加语义必须落进 FactGraph

    2026-09-13 小调用改造后一次登记一个实体（write_entity），op log 仍按提交顺序
    累积；同名重交按更新语义覆盖（tags/description 增量）。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
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
        current_chunk_id=1,
        current_chunk_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
    )
    tools = {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}
    first = await tools["write_entity"].ainvoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    replay = await tools["write_entity"].ainvoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    assert json.loads(first) == json.loads(replay)
    assert len(ledger.graph.entity_ops) == 1


@pytest.mark.asyncio
async def test_single_chunk_chapter_completes_via_write_and_auto_finalize() -> None:
    """2026-08-07 用于验证单 chunk 章节经小调用写入 + finish_chapter 收尾后由系统自动冻结完成

    2026-09-13 变化点：写入即生效、没有逐域结束声明，唯一收尾是 finish_chapter
    （工具体只回 pending，真正判定在批次末尾执行）。
    """
    llm = _SequenceLLM(_serial_write_messages())
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3


def test_case_pool_notice_in_first_message_and_no_case_table_injected() -> None:
    """2026-09-11 案例改检索制：首条消息声明检索通道，且不注入任何案例编号表

    旧合同（09-04 起）把初始活动案例全量渲染为 <ActiveCases> 编号表随正文注入
    （第7章死锁的产物）；新合同案例只经 search_pool 展示，注入块退化为通道说明，
    正文中不再出现任何 case_number。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, 4)],
            texts=["住手回荡"],
        ),
    )
    message = build_chunk_message(
        chunk_index=1,
        chunk_total=1,
        chunk_text="住手回荡",
        candidates=ledger.dialogue_candidates,
    )
    assert "<ActiveCases>" in message
    assert "search_pool" in message
    assert "case_number" in message
    assert '"case_number"' not in message


def test_dialogue_candidate_view_field_aligned_with_write_param() -> None:
    """2026-09-10 候选渲染字段名与 write_dialogue 参数名对齐

    旧字段名 index 与 ActiveCases 的 case_number 同为小整数，模型每章重新
    推理两套编号关系（run a83fae3d 思考实测映射推理 1725 次）；改名后
    candidate_index 与 write_dialogue 参数字面一致，映射自明
    （2026-09-13 小调用改造后按候选逐个提交判定）。
    """
    chunk_text = "“住手”回荡"
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=chunk_text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chunk_text))],
            texts=[chunk_text],
        ),
    )
    message = build_chunk_message(
        chunk_index=1,
        chunk_total=1,
        chunk_text=chunk_text,
        candidates=ledger.dialogue_candidates,
    )
    assert '"candidate_index": 1' in message
    assert '"index":' not in message


@pytest.mark.asyncio
async def test_turn_budget_reminder_injected_near_iteration_cap() -> None:
    """2026-09-05 第3章死锁回归：临近内部循环上限的请求必须携带收尾提醒

    ch3 空转 15 轮 40 次检索 0 写入后撞硬顶，模型全程看不到轮次预算。
    提醒只进本次请求、不写入状态消息链（否则历史中逐轮堆积）。
    """
    search_call = _write_call("search_pool", {"query": "伯安"}, call_id="call-search")
    llm = _SequenceLLM([_tool_message([search_call])] * 4)
    result = await _invoke_graph(llm, allow_future_context=True, max_iterations=4)

    assert result.get("error") == "annotation LangGraph 内部循环达到上限 4"
    assert len(llm.captured_messages) == 4
    for index, messages in enumerate(llm.captured_messages):
        reminders = [
            message
            for message in messages
            if isinstance(message, HumanMessage) and "轮次预算" in str(message.content)
        ]
        remaining = 4 - index
        if remaining <= 3:
            assert len(reminders) == 1, f"第 {index + 1} 次请求应恰好携带一条提醒"
            assert messages[-1] is reminders[0]
        else:
            assert reminders == [], "远离上限的请求不得携带提醒"
    assert "剩余 3 轮" in str(llm.captured_messages[1][-1].content)
    assert "最后一轮" in str(llm.captured_messages[3][-1].content)
    # 2026-09-13：两个分支都点名唯一收尾动作 finish_chapter（run c80105cc 第 4 章死因：
    # 末轮文案只说"提交已确认内容"，模型把收尾留到"下一轮"，该轮结束即整章作废）
    for messages in (llm.captured_messages[1], llm.captured_messages[3]):
        reminder = str(messages[-1].content)
        assert "finish_chapter" in reminder


@pytest.mark.asyncio
async def test_every_write_tool_is_on_the_surface_from_the_first_turn() -> None:
    """2026-09-14 写入面重构：五个写入小调用从首轮起全部在工具面上，三轮写入 + 唯一收尾完成章节

    09-13 全放开：此前按"实体已写入"渐进解锁事件/关系/对话工具，模型把
    "不在工具面上"读成"工具不存在"，run c80105cc 实测 67% 的思考量落在锁定轮
    （ch3 第 5 轮单轮 40,287 字符只为 5 个 write_entity）。解锁判据删除后每轮
    工具面都是全集；未登记的实体编号在写入点按既有授权校验结构化拒绝。
    """
    llm = _SequenceLLM(_serial_write_messages())
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 3
    assert [
        [name for name in tool_names if name in _WRITE_TOOLS]
        for tool_names in llm.captured_tool_names
    ] == [list(_ALL_WRITE_TOOLS), list(_ALL_WRITE_TOOLS), list(_ALL_WRITE_TOOLS)]
    # 收尾工具是非正式工具：第一轮起就恒定开放（收尾判定由账本兜底）
    assert "finish_chapter" in llm.captured_tool_names[0]
    # 2026-09-14 写者面每次请求尾部注入【进度账本】（跨回合失忆修复，仅本次请求生效）：
    # 每请求比状态消息链多 1 条注入块
    assert [len(messages) for messages in llm.captured_messages] == [3, 6, 9]

    # 第 1 次请求：什么都还没写，五个域全部空白态
    first = _progress(llm.captured_messages[0])
    assert "实体：未写入" in first and "事件树：未写入" in first
    assert "指标：未写入" in first
    # 2026-09-14 三迭：注入块携带回合预算动态行
    assert "剩余回合" in first
    # 第 2 次请求：上一轮写入的实体与指标已进账本（局部键面：el、n、域现值）
    second = _progress(llm.captured_messages[1])
    assert "实体(1)：顾霜=顾霜(n=1)" in second
    assert "指标：已写入" in second
    # 第 3 次请求：第 2 轮写完的事件树结构进账本（根描述/子键类型/主链尾），
    # 对话判定发生在第 3 轮调用里，注入仍显示未判定
    third = _progress(llm.captured_messages[2])
    assert 't1="顾霜喝止众人"' in third and "children: e1 main" in third and "主链尾 e1" in third
    assert "对话：已判定 0/" in third


@pytest.mark.asyncio
async def test_cross_domain_write_calls_in_one_round_all_take_effect() -> None:
    """2026-09-13 写者面全放开：同一回复里的跨领域小调用全部生效，不再整批打回

    旧行为（09-13 前）：实体/指标/对话分属不同解锁窗口，同轮跨窗口调用按
    "本轮未开放工具"整批拒绝。解锁窗口删除后，同一批里的实体、指标与对话按
    调用顺序各自落账（每条写入即生效，失败也只回滚该条）。
    """
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    _write_call(
                        "write_entity",
                        {"name": "顾霜", "entity_type": "character", "el": "顾霜", "tags": ["少年"]},
                        call_id="call-entity",
                    ),
                    *_dialogue_calls(),
                    *_metrics_calls(),
                ]
            ),
            _tool_message([*_event_calls()]),
            _tool_message([_finish_chapter_call()]),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 3
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 3
    assert all('"status": "written"' in receipt for receipt in receipts)
    # 2026-09-14 注入账本带判定值与标签列：已判条目必须能直接读回"谁/什么语气/误判"，
    # 模型不再需要为核对已判内容回文重推（run b7477080 ch1 整册 6 遍的根因）
    progress = _progress(llm.captured_messages[1])
    assert "顾霜=顾霜(n=1；标签:少年)" in progress
    assert "对话：已判定 1/" in progress and "已判定值：1=null/平静" in progress


@pytest.mark.asyncio
async def test_failed_write_rolls_back_only_that_calls_revision() -> None:
    """2026-08-30 用于验证单条小调用失败只回滚该调用并允许下一轮修正"""
    invalid_entities = _write_call(
        "write_entity",
        {"name": " ", "entity_type": "character", "el": " "},
        call_id="call-entities-bad",
    )
    llm = _SequenceLLM(
        [
            _tool_message([invalid_entities]),
            *_serial_write_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    assert len(receipts) == 1
    assert '"status": "rejected"' in receipts[0]
    assert "write_entity" in llm.captured_tool_names[0]
    assert "write_entity" in llm.captured_tool_names[1]


@pytest.mark.asyncio
async def test_failed_entity_write_rolls_back_only_itself() -> None:
    """2026-09-13 同轮实体失败只回滚该调用：同轮指标照常落账，后续轮工具面不变

    旧行为（09-13 前）：实体失败会推迟依赖工具解锁，下一轮实体被接受后工具面
    才从三个小调用扩到九个且有"只追加不回收"的语义。解锁窗口删除后，失败的唯一
    后果是该条记录不落账——同批指标仍写入，四轮工具面都是全集。
    """
    invalid_entities = _write_call(
        "write_entity",
        {"name": " ", "entity_type": "character", "el": " "},
        call_id="call-entities-invalid",
    )
    llm = _SequenceLLM(
        [
            _tool_message([invalid_entities, *_metrics_calls()]),
            _tool_message([*_entity_calls(call_id="call-entity-fixed")]),
            _tool_message([*_event_calls()]),
            _tool_message([*_dialogue_calls(), _finish_chapter_call()]),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    assert [
        [name for name in tool_names if name in _WRITE_TOOLS]
        for tool_names in llm.captured_tool_names
    ] == [
        list(_ALL_WRITE_TOOLS),
        list(_ALL_WRITE_TOOLS),
        list(_ALL_WRITE_TOOLS),
        list(_ALL_WRITE_TOOLS),
    ]
    first_round_receipts = _tool_receipts(llm.captured_messages[1])
    assert len(first_round_receipts) == 2
    assert '"status": "rejected"' in first_round_receipts[0]
    assert '"record": "metrics"' in first_round_receipts[1]
    assert '"status": "written"' in first_round_receipts[1]


@pytest.mark.asyncio
async def test_partial_writes_do_not_auto_finalize() -> None:
    """2026-09-14 未发 finish_chapter 时写入保持开放：下一轮可继续追加，收尾轮一次性冻结

    旧合同（2026-09-13 前）以"事件域暂存 + finish_domain('events')"表达分轮追加；
    取消暂存与逐域结束后，写入即时生效但 chunk 只在唯一 finish_chapter 收尾后冻结，
    本轮未收尾时下一轮的树按调用顺序继续追加，两棵树都进最终收尾回执。
    """
    llm = _SequenceLLM(
        [
            _tool_message([*_entity_calls(), *_metrics_calls()]),
            _tool_message([*_event_calls(tree_key="t1")]),
            _tool_message(
                [
                    *_event_calls(
                        tree_key="t2",
                        description="顾霜追击众人",
                        action="追击",
                        child_key="e1",
                        child_description="众人退去",
                        child_action="退去",
                        call_id="call-events-second",
                    ),
                    *_dialogue_calls(),
                    _finish_chapter_call(),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    finals = [
        receipt
        for receipt in _tool_receipts(result["messages"])
        if '"status": "completed"' in receipt
    ]
    assert len(finals) == 1
    # 两棵树各 2 个节点（根 + 子事件）都进了同一次收尾
    assert '"events": 4' in finals[0]


@pytest.mark.asyncio
async def test_three_write_event_calls_and_relation_write_succeed_in_one_round() -> None:
    """2026-09-14 同轮写入三棵事件树与一条关系：每个小调用独立生效并即时返回 written

    旧合同（2026-09-13 前）以"暂存 + finish_domain"表达同轮多树并断言 12 条 staged
    回执；取消暂存后同轮 7 条写入调用（3 棵树 × 根+子 + 1 关系）各自返回 written 回执，
    事件与关系即时落账，收尾回执按域汇总条数（事件 6 节点、关系 1 条）。
    """
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    *_entity_calls(),
                    *_entity_calls(name="褚大山", call_id="call-entity-second"),
                    *_metrics_calls(),
                ]
            ),
            _tool_message(
                [
                    *_event_calls(tree_key="t1"),
                    *_event_calls(
                        tree_key="t2",
                        description="顾霜追击",
                        action="追击",
                        child_action="拦截",
                        call_id="call-events-second",
                    ),
                    *_event_calls(
                        tree_key="t3",
                        description="顾霜抱拳离场",
                        action="抱拳",
                        child_action="散去",
                        call_id="call-events-final",
                    ),
                    *_relation_calls(),
                ]
            ),
            _tool_message([*_dialogue_calls(), _finish_chapter_call()]),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    event_round_receipts = _tool_receipts(llm.captured_messages[2])[-7:]
    written = [receipt for receipt in event_round_receipts if '"status": "written"' in receipt]
    assert len(written) == 7
    assert '"record": "relation/顾霜-褚大山/敌对"' in event_round_receipts[-1]
    finals = [
        receipt
        for receipt in _tool_receipts(result["messages"])
        if '"status": "completed"' in receipt
    ]
    assert len(finals) == 1
    assert '"events": 6' in finals[0]
    assert '"relations": 1' in finals[0]


@pytest.mark.asyncio
async def test_failed_event_write_does_not_block_relation_write_in_same_round() -> None:
    """2026-09-14 事件记录失败时同轮关系写入照常生效，下一轮修正后收尾

    旧合同断言同轮关系域 finish 独立执行并保留成功回执；取消暂存后关系小调用即时
    入图并返回 written 回执，失败调用只回滚自己（同回合收尾不受影响，见
    test_failed_call_in_same_round_does_not_block_finish）。
    """
    invalid_participation = _write_call(
        "write_event",
        {
            "el": "t1/e2",
            "isroot": False,
            "type": "main",
            "description": "顾霜拦截去路",
            "characters": [
                {
                    "entityid": 1,
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "拦截",
                    "emotion": 9,
                }
            ],
        },
        call_id="call-events-invalid",
    )
    llm = _SequenceLLM(
        [
            _tool_message(
                [
                    *_entity_calls(),
                    *_entity_calls(name="褚大山", call_id="call-entity-second"),
                    *_metrics_calls(),
                ]
            ),
            _tool_message([*_event_calls(tree_key="t1"), invalid_participation, *_relation_calls()]),
            _tool_message(
                [
                    _write_call(
                        "write_event",
                        {
                            "el": "t1/e2",
                            "isroot": False,
                            "type": "main",
                            "description": "顾霜拦截去路",
                            "characters": [
                                {
                                    "entityid": 1,
                                    "role": "主体",
                                    "narrative_role": "主体",
                                    "action": "拦截",
                                    "emotion": -1,
                                }
                            ],
                        },
                        call_id="call-events-fixed",
                    ),
                    *_dialogue_calls(),
                    _finish_chapter_call(),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 3
    event_round_receipts = _tool_receipts(llm.captured_messages[2])
    rejected = [receipt for receipt in event_round_receipts if '"status": "rejected"' in receipt]
    assert len(rejected) == 1
    assert '"field": "emotion"' in rejected[0]
    assert any('"record": "relation/顾霜-褚大山/敌对"' in receipt for receipt in event_round_receipts)


@pytest.mark.asyncio
async def test_failed_call_in_same_round_does_not_block_finish() -> None:
    """2026-09-13 同回合的失败调用不阻塞收尾：失败只回滚自己，收尾按已写入内容完成

    旧合同此处是 round_failed 拒绝（要求先修正再重交），那条规则把收尾绑到无关记录的
    成功上：末轮出现一次失败就足以让整章作废（run 1b388eb3 第 2 章实锤）。逐条失败
    本来就在调用点单独回执，不需要收尾再报一次。
    """
    invalid_participation = _write_call(
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": 1,
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "怒斥",
                    "emotion": 9,
                }
            ],
        },
        call_id="call-events-invalid",
    )
    llm = _SequenceLLM(
        [
            _tool_message([*_entity_calls(), *_metrics_calls()]),
            _tool_message(
                [
                    *_event_calls(tree_key="t1"),
                    invalid_participation,
                    _finish_chapter_call("call-finish-ok"),
                ]
            ),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    # 末轮回执只在最终 state（captured_messages 是各次请求的历史，不含该轮自己的 ToolMessage）
    receipts = _tool_receipts(result["messages"])
    rejected = [receipt for receipt in receipts if '"code": "out_of_range"' in receipt]
    assert len(rejected) == 1, "越界 emotion 的那一条必须被单独拒绝并回执"
    assert '"record": "t1/root"' in rejected[0]
    # 失败不阻塞收尾：同回合的 finish_chapter 正常完成，坏记录本来就没进载荷
    assert result["phase"] == "completed"
    assert llm.calls == 2
    assert '"status": "completed"' in receipts[-1]


@pytest.mark.asyncio
async def test_truncated_tool_call_skips_business_tool_and_feeds_error_receipt() -> None:
    """
    2026-08-11 用于验证带截断标记的工具调用不执行业务写入，
    只回喂"参数不完整"错误回执，模型补全后章节仍能完成。
    """
    truncated_entities = {
        "name": "write_entity",
        "args": {},
        "id": "call-entities-truncated",
        "type": "tool_call",
        "truncated": True,
        "truncated_args": '{"name": "顾霜"',
    }
    # 聚合器在运行时以属性赋值挂载截断标记（绕过 create_tool_call 重建），测试同样模拟
    first_message = AIMessage(content="")
    first_message.tool_calls = [truncated_entities]
    llm = _SequenceLLM(
        [
            first_message,
            *_serial_write_messages(),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=False)

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    rejected = [receipt for receipt in receipts if '"accepted": false' in receipt]
    accepted = [receipt for receipt in receipts if '"status": "written"' in receipt]
    assert len(rejected) == 1
    assert len(accepted) == 0
    assert '"tool": "write_entity"' in rejected[0]
    assert "截断" in rejected[0]


@pytest.mark.asyncio
async def test_auto_finalize_invariant_error_terminates_chapter() -> None:
    """2026-08-10 用于验证收尾后 ready_chunk 缺失时按不变量错误终止而非回环修正

    2026-09-13 变化点：不再有六域回执齐备这一判据，auto_finalize 只看
    ledger.chapter_finished；此处模拟 finish_chapter 通过但 ready_chunk 被破坏。
    """
    llm = _SequenceLLM(_serial_write_messages())

    class _BrokenLedger(AnnotationToolLedger):
        """2026-09-13 用于模拟已收尾但 ready_chunk 被破坏的账本"""

        def finish_chapter(self) -> dict:
            """2026-09-13 用于正常收尾后清掉 ready_chunk"""
            receipt = super().finish_chapter()
            self.ready_chunk = None
            return receipt

    chunk_id, chunk_text = 1, "\u201c住手\u201d回荡"
    ledger = _BrokenLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=chunk_id,
        current_chunk_text=chunk_text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len(chunk_text))],
            texts=[chunk_text],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=30,
    )
    with pytest.raises(AnnotationInvariantError, match="ready_chunk 缺失"):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(
                        content=build_chunk_message(
                            chunk_index=1,
                            chunk_total=1,
                            chunk_text=chunk_text,
                            candidates=ledger.dialogue_candidates,
                        )
                    ),
                ],
                "phase": "chunk_open",
                "iterations": 0,
                "error": None,
            }
        )
    assert llm.calls == 3
    assert ledger.annotation is None
    assert ledger.completed_chunks == []


def test_validate_bound_annotation_requires_exact_chunk_order() -> None:
    """2026-08-07 用于验证系统绑定 chunks 必须精确覆盖 current"""
    annotation = _bound_annotation()
    with pytest.raises(ValueError, match="必须按原文顺序精确覆盖"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(2, "另一个原文")],
        )


def test_validate_bound_annotation_verifies_dialogue_original_text() -> None:
    """2026-08-07 用于验证对话原文位置与内容由系统绑定且可回查"""
    annotation = _bound_annotation()
    chunk = annotation.chunks[0]
    chunk.dialogues = [
        BoundDialogue(
            candidate_index=1,
            candidate_key="dlg_1",
            content="住手",
            start=0,
            end=2,
        )
    ]
    with pytest.raises(ValueError, match="系统对话原文绑定不一致"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(1, "顾霜进入山门")],
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
                current_chunks=[(1, "顾霜进入山门")],
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
                current_chunks=[(1, "顾霜进入山门")],
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
                current_chunks=[(1, "顾霜进入山门")],
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
            current_chunks=[(1, "顾霜进入山门")],
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=recorder,
        )
    assert actual == result
    assert run_attempt.await_count == 1
    assert recorder.finish_invocation.call_args.kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_runner_accepts_multiple_sub_chunk_entries_and_negative_ids() -> None:
    """2026-08-14 M7（§20）用于验证多 chunk 输入与负子块 ID 通过章节身份校验"""
    session = MagicMock()
    result = _agent_result()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=result),
    ) as run_attempt:
        actual = await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(-1, "第一个子块"), (-2, "第二个子块")],
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=MagicMock(),
        )
    assert actual == result
    assert run_attempt.await_count == 1


@pytest.mark.asyncio
async def test_runner_rejects_empty_chunk_text_entry() -> None:
    """2026-08-14 M7 用于验证逐条校验子块原文非空"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=_agent_result()),
    ) as run_attempt:
        with pytest.raises(AnnotationInputError, match="原文不能为空"):
            await run_annotation_agent(
                run_id="run-1",
                chapter_id=1,
                current_chunks=[(-1, "   ")],
                query_service_factory=lambda session: _QueryService(),
                session_factory=lambda: session,
                llm=MagicMock(),
                audit_recorder=MagicMock(),
            )
    assert run_attempt.await_count == 0


@pytest.mark.asyncio
async def test_runner_forwards_sub_chunk_index_to_attempt() -> None:
    """2026-08-14 M7（§20）用于验证 sub_chunk_index 透传到底层尝试"""
    session = MagicMock()
    with patch(
        "src.agents.annotation.runner._run_single_attempt",
        new=AsyncMock(return_value=_agent_result()),
    ) as run_attempt:
        await run_annotation_agent(
            run_id="run-1",
            chapter_id=1,
            current_chunks=[(-2, "第二个子块")],
            sub_chunk_index=1,
            query_service_factory=lambda session: _QueryService(),
            session_factory=lambda: session,
            llm=MagicMock(),
            audit_recorder=MagicMock(),
        )
    assert run_attempt.call_args.kwargs["sub_chunk_index"] == 1


def test_validate_bound_annotation_covers_multiple_sub_chunks() -> None:
    """2026-08-14 M7 用于验证多条目 current 按子块 ID 精确覆盖且对话按各自原文绑定"""
    first = BoundChunkAnnotation(
        chunk_id=-1,
        metrics=ChunkMetricsInput(
            summary="第一子块",
            emotional_valence=0,
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=[
            BoundDialogue(
                candidate_index=1,
                candidate_key="dlg_1",
                content="住手",
                start=0,
                end=2,
            )
        ],
        events=[],
    )
    second = BoundChunkAnnotation(
        chunk_id=-2,
        metrics=ChunkMetricsInput(
            summary="第二子块",
            emotional_valence=0,
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=[
            BoundDialogue(
                candidate_index=1,
                candidate_key="dlg_2",
                content="退下",
                start=0,
                end=2,
            )
        ],
        events=[],
    )
    annotation = BoundChapterAnnotation(
        chapter_summary="子块合并摘要",
        chunks=[first, second],
    )
    validate_bound_annotation(
        annotation,
        chapter_id=1,
        current_chunks=[(-1, "住手喝止"), (-2, "退下众人")],
    )
    # 顺序错位仍被拒绝
    with pytest.raises(ValueError, match="必须按原文顺序精确覆盖"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(-2, "退下众人"), (-1, "住手喝止")],
        )


class _AliasCaseQueryService(_QueryService):
    """2026-08-12 用于提供 entity_alias 活动案例的图级测试查询桩"""

    def _alias_case(self) -> CaseSearchResult:
        return CaseSearchResult(
            id="alias-1",
            type="entity_alias",
            chunk_id=1,
            keys=["同一人物", "顾霜", "顾老"],
            description="疑似同一人物：顾霜 与 顾老",
        )

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-11 案例改检索制：alias 案例经 search_pool 展示取得编号（旧合同为注入候选）"""
        del query, hidden_case_ids, case_type, limit
        return SearchResult(results=[self._alias_case()])

    def fetch_active_case_details(self, case_id):
        del case_id
        return ActiveCaseDetails(
            **self._alias_case().model_dump(mode="python"),
            target_key="target-alias-1",
            target_ref={"kind": "alias", "name_a": "顾霜", "name_b": "顾老", "chunk_id": 1},
        )


def _resolve_fact_case_call(call_id: str = "call-fact") -> dict:
    """2026-08-12 用于构造带非法 change_kind 的 resolve_fact_case 调用"""
    return _write_call(
        "resolve_fact_case",
        {
            "case_number": 1,
            "from_entity": 1,
            "to_entity": 2,
            "relation_type": "同一人物",
            "change_kind": "强化关系",
            "reason": "指向同一人",
        },
        call_id=call_id,
    )


@pytest.mark.asyncio
async def test_resolve_fact_case_invalid_change_kind_returns_failed_receipt() -> None:
    """
    2026-08-12 用于验证非法 change_kind 以失败回执回到模型继续对话，
    而不是抛出让整章失败（下游持久化只认闭合枚举）。

    2026-09-14 解决类工具并入 schema 层失败翻译：回执从 tool/error 通用形态
    收窄为 record/field/code/expected 结构化拒绝（field=change_kind、可自纠）。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text="\u201c住手\u201d回荡",
        allow_future_context=False,
        graph=FactGraph(
            history_entity_types={"顾霜": "character", "顾老": "character"},
            history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        ),
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, len("\u201c住手\u201d回荡"))],
            texts=["\u201c住手\u201d回荡"],
        ),
    )
    service = _AliasCaseQueryService()
    tools = build_annotation_tools(service, ledger)
    # 2026-09-11 案例改检索制：先经 search_pool 展示取得编号 1（展示即授权）
    next(candidate for candidate in tools if candidate.name == "search_pool").invoke({"query": "顾霜"})
    llm = _SequenceLLM(
        [
            _tool_message([_resolve_fact_case_call()]),
            *_serial_write_messages(),
        ]
    )
    graph = build_annotation_graph(
        llm,
        tools,
        ledger=ledger,
        max_iterations=30,
    )
    result = await graph.ainvoke(
        {
            "messages": [
                SystemMessage(content="test"),
                HumanMessage(
                    content=build_chunk_message(
                        chunk_index=1,
                        chunk_total=1,
                        chunk_text="“住手”回荡",
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ],
            "phase": "chunk_open",
            "iterations": 0,
            "error": None,
        }
    )

    assert result["phase"] == "completed"
    assert result.get("error") is None
    assert llm.calls == 4
    receipts = _tool_receipts(llm.captured_messages[1])
    rejected = [receipt for receipt in receipts if '"status": "rejected"' in receipt]
    assert len(rejected) == 1
    assert '"field": "change_kind"' in rejected[0]
    assert '"code": "invalid_value"' in rejected[0]
    assert "change_kind" in rejected[0]
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
                current_chunks=[(1, "顾霜进入山门")],
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
    chunk = annotation.chunks[0]
    paragraph_info = ChunkParagraphInfo(
        paragraph_ids=[0, 1],
        char_spans=[(0, 4), (4, 9)],
        texts=["顾霜“住手”", "回荡"],
    )
    chunk.paragraph_labels = [BoundParagraphLabel(paragraph_id=0, emotion=0)]
    validate_bound_annotation(
        annotation,
        chapter_id=1,
        current_chunks=[(1, "顾霜“住手”回荡")],
        paragraph_info=paragraph_info,
    )
    chunk.paragraph_labels = [BoundParagraphLabel(paragraph_id=9, emotion=0)]
    with pytest.raises(ValueError, match="系统自选段标签超出本 chunk 段落范围"):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            current_chunks=[(1, "顾霜“住手”回荡")],
            paragraph_info=paragraph_info,
        )


@pytest.mark.asyncio
async def test_graph_reinjects_finish_chapter_hint_after_plain_text_reply(monkeypatch) -> None:
    """2026-09-08 用于验证模型纯文本汇报后被重发请求带上收尾提醒并补齐写入

    第13章死锁回归：模型写完实体与指标后改用纯文本汇报，调用层重发时注入缺内容
    清单与收尾方式（2026-09-13 取消逐域结束后文案改为"还没收尾"并指向
    finish_chapter），模型据此补齐剩余领域，章节正常完成。
    """
    async def _skip_sleep(_seconds: float) -> None:
        """2026-09-08 用于跳过重试退避等待"""

    monkeypatch.setattr("src.agents.stream.asyncio.sleep", _skip_sleep)
    llm = _SequenceLLM(
        [
            _tool_message([*_entity_calls(), *_metrics_calls()]),
            AIMessage(content="本章语义标注已完成，汇总如下……"),
            _tool_message([*_event_calls()]),
            _tool_message([*_dialogue_calls(), _finish_chapter_call()]),
        ]
    )
    result = await _invoke_graph(llm, allow_future_context=True)

    assert result["error"] is None
    assert llm.calls == 4
    # 重发请求（第 3 次调用）末尾是收尾提醒，指出剩余领域与收尾方式
    resent = llm.captured_messages[2]
    last = resent[-1]
    assert isinstance(last, HumanMessage)
    assert "收尾提醒" in str(last.content)
    assert "finish_chapter" in str(last.content)
    assert "relations" in str(last.content) and "dialogues" in str(last.content)
    # 首次请求与状态消息链都不含提醒：注入只对重发请求生效
    assert all("收尾提醒" not in str(m.content) for m in llm.captured_messages[1])
    assert all("收尾提醒" not in str(m.content) for m in result["messages"])
