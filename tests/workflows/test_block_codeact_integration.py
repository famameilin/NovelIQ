"""2026-09-16 章内并行 CodeAct 端到端集成（只换模型，其余全真实）

与调度器测试互补：调度器测试 monkeypatch 了块/章运行器，这里让真实的块会话图、
真实写者会话图、真实账本与合并程序面全部跑起来，只把 LLM 换成脚本化伪模型。
断言端到端不变式：

- 两个块会话各自构造出块内对象，块代理**一行正式记录都没写**（审计表里只有
  execute_code 与它内部调用的构造器/检索）；
- 章会话经同一个账本把句柄编译成正式记录：实体、事件树、对话、指标与段标签；
- 块内候选编号（块内 1 基）经章级候选表映射后写成章级对话；
- 块代理的正文授权足迹经程序面工厂并入章账本（并入时机在章会话开始之前）；
- finish_chapter 的章会话收尾语义不变（账本 annotation 正常落地）。
"""

from __future__ import annotations

import itertools
import re
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.program import PROGRAM_TOOL_NAME
from src.agents.annotation.schema import ChunkParagraphInfo, SearchResult, TextSearchResult
from src.config import settings
from src.workflows.annotate_helpers.block_codeact import run_chapter_block_codeact

# 三段正文：块1 = 段1+段2（20 字），块2 = 段3（15 字）；两段各含一个对话候选
_PARAGRAPHS = ["顾霜喝道：“住手！”", "众人散去，夜色渐深。", "伯安拔剑相向，喝道：“退下！”"]
_CHAPTER_TEXT = "".join(_PARAGRAPHS)
_SPLIT_MAX_CHARS = 20
_BLOCK_TEXT_LENGTHS = (20, len(_PARAGRAPHS[2]))


class _QueryService:
    """用于提供无数据库依赖的查询桩（search_text 命中一个授权段落）"""

    current_chapter_order = None

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """用于返回一条正文命中（块账本据此登记真实授权段落）"""
        del query, range_name, limit
        return [
            TextSearchResult(
                chapter_id=1,
                paragraph_ids=[99],
                content="顾霜喝道：",
                keyword_score=0.5,
                semantic_score=0.1,
            )
        ]

    def search_event_history(self, query, *, limit=50):
        """用于返回空历史事件树"""
        del query, limit
        return []

    def fetch_active_case_details(self, case_id):
        """用于表示没有 active 案例"""
        del case_id
        return None


class _AuditSession:
    """用于在内存里模拟审计短事务会话（add 即分配主键，get 按类名+主键取回）"""

    def __init__(self, store: _AuditStore) -> None:
        """用于绑定共享的审计行仓库"""
        self._store = store

    def get_bind(self) -> None:
        """用于声明非 postgresql 绑定（跳过 SET TRANSACTION READ ONLY）"""
        return None

    def add(self, row: Any) -> None:
        """用于登记审计行并分配主键（生产记录器依赖 add 后 flush 能拿到 id）"""
        if getattr(row, "id", None) is None:
            row.id = next(self._store.ids)
        self._store.rows[(type(row).__name__, int(row.id))] = row
        if type(row).__name__ == "AgentInvocation":
            self._store.invocations.append(row)
        if type(row).__name__ == "AgentToolCall":
            self._store.tool_calls.append(row)

    def get(self, model: Any, identity: int) -> Any:
        """用于按主键取回已写入的审计行"""
        return self._store.rows.get((model.__name__, int(identity)))

    def flush(self) -> None:
        """用于满足 flush 协议"""

    def commit(self) -> None:
        """用于满足提交协议"""

    def rollback(self) -> None:
        """用于满足回滚协议"""

    def close(self) -> None:
        """用于满足关闭协议"""


class _AuditStore:
    """用于收集全部审计行（实验/测试不落库）"""

    def __init__(self) -> None:
        """用于初始化空仓库"""
        self.ids = itertools.count(1)
        self.rows: dict[tuple[str, int], Any] = {}
        self.invocations: list[Any] = []
        self.tool_calls: list[Any] = []

    def __call__(self) -> _AuditSession:
        """用于按会话工厂协议开一条新会话"""
        return _AuditSession(self)

    def session_factory(self) -> _AuditSession:
        """用于满足 session_factory 协议"""
        return _AuditSession(self)


_BLOCK_PROGRAMS: dict[int, list[str]] = {
    1: [
        'search_text(query="顾霜", range_name="previous")\n'
        'mention(key="m1", name="顾霜", entity_type="character", evidence=[{"paragraph_id": 1, "quote": "顾霜"}])\n'
        'local_event(key="e1", description="顾霜喝止众人", evidence=[{"paragraph_id": 1, "quote": "喝道"}])\n'
        "participant(event=\"e1\", entity=\"m1\", role=\"主体\", narrative_role=\"主体\", action=\"喝止\", "
        'emotion=-1, evidence=[{"paragraph_id": 1, "quote": "喝道"}])\n'
        'dialogue(key="d1", candidate_index=1, verdict="dialogue", speaker="m1", tone="愤怒", '
        'evidence=[{"paragraph_id": 1, "quote": "住手"}])\n'
        "label(paragraph_id=1, emotion=-1)\n"
    ],
    2: [
        'mention(key="m1", name="伯安", entity_type="character", evidence=[{"paragraph_id": 3, "quote": "伯安"}])\n'
        'local_event(key="e1", description="伯安拔剑相向", evidence=[{"paragraph_id": 3, "quote": "拔剑"}])\n'
        "participant(event=\"e1\", entity=\"m1\", role=\"主体\", narrative_role=\"主体\", action=\"拔剑\", "
        'emotion=1, evidence=[{"paragraph_id": 3, "quote": "拔剑"}])\n'
        'dialogue(key="d1", candidate_index=1, verdict="dialogue", speaker="m1", tone="愤怒", '
        'evidence=[{"paragraph_id": 3, "quote": "退下"}])\n'
        "label(paragraph_id=3, emotion=1)\n"
    ],
}

_CHAPTER_PROGRAMS = [
    'bind(mention="B1:m1", el="gs")\n'
    'bind(mention="B2:m1", el="ba")\n'
    "merge_dialogues()\n"
    'tree(key="t1", description="顾霜喝止众人", sources=["B1:e1"])\n'
    'event(tree="t1", key="e2", description="伯安拔剑相向", sources=["B2:e1"])\n'
    'metric(summary="顾霜喝止众人，伯安拔剑相向", emotional_valence=-1, narrative_function="冲突")\n'
    "finish_chapter()\n"
]


class _ScriptedLLM:
    """用于按会话（哪个块 / 章）返回脚本化 execute_code 程序"""

    def __init__(self) -> None:
        """用于初始化脚本游标与绑定面记录"""
        self.counts: dict[str, int] = {}
        self.bound_names: list[tuple[str, ...]] = []
        self.sessions: list[str] = []

    def bind_tools(self, tools: list[Any]) -> _ScriptedLLM:
        """用于记录每个图实际绑定给模型的工具名"""
        self.bound_names.append(tuple(str(tool.name) for tool in tools))
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        """用于返回该会话的下一段程序（脚本用尽即无工具回复=会话自然收束）"""
        content = "\n".join(str(getattr(message, "content", "")) for message in messages)
        key, script = self._session_of(content)
        index = self.counts.get(key, 0)
        self.counts[key] = index + 1
        if index >= len(script):
            return AIMessage(content="", tool_calls=[])
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": PROGRAM_TOOL_NAME,
                    "args": {"code": script[index]},
                    "id": f"{key}-{index}",
                    "type": "tool_call",
                }
            ],
        )

    def _session_of(self, content: str) -> tuple[str, list[str]]:
        """用于从句柄/索引进场方式辨认当前是哪个会话"""
        if "<BlockAnnotations>" in content:
            self.sessions.append("chapter")
            return "chapter", _CHAPTER_PROGRAMS
        match = re.search(r'<CurrentBlock block="(\d+)/\d+">', content)
        if match is not None:
            block = int(match.group(1))
            self.sessions.append(f"block{block}")
            return f"block{block}", _BLOCK_PROGRAMS[block]
        raise AssertionError("无法辨认会话来源（首条消息既不是块也不是章）")


def _paragraph_rows() -> list[Any]:
    """用于构造三段正文的段落事实源行"""
    from types import SimpleNamespace

    rows = []
    offset = 0
    for index, text in enumerate(_PARAGRAPHS, start=1):
        rows.append(
            SimpleNamespace(
                paragraph_id=index,
                chapter_id=1,
                local_start_char=offset,
                local_end_char=offset + len(text),
                text=text,
            )
        )
        offset += len(text)
    return rows


def _sub_chunks() -> list[tuple[int, str, int]]:
    """用于构造与段落边界对齐的两块切分"""
    from src.workflows.annotate import _split_chapter_sub_chunks

    return _split_chapter_sub_chunks(
        _CHAPTER_TEXT,
        _paragraph_rows(),
        chapter_chunk_id=1,
        max_chars=_SPLIT_MAX_CHARS,
        min_tail_chars=0,
    )


def _paragraph_info() -> ChunkParagraphInfo:
    """用于构造整章段落坐标（章会话账本按整章文本构造）"""
    spans: list[tuple[int, int]] = []
    offset = 0
    for text in _PARAGRAPHS:
        spans.append((offset, offset + len(text)))
        offset += len(text)
    return ChunkParagraphInfo(paragraph_ids=[1, 2, 3], char_spans=spans, texts=list(_PARAGRAPHS))


@pytest.fixture(autouse=True)
def _codeact_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """用于开启程序面（块面路径的前置）"""
    monkeypatch.setattr(settings.models.annotation, "codeact_enabled", True)


@pytest.mark.asyncio
async def test_block_agents_annotate_and_chapter_merge_writes_formal_records() -> None:
    """端到端：块代理产出局部标注 → 章代理绑定并编译成正式记录，块面一行未写"""
    llm = _ScriptedLLM()
    store = _AuditStore()
    sub_chunks = _sub_chunks()
    assert [len(text) for _id, text, _offset in sub_chunks] == list(_BLOCK_TEXT_LENGTHS)

    result = await run_chapter_block_codeact(
        run_id="run-1",
        chapter_id=1,
        chapter_chunk_id=1,
        chapter_text=_CHAPTER_TEXT,
        chapter_paragraph_rows=_paragraph_rows(),
        sub_chunks=sub_chunks,
        llm=llm,
        sql_session_factory=store.session_factory,
        query_service_factory=lambda session: _QueryService(),
        graph_state=FactGraph(),
        stream=None,
        novel_id="default",
        novel_title=None,
        chapter_label="第1章",
    )

    # 每个会话的绑定面都只有唯一 execute_code（三个会话；模型调用层可能重复绑定）
    assert set(llm.bound_names) == {(PROGRAM_TOOL_NAME,)}
    assert len(llm.bound_names) >= 3
    assert sorted(set(llm.sessions)) == ["block1", "block2", "chapter"]

    # 章会话产出的正式记录：两个实体、两个事件节点、两条对话、指标与段标签
    assert sorted(op["name"] for op in result.entity_ops) == ["伯安", "顾霜"]
    chunk = result.annotation.chunks[0]
    assert {event.description for event in chunk.events} == {"顾霜喝止众人", "伯安拔剑相向"}
    assert {dialogue.content for dialogue in chunk.dialogues} == {"住手！", "退下！"}
    # 块内候选 1 经章级候选表映射：块2 的候选 1 落成章候选 2
    assert {dialogue.candidate_index for dialogue in chunk.dialogues} == {1, 2}
    assert chunk.metrics.summary == "顾霜喝止众人，伯安拔剑相向"
    assert {label.paragraph_id for label in chunk.paragraph_labels} == {1, 3}

    # 块代理只写过块内对象与检索：审计里没有一条正式写入工具
    formal_writes = {
        "write_entity",
        "write_relation",
        "write_dialogue",
        "write_event",
        "write_metrics",
        "write_dialogues",
        "finish_chapter",
    }
    invocations = {row.id: row.task_type for row in store.invocations}
    assert sorted(invocations.values()) == ["annotation", "annotation_block", "annotation_block"]
    block_ids = {row.id for row in store.invocations if row.task_type == "annotation_block"}
    chapter_ids = {row.id for row in store.invocations if row.task_type == "annotation"}
    block_tools = {
        str(getattr(call, "tool_name", ""))
        for call in store.tool_calls
        if _invocation_of(store, call) in block_ids
    }
    assert block_tools.isdisjoint(formal_writes), block_tools
    chapter_tools = {
        str(getattr(call, "tool_name", ""))
        for call in store.tool_calls
        if _invocation_of(store, call) in chapter_ids
    }
    assert {"write_entity", "write_event", "write_dialogue", "write_metrics"} <= chapter_tools

    # 块代理的正文授权足迹并入章审计（并入发生在章会话开始之前）
    assert 99 in result.audit.authorized_text_paragraph_ids


def _invocation_of(store: _AuditStore, call: Any) -> int:
    """用于由工具调用行反查它属于哪次尝试（turn 行 → invocation）"""
    turn = store.rows.get(("AgentTurn", int(call.turn_id)))
    assert turn is not None
    return int(turn.invocation_id)
