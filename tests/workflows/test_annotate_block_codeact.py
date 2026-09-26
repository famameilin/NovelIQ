"""章内多代理并发：编排层（三条 subagent 并发 → 章收尾相位）的合同测试

2026-09-18 写入生效重构后，subagent 的构造器当场经生产单条事务边界落库、三个 subagent
共享同一个章级账本，编排层只剩"派发 + 收尾"两段。本文件 monkeypatch 掉 subagent 运行器
（不真跑模型），覆盖：

- 多块章按 `SUBAGENT_ROLES` 并发派发三条 subagent，每条拿到同一个共享章级账本、同一份
  工具表与同一把章级写锁，角色与运行参数逐条传对（靠"三条都进到等待点"证明重叠，
  而不是串行等待）；
- 任一 subagent 失败：取消其余在飞 subagent、异常上抛、`FactGraph` 章节改动被回滚；
- 收尾相位顺序：接续层（跨 agent 展示名分歧挂案例）→ 指标/标签一次落库 → finish，
  且收尾相位不落节点（实体/事件在 subagent 相位即时生效）；
- 子事件先于树根写入被生产写入当场拒（"先根后子"由 write_event 在写入当场保证）；
- 收尾失败整章失败并回滚章节改动；
- 章级结果与审计（授权足迹/写记录/案例）全部取自共享账本；
- `build_chapter_paragraph_info` 与段落行一致、空段落行显式拒绝。

2026-09-19 双路径定案：solo 形态与 codeact_enabled 开关随单块章归 agent 路径一起退役，
本文件只剩 subagent 路径（roles 参数保留供单角色编排用例使用）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents.annotation import graph as annotation_graph
from src.agents.annotation import subagent_connect as subagent_connect_module
from src.agents.annotation.errors import AnnotationRetryableError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import ChapterParagraphInfo, PendingCase, SearchResult
from src.agents.annotation.subagent_ir import (
    SubagentAnnotation,
    SubagentEntity,
    SubagentLabel,
    SubagentMetric,
)
from src.agents.annotation.subagent_program import SUBAGENT_ROLES, SubagentRunOutcome
from src.workflows.annotate_helpers import block_codeact
from src.workflows.annotate_helpers.block_codeact import (
    build_chapter_paragraph_info,
    run_chapter_subagents,
)

TEXT = "“站住！”沈遥喝道。她收起长刀，转身走进雨里。"
P1 = "“站住！”沈遥喝道。"
P2 = "她收起长刀，转身走进雨里。"
PARAGRAPH_ROWS = [
    SimpleNamespace(paragraph_id=1, local_start_char=0, local_end_char=len(P1), text=P1),
    SimpleNamespace(paragraph_id=2, local_start_char=len(P1), local_end_char=len(TEXT), text=P2),
]


class _QueryService:
    """用于提供无数据库依赖的查询桩"""

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


def _outcome(subagent: SubagentAnnotation) -> SubagentRunOutcome:
    """用于构造一个 subagent 会话的产出（授权足迹与案例都在共享账本上，不再搬运）"""
    return SubagentRunOutcome(subagent=subagent, final_messages=[])


def _kwargs(*, graph_state: FactGraph | None = None) -> dict:
    """用于构造编排器的完整入参"""
    return {
        "run_id": "run-1",
        "chapter_id": 1,
        "chapter_text": TEXT,
        "chapter_paragraph_rows": list(PARAGRAPH_ROWS),
        "llm": MagicMock(),
        "sql_session_factory": MagicMock(),
        "query_service_factory": lambda session_factory: _QueryService(),
        "graph_state": graph_state,
        "stream": None,
        "novel_id": "default",
    }


# ----------------------------------------------------------------------
# 一、按 roles 并发派发，运行参数逐条传对


@pytest.mark.asyncio
async def test_multi_role_dispatch_concurrently_with_correct_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """三条 subagent 按 SUBAGENT_ROLES 并发派发，共享同一账本/工具表/写锁，参数逐条传对"""
    llm = MagicMock()
    session_factory = MagicMock()
    kwargs = _kwargs(graph_state=FactGraph())
    kwargs["llm"] = llm
    kwargs["sql_session_factory"] = session_factory

    dispatched: list[str] = []
    received: dict[str, dict] = {}
    all_started = asyncio.Event()

    async def fake_subagent_agent(**call_kwargs):
        role = call_kwargs["role"]
        dispatched.append(role)
        received[role] = {
            "subagent_role": call_kwargs["subagent"].role,
            "ledger": call_kwargs["ledger"],
            "tool_map": call_kwargs["tool_map"],
            "write_lock": call_kwargs["write_lock"],
            "run_id": call_kwargs["run_id"],
            "chapter_id": call_kwargs["chapter_id"],
            "novel_id": call_kwargs["novel_id"],
            "llm": call_kwargs["llm"],
            "session_factory": call_kwargs["session_factory"],
            "graph_state": call_kwargs["graph_state"],
            "stream": call_kwargs["stream"],
        }
        if len(dispatched) == 3:
            all_started.set()
        # 串行派发时这里会等到超时（TimeoutError）→ 用例失败，即"重叠"的反证
        await asyncio.wait_for(all_started.wait(), timeout=5)
        call_kwargs["subagent"].finished = True
        return _outcome(call_kwargs["subagent"])

    monkeypatch.setattr(block_codeact, "run_subagent_agent", fake_subagent_agent)

    result = await run_chapter_subagents(**kwargs)

    assert len(dispatched) == 3
    assert sorted(dispatched) == sorted(SUBAGENT_ROLES)
    assert {role: item["subagent_role"] for role, item in received.items()} == {role: role for role in SUBAGENT_ROLES}
    # 共享章级账本、同一份工具表、同一把写锁：三条 subagent 拿到的是同一个对象
    assert len({id(item["ledger"]) for item in received.values()}) == 1
    assert len({id(item["tool_map"]) for item in received.values()}) == 1
    assert len({id(item["write_lock"]) for item in received.values()}) == 1
    assert len({id(item["graph_state"]) for item in received.values()}) == 1
    for item in received.values():
        assert item["run_id"] == "run-1"
        assert item["chapter_id"] == 1
        assert item["novel_id"] == "default"
        assert item["llm"] is llm
        assert item["session_factory"] is session_factory
        assert item["stream"] is None
    # 没有 subagent 提交指标时章收尾走中性兜底，整章照常产出结果
    assert result.annotation is not None


# ----------------------------------------------------------------------
# 二、任一 subagent 失败：取消其余在飞 subagent、异常上抛、章节改动回滚


@pytest.mark.asyncio
async def test_subagent_failure_cancels_siblings_and_resets_chapter_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """事件 subagent 抛错：其余两条被取消，异常上抛，FactGraph 回滚本章改动"""
    cancelled: list[str] = []

    async def fake_subagent_agent(**call_kwargs):
        role = call_kwargs["role"]
        if role == "event":
            await asyncio.sleep(0.01)
            raise RuntimeError("subagent boom")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(role)
            raise
        return _outcome(call_kwargs["subagent"])

    monkeypatch.setattr(block_codeact, "run_subagent_agent", fake_subagent_agent)
    graph_state = MagicMock(spec=FactGraph)

    with pytest.raises(RuntimeError, match="subagent boom"):
        await asyncio.wait_for(run_chapter_subagents(**_kwargs(graph_state=graph_state)), timeout=10)

    assert sorted(cancelled) == ["evidence", "structure"]
    graph_state.begin_chapter.assert_called_once()
    graph_state.reset_chapter_changes.assert_called_once()


# ----------------------------------------------------------------------
# 三、收尾相位顺序：接续层 → 指标/标签 → finish，且不落节点


@pytest.mark.asyncio
async def test_finish_phase_pushes_connections_then_metrics_then_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """实体在 subagent 相位即时落库 → 接续层挂分歧案例 → 指标/标签一次落库 → finish"""
    calls: list[tuple[str, dict]] = []

    async def fake_subagent_agent(**call_kwargs):
        role = call_kwargs["role"]
        subagent = call_kwargs["subagent"]
        tool_map = call_kwargs["tool_map"]
        if role == "structure":
            calls.append(("subagent:write_entity", {"name": "沈遥"}))
            tool_map["write_entity"].func(name="沈遥", entity_type="character", el="structure:a1")
            subagent.entities.append(SubagentEntity(id="a1", name="沈遥", entity_type="character"))
        elif role == "event":
            calls.append(("subagent:write_entity", {"name": "沈师姐"}))
            tool_map["write_entity"].func(name="沈师姐", entity_type="character", el="event:a1")
            subagent.entities.append(SubagentEntity(id="a1", name="沈师姐", entity_type="character"))
        elif role == "evidence":
            subagent.metric = SubagentMetric(summary="冲突", emotional_valence=-1, narrative_function="冲突")
            subagent.labels.append(SubagentLabel(paragraph_id=1, emotion=-1))
            subagent.labels.append(SubagentLabel(paragraph_id=2, emotion=0))
        subagent.finished = True
        return _outcome(subagent)

    monkeypatch.setattr(block_codeact, "run_subagent_agent", fake_subagent_agent)

    real_execute = annotation_graph._execute_call

    async def recording_execute(call, **exec_kwargs):
        calls.append((str(call.get("name")), dict(call.get("args") or {})))
        return await real_execute(call, **exec_kwargs)

    # 收尾相位与接续层各持一份 _execute_call 全局引用，两处都要换成记录版
    monkeypatch.setattr(block_codeact, "_execute_call", recording_execute)
    monkeypatch.setattr(subagent_connect_module, "_execute_call", recording_execute)

    result = await run_chapter_subagents(**_kwargs(graph_state=FactGraph()))

    names = [name for name, _ in calls]
    # 收尾相位不落节点：实体已在 subagent 相位生效，收尾只挂跨 agent 案例 + 指标 + finish
    assert "write_entity" not in names
    assert "write_event" not in names
    assert names.count("finish") == 1
    assert names[-1] == "finish"
    # 接续层的展示名分歧案例先于指标与 finish
    assert names.index("push_case") < names.index("write_metrics") < names.index("finish")
    last_entity = max(index for index, (name, _) in enumerate(calls) if name == "subagent:write_entity")
    first_finish_phase = min(
        index for index, (name, _) in enumerate(calls) if name in {"push_case", "write_metrics", "finish"}
    )
    assert last_entity < first_finish_phase

    alias_call = next(args for name, args in calls if name == "push_case")
    assert alias_call["type"] == "entity_alias"
    assert alias_call["keys"] == ["沈师姐"]
    metrics_call = next(args for name, args in calls if name == "write_metrics")
    assert metrics_call["summary"] == "冲突"
    assert [(item["paragraph_id"], item["emotion"]) for item in metrics_call["labels"]] == [(1, -1), (2, 0)]

    assert [op["name"] for op in result.entity_ops] == ["沈遥", "沈师姐"]
    assert result.annotation is not None
    assert result.annotation.metrics.summary == "冲突"
    assert [case.type for case in result.pushed_cases] == ["entity_alias"]


# ----------------------------------------------------------------------
# 四、子事件先于树根写入被生产写入当场拒


@pytest.mark.asyncio
async def test_subagent_phase_rejects_child_event_before_root_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """子事件先于树根写入：生产写入当场判拒（树键未建），建根后同键子事件才落账

    2026-09-18 写入生效后"先根后子"由生产 write_event 在写入当场保证，不再是落库相位的
    重排职责；模型先写子事件会拿到结构化拒绝，自纠补根后同键子事件照常落账。
    """
    statuses: list[str] = []

    async def fake_subagent_agent(**call_kwargs):
        tool_map = call_kwargs["tool_map"]
        ledger = call_kwargs["ledger"]
        child_first = await annotation_graph._execute_call(
            {
                "name": "write_event",
                "args": {"el": "event:t1/e1", "isroot": False, "type": "main", "description": "子一", "evidence": 1},
                "id": "a",
            },
            tool_map=tool_map,
            ledger=ledger,
            call_index=0,
        )
        root = await annotation_graph._execute_call(
            {
                "name": "write_event",
                "args": {"el": "event:t1", "isroot": True, "description": "根", "evidence": 1},
                "id": "b",
            },
            tool_map=tool_map,
            ledger=ledger,
            call_index=1,
        )
        child_after = await annotation_graph._execute_call(
            {
                "name": "write_event",
                "args": {"el": "event:t1/e2", "isroot": False, "type": "main", "description": "子二", "evidence": 2},
                "id": "c",
            },
            tool_map=tool_map,
            ledger=ledger,
            call_index=2,
        )
        statuses.extend([str(child_first["status"]), str(root["status"]), str(child_after["status"])])
        call_kwargs["subagent"].metric = SubagentMetric(summary="事件", emotional_valence=0, narrative_function="铺垫")
        call_kwargs["subagent"].finished = True
        return _outcome(call_kwargs["subagent"])

    monkeypatch.setattr(block_codeact, "run_subagent_agent", fake_subagent_agent)

    result = await run_chapter_subagents(**_kwargs(graph_state=FactGraph()), roles=("event",))

    assert statuses == ["error", "success", "success"]
    annotation = result.annotation
    assert [event.description for event in annotation.events] == ["根", "子二"]
    assert [event.evidence_paragraph_id for event in annotation.events] == [1, 2]
    assert [event.cause_role for event in annotation.events] == ["root", "main"]
    assert annotation.events[1].parent_node_id == annotation.events[0].node_id


# ----------------------------------------------------------------------
# 五、收尾失败：整章失败并回滚章节改动


@pytest.mark.asyncio
async def test_finish_phase_failure_resets_chapter_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """finish 被拒：异常上抛，收尾相位已写入的章节改动被回滚（不留脏状态）"""

    async def fake_subagent_agent(**call_kwargs):
        call_kwargs["subagent"].metric = SubagentMetric(summary="x", emotional_valence=0, narrative_function="铺垫")
        call_kwargs["subagent"].finished = True
        return _outcome(call_kwargs["subagent"])

    monkeypatch.setattr(block_codeact, "run_subagent_agent", fake_subagent_agent)

    async def boom(tool_map, ledger, *, stream):
        del tool_map, ledger, stream
        raise AnnotationRetryableError("finish 被拒")

    monkeypatch.setattr(block_codeact, "_settle_chapter", boom)
    graph_state = MagicMock(spec=FactGraph)

    with pytest.raises(AnnotationRetryableError):
        await run_chapter_subagents(**_kwargs(graph_state=graph_state))

    graph_state.begin_chapter.assert_called_once()
    graph_state.reset_chapter_changes.assert_called_once()


# ----------------------------------------------------------------------
# 六、章级结果与审计取自共享账本


@pytest.mark.asyncio
async def test_chapter_result_and_audit_read_from_shared_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    """授权足迹/案例 id/写记录都落在共享账本上，章级结果与审计直接读它的终态"""
    captured: dict = {}
    pushed = PendingCase(
        type="其他疑点",
        chapter_id=1,
        keys=["长刀"],
        description="共享账本案例",
        target_key="shared-case",
        target_ref={},
    )

    async def fake_subagent_agent(**call_kwargs):
        role = call_kwargs["role"]
        subagent = call_kwargs["subagent"]
        ledger = call_kwargs["ledger"]
        captured["ledger"] = ledger
        if role == "structure":
            ledger.authorized_text_paragraph_ids.update({1, 2})
            ledger.authorized_chapter_ids.add(10)
            ledger.authorized_event_ids.add("tree-1")
            # 2026-09-19 案例 id 纪律：无运行期编号，案例 id 直接登记到授权面 known_case_ids
            ledger.known_case_ids.update({"case-a", "case-b"})
            subagent.metric = SubagentMetric(summary="共享账本", emotional_valence=1, narrative_function="转折")
        elif role == "event":
            ledger.authorized_text_paragraph_ids.add(3)
            ledger.authorized_event_ids.add("tree-2")
            # 案例 id 全章去重：另一条 subagent 登记同一 case_id 不产生重复条目
            ledger.known_case_ids.add("case-b")
            assert ledger.known_case_ids == {"case-a", "case-b"}
        elif role == "evidence":
            ledger.pushed_cases.append(pushed)
        subagent.finished = True
        return _outcome(subagent)

    monkeypatch.setattr(block_codeact, "run_subagent_agent", fake_subagent_agent)

    result = await run_chapter_subagents(**_kwargs(graph_state=FactGraph()))
    ledger = captured["ledger"]

    assert result.annotation is not None
    assert result.annotation.metrics.summary == "共享账本"
    # 审计字段就是共享账本的终态，不做任何外部补并
    assert result.audit.authorized_text_paragraph_ids == [1, 2, 3]
    assert result.audit.authorized_chapter_ids == [10]
    assert result.audit.authorized_event_ids == ["tree-1", "tree-2"]
    assert result.audit.write_records == list(ledger.write_records)
    assert result.audit.write_records
    assert result.resolved_cases == []
    assert result.pushed_cases == [pushed]
    # 案例 id 按全章去重登记（另一条 subagent 登记同一 id 不产生重复条目）
    assert ledger.known_case_ids == {"case-a", "case-b"}


# ----------------------------------------------------------------------
# 七、段落坐标映射


def test_build_chapter_paragraph_info_matches_paragraph_rows() -> None:
    """段落坐标映射与段落行逐项一致，段号即全局 paragraph_id"""
    info = build_chapter_paragraph_info(list(PARAGRAPH_ROWS), chapter_text=TEXT)

    assert isinstance(info, ChapterParagraphInfo)
    assert info.paragraph_ids == [1, 2]
    assert info.char_spans == [(0, len(P1)), (len(P1), len(TEXT))]
    assert info.texts == [P1, P2]
    assert "".join(info.texts) == TEXT


def test_build_chapter_paragraph_info_rejects_empty_rows() -> None:
    """空段落行：没有事实源可锚，显式抛可重试错误"""
    with pytest.raises(AnnotationRetryableError):
        build_chapter_paragraph_info([], chapter_text=TEXT)
