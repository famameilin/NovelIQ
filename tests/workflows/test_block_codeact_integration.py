"""2026-09-17 章内三代理并发端到端集成（只换模型，其余全真实）

与 subagent 单元测试互补：`tests/agents/test_annotation_subagent_program.py` 只测单个 subagent 的
构造器与程序面合同；这里让**真实的 subagent 会话图、真实的章级账本、真实的接续层与生产
写入工具**全部跑起来，只把 LLM 换成脚本化伪模型，断言端到端不变式：

1. 三个 subagent 的会话各跑一轮 `execute_code`：构造器即时经生产边界落库（写入生效），
   但审计里 subagent invocation 的内层调用只有构造器与检索工具名，`write_*` 一个不出现；
2. 三条齐之后章收尾链把产出组装成正式章级结果：实体/关系/事件/对话/段标签/指标齐全
   （条数与名字逐条断言）；
3. **名字即连接**：事件参与者与对话说话人的人名只要与结构 subagent 登记的写法一致，就落到
   同一个实体上，且不因此多出实体；
4. **写法分歧的可见降级**：引用处出现结构 subagent 未登记的人名时，写入口按引用处自报大类
   照常登记新实体，接续层再挂一条 `type=entity_alias` 的案例（实体数 +1，两条实体都如实保留）；
5. 对话候选缺判定时按 `not_dialogue` 默认（`finish` 回执的 `dialogue_defaulted`
   含缺的编号），整章照常完成；
6. 任一 subagent 失败 → 整章失败，且 `FactGraph` 未被写入脏数据。

章收尾相位（`_finish_chapter`）在 subagent 相位之后补齐接续层、指标/标签落库与
`complete_active_chunk()` / `ledger.finish()`，因此不变式 2-5 都能在真实产出上断言；
`run_chapter_subagents` 在 subagent 相位与收尾相位失败时都回滚 `FactGraph`
（收尾失败另见编排层合同测试），这里断言的是失败路径不留脏数据。

只换模型：`_QueryService` 是无数据库查询桩，`_AuditStore` 是内存审计会话，其余（subagent 图、
账本、程序面、接续层、生产写入工具、FactGraph）全真实，不连数据库、不真调模型。
"""

from __future__ import annotations

import itertools
import re
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.errors import AnnotationRetryableError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.program import PROGRAM_TOOL_NAME
from src.agents.annotation.schema import SearchResult
from src.workflows.annotate_helpers import block_codeact
from src.workflows.annotate_helpers.block_codeact import run_chapter_subagents

# 三段以上正文：¶1/¶3/¶4 各含一个成对引号对话候选（住手！/退下！/晚了。）
_PARAGRAPHS = [
    "沈遥喝道：“住手！”",
    "众人散去，夜色渐深。",
    "沈遥拔剑相向，喝道：“退下！”",
    "伯安低声道：“晚了。”",
]
_CHAPTER_TEXT = "".join(_PARAGRAPHS)

# ----------------------------------------------------------------------
# 脚本化伪 LLM 的程序：每个 subagent 一个程序（单轮写完），之后一轮空回复收束会话


# 结构 subagent：两名角色一条关系；带一次 search_graph 证明检索面也在真实路径上
# 2026-09-18 引用一律用本 subagent 自定 id（a1/a2…），name 只作展示与落库登记名
_STRUCTURE_PROGRAM = (
    'search_graph(entities=["沈遥"])\n'
    'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
    'entity(id="a2", name="伯安", entity_type="character", evidence=4)\n'
    'relation(from_id="a1", to_id="a2", relation_type="敌对", evidence=3)\n'
    "finish()\n"
)

# 事件 subagent：自己登记参与实体（同名会由 write_entity 按 name 会合），参与者按本 subagent id 引用
_EVENT_PROGRAM = (
    'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
    'entity(id="a2", name="伯安", entity_type="character", evidence=4)\n'
    'event(el="t1", isroot=True, description="沈遥喝止众人", evidence=1)\n'
    'event(el="t1/e2", isroot=False, type="main", description="沈遥拔剑相向", evidence=3)\n'
    'participants(el="t1", items=['
    '{"entity_id": "a1", "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1}, '
    '{"entity_id": "a2", "role": "客体", "narrative_role": "客体", "action": "旁观", "emotion": 0}])\n'
    'participants(el="t1/e2", items=['
    '{"entity_id": "a1", "role": "主体", "narrative_role": "主体", "action": "拔剑", "emotion": 1}])\n'
    "finish()\n"
)

# 证据 subagent：三条候选判完（说话人写本 subagent 实体 id）+ 两段标签 + 章级指标
_EVIDENCE_PROGRAM = (
    'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
    'entity(id="a2", name="伯安", entity_type="character", evidence=4)\n'
    'dialogue(candidate_index=1, verdict="dialogue", speaker_id="a1", tone="愤怒", evidence=1)\n'
    'dialogue(candidate_index=2, verdict="dialogue", speaker_id="a1", tone="愤怒", evidence=3)\n'
    'dialogue(candidate_index=3, verdict="dialogue", speaker_id="a2", tone="平静", evidence=4)\n'
    "label(paragraph_id=1, emotion=-1)\n"
    "label(paragraph_id=4, emotion=0)\n"
    'metric(summary="沈遥喝止众人，伯安低声道晚了", emotional_valence=-1, '
    'narrative_function="冲突", pivot_moment=True)\n'
    "finish()\n"
)

# 写法分歧：结构 subagent 只登记 沈遥，事件 subagent 的参与人名写「沈师姐」（正文里的称号写法）
# 零通信下由事件 subagent 自己登记该名，write_entity 不会合它，接续层再挂一条待核案例
_ALIAS_STRUCTURE_PROGRAM = (
    'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
    "finish()\n"
)
_ALIAS_EVENT_PROGRAM = (
    'entity(id="a1", name="沈师姐", entity_type="character", evidence=1)\n'
    'event(el="t1", isroot=True, description="沈师姐喝止众人", evidence=1)\n'
    'participants(el="t1", items=['
    '{"entity_id": "a1", "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1}])\n'
    "finish()\n"
)
_ALIAS_EVIDENCE_PROGRAM = (
    'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
    'dialogue(candidate_index=1, verdict="dialogue", speaker_id="a1", tone="愤怒", evidence=1)\n'
    'dialogue(candidate_index=2, verdict="not_dialogue")\n'
    'dialogue(candidate_index=3, verdict="not_dialogue")\n'
    "label(paragraph_id=1, emotion=-1)\n"
    'metric(summary="沈师姐喝止众人", emotional_valence=-1, narrative_function="冲突")\n'
    "finish()\n"
)

# 缺判定：证据 subagent 只判候选 1、3，候选 2 留给收尾按 not_dialogue 默认
_MISSING_DIALOGUE_EVIDENCE_PROGRAM = (
    'entity(id="a1", name="沈遥", entity_type="character", evidence=1)\n'
    'entity(id="a2", name="伯安", entity_type="character", evidence=4)\n'
    'dialogue(candidate_index=1, verdict="dialogue", speaker_id="a1", tone="愤怒", evidence=1)\n'
    'dialogue(candidate_index=3, verdict="dialogue", speaker_id="a2", tone="平静", evidence=4)\n'
    "label(paragraph_id=1, emotion=-1)\n"
    'metric(summary="沈遥喝止众人", emotional_valence=-1, narrative_function="冲突")\n'
    "finish()\n"
)

_MAIN_PROGRAMS: dict[str, list[str]] = {
    "structure": [_STRUCTURE_PROGRAM],
    "event": [_EVENT_PROGRAM],
    "evidence": [_EVIDENCE_PROGRAM],
}


class _QueryService:
    """用于提供无数据库依赖的查询桩（subagent 的检索面走真实工具，但底层无库）"""

    current_chapter_order = None

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """用于返回空正文命中"""
        del query, range_name, limit
        return []

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
        """用于声明无绑定"""
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


class _SubagentBoom(Exception):
    """用于让脚本化 LLM 在某个 subagent 上抛错（非瞬态，不触发调用层重试）"""


class _ScriptedLLM:
    """用于按 subagent 职责返回脚本化 execute_code 程序"""

    def __init__(self, programs: dict[str, list[str]], *, fail_roles: tuple[str, ...] = ()) -> None:
        """用于初始化脚本游标、绑定面记录与失败 subagent 集合"""
        self.programs = dict(programs)
        self.fail_roles = set(fail_roles)
        self.counts: dict[str, int] = {}
        self.bound_names: list[tuple[str, ...]] = []
        self.sessions: list[str] = []

    def bind_tools(self, tools: list[Any]) -> _ScriptedLLM:
        """用于记录每个 subagent 会话实际绑定给模型的工具名"""
        self.bound_names.append(tuple(str(tool.name) for tool in tools))
        return self

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        """用于返回本 subagent 的下一段程序（脚本用尽即无工具回复=会话自然收束）"""
        content = "\n".join(str(getattr(message, "content", "")) for message in messages)
        role = _subagent_role_of(content)
        self.sessions.append(role)
        if role in self.fail_roles:
            raise _SubagentBoom(f"{role} subagent boom")
        script = self.programs[role]
        index = self.counts.get(role, 0)
        self.counts[role] = index + 1
        if index >= len(script):
            return AIMessage(content="", tool_calls=[])
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": PROGRAM_TOOL_NAME,
                    "args": {"code": script[index]},
                    "id": f"{role}-{index}",
                    "type": "tool_call",
                }
            ],
        )


def _subagent_role_of(content: str) -> str:
    """用于从正文注入里辨认当前是哪个 subagent 的会话（返回 structure/event/evidence）"""
    match = re.search(r'<CurrentChapter role="(\w+)">', content)
    if match is None:
        raise AssertionError("无法辨认 subagent 会话来源（正文注入里没有 CurrentChapter role）")
    return match.group(1)


def _paragraph_rows() -> list[Any]:
    """用于构造四段正文的段落事实源行"""
    rows: list[Any] = []
    offset = 0
    for paragraph_id, text in enumerate(_PARAGRAPHS, start=1):
        rows.append(
            SimpleNamespace(
                paragraph_id=paragraph_id,
                chapter_id=1,
                local_start_char=offset,
                local_end_char=offset + len(text),
                text=text,
            )
        )
        offset += len(text)
    return rows


async def _run_subagents(*, llm: _ScriptedLLM, store: _AuditStore, graph_state: FactGraph) -> Any:
    """用于以真实编排层跑一次三 subagent 章（只换模型与无库桩）"""
    return await run_chapter_subagents(
        run_id="run-1",
        chapter_id=1,
        chapter_text=_CHAPTER_TEXT,
        chapter_paragraph_rows=_paragraph_rows(),
        llm=llm,
        sql_session_factory=store.session_factory,
        query_service_factory=lambda session: _QueryService(),
        graph_state=graph_state,
        stream=None,
        novel_id="default",
    )


# ----------------------------------------------------------------------
# 不变式 2/3：构造器即时落正式产出 + 名字即连接


@pytest.mark.asyncio
async def test_constructors_materialize_records_and_connect_names_by_name() -> None:
    """端到端：三个 subagent 的构造器即时落库；参与者/说话人按名字接到同一实体"""
    llm = _ScriptedLLM(_MAIN_PROGRAMS)
    store = _AuditStore()
    graph = FactGraph()

    result = await _run_subagents(llm=llm, store=store, graph_state=graph)

    # ---- 不变式 2：构造器把记录即时落成正式产出 ----
    # 实体与关系在图域操作日志里
    assert [op["name"] for op in result.entity_ops] == ["沈遥", "伯安"]
    assert [op["entity_type"] for op in result.entity_ops] == ["character", "character"]
    assert len(result.relation_assert_ops) == 1
    relation = result.relation_assert_ops[0]
    assert (relation["from_entity"], relation["to_entity"], relation["relation_type"]) == ("沈遥", "伯安", "敌对")

    annotation = result.annotation
    # 事件树：根 + 子（main 顺延主链）
    assert [event.description for event in annotation.events] == ["沈遥喝止众人", "沈遥拔剑相向"]
    assert [event.cause_role for event in annotation.events] == ["root", "main"]
    assert annotation.events[1].parent_node_id == annotation.events[0].node_id
    # 对话：三条候选三条判定
    assert [dialogue.content for dialogue in annotation.dialogues] == ["住手！", "退下！", "晚了。"]
    assert [dialogue.candidate_index for dialogue in annotation.dialogues] == [1, 2, 3]
    # 段标签与指标
    assert {(label.paragraph_id, label.emotion) for label in annotation.paragraph_labels} == {(1, -1), (4, 0)}
    assert annotation.metrics.summary == "沈遥喝止众人，伯安低声道晚了"
    assert annotation.metrics.emotional_valence == -1
    assert str(annotation.metrics.narrative_function) == "冲突"
    assert annotation.metrics.pivot_moment is True

    # ---- 不变式 3：名字即连接（参与者/说话人都落到同一个实体，且没多出实体）----
    root = annotation.events[0]
    assert {participant.entity for participant in root.participants} == {"沈遥", "伯安"}
    assert [participant.entity for participant in annotation.events[1].participants] == ["沈遥"]
    assert [dialogue.speaker for dialogue in annotation.dialogues] == ["沈遥", "沈遥", "伯安"]
    # 只有结构 subagent 登记的两个名字，参与者/说话人没有派生任何新实体或别名案例
    assert len(result.entity_ops) == 2
    assert result.pushed_cases == []


# ----------------------------------------------------------------------
# 不变式 4：写法分歧 → 按引用处自报大类登记 + push entity_alias 案例


@pytest.mark.asyncio
async def test_unregistered_reference_registers_entity_and_pushes_alias_case() -> None:
    """事件参与者写了结构 subagent 未登记的人名：照常登记 character，接续层再挂一条 entity_alias"""
    llm = _ScriptedLLM(
        {
            "structure": [_ALIAS_STRUCTURE_PROGRAM],
            "event": [_ALIAS_EVENT_PROGRAM],
            "evidence": [_ALIAS_EVIDENCE_PROGRAM],
        }
    )
    store = _AuditStore()
    graph = FactGraph()

    result = await _run_subagents(llm=llm, store=store, graph_state=graph)

    # 结构 subagent 只登记了 沈遥；参与者的「沈师姐」是引用处自己带出来的第二个实体
    assert [op["name"] for op in result.entity_ops] == ["沈遥", "沈师姐"]
    assert [op["entity_type"] for op in result.entity_ops] == ["character", "character"]

    # 可见降级：一条 entity_alias 案例，keys 含该名字
    alias_cases = [case for case in result.pushed_cases if case.type == "entity_alias"]
    assert len(alias_cases) == 1
    assert alias_cases[0].keys == ["沈师姐"]

    # 连接照常建起来：事件参与者落在新登记的实体上
    root = result.annotation.events[0]
    assert [participant.entity for participant in root.participants] == ["沈师姐"]


# ----------------------------------------------------------------------
# 不变式 5：缺判定的对话候选按 not_dialogue 默认，整章照常完成


@pytest.mark.asyncio
async def test_unjudged_dialogue_candidate_defaults_to_not_dialogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """候选 2 未判定：finish 回执 dialogue_defaulted 含 2，整章照常完成"""
    captured: dict[str, Any] = {}
    original_settle = block_codeact._settle_chapter

    async def spy_settle(tool_map, ledger, *, stream):
        """用于在真实收尾实现之上捕获 finish 回执"""
        receipt = await original_settle(tool_map, ledger, stream=stream)
        captured["receipt"] = receipt
        return receipt

    monkeypatch.setattr(block_codeact, "_settle_chapter", spy_settle)

    llm = _ScriptedLLM(
        {
            "structure": [_STRUCTURE_PROGRAM],
            "event": [_EVENT_PROGRAM],
            "evidence": [_MISSING_DIALOGUE_EVIDENCE_PROGRAM],
        }
    )
    store = _AuditStore()
    graph = FactGraph()

    result = await _run_subagents(llm=llm, store=store, graph_state=graph)

    # 收尾回执点名缺判定的编号
    assert captured["receipt"]["status"] == "completed"
    assert captured["receipt"]["dialogue_defaulted"] == [2]

    # 默认 not_dialogue 不落成对话，但覆盖缺口随章留痕；整章照常完成
    annotation = result.annotation
    assert [dialogue.candidate_index for dialogue in annotation.dialogues] == [1, 3]
    assert annotation.coverage_warnings == [
        "对话覆盖: 1 条候选未提交判定（序号 [2]），按 not_dialogue 默认处理",
        "情绪标签覆盖: 仅标注 1 段（每章应自选 2-3 段）",
    ]
    assert result.annotation.metrics.summary == "沈遥喝止众人"


# ----------------------------------------------------------------------
# 不变式 6：任一 subagent 失败 → 整章失败，事实图不被写脏（失败在 subagent 相位，收尾相位未起跑）


@pytest.mark.asyncio
async def test_any_subagent_failure_fails_chapter_without_dirtying_fact_graph() -> None:
    """事件 subagent 抛错：run_chapter_subagents 上抛，其他 subagent 取消，FactGraph 保持干净"""
    llm = _ScriptedLLM(_MAIN_PROGRAMS, fail_roles=("event",))
    store = _AuditStore()
    graph = FactGraph()

    with pytest.raises(AnnotationRetryableError):
        await _run_subagents(llm=llm, store=store, graph_state=graph)

    # 三个 subagent 的 invocation 都开出来了，但没有任何正式产出落进事实图
    assert sorted(row.task_type for row in store.invocations) == ["annotation_subagent"] * 3
    assert graph.entity_names == {}
    assert graph.entity_types == {}
    assert graph.chapter_registered_entities == {}
    assert graph.entity_ops == []
    assert graph.relation_assert_ops == []
    assert graph.active_relations == set()
