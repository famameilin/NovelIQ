"""search_event 工具与 authorized_event_ids 授权链路测试

覆盖：
- 检索返回历史事件树根视图并把 tree_id/root_node_id 登记进授权集合
- 本章事件写入即生效：apply_event_root/apply_event_child 当场把树的根节点 id 与
  tree_id 登记进 authorized_event_ids / authorized_tree_ids，无需任何域结算
  （2026-09-13 取消暂存后的事件合同）
- 非 chunk_open 阶段拒绝检索
- resolve_foreshadowing_case 对未授权 root/event 拒绝、对非伏笔根拒绝
- 章内局部键（t1、t1/e1）在 finish_chunk 之前即可直接引用
- 先检索授权后 resolve 通过（根事件+挂树事件写入 ResolvedCase）
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationInputError
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    EntityInput,
    EventTreeHistoryResult,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

_CHUNK_TEXT = "\u201c住手\u201d回荡"


class _EventHistoryService:
    """2026-08-18 用于记录检索调用并返回预设历史事件树的测试查询服务"""

    def __init__(
        self,
        trees: list[EventTreeHistoryResult] | None = None,
        current_chapter_order: int = 2,
    ) -> None:
        self.trees = trees or []
        self.current_chapter_order = current_chapter_order
        self.calls: list[tuple[str, int]] = []

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-11 案例改检索制：案例经 search_pool 展示取得编号（旧合同为注入候选）"""
        del query, hidden_case_ids, case_type, limit
        return SearchResult(results=[self._case()])

    def _case(self) -> CaseSearchResult:
        """2026-08-18 用于构造可严格解决的活动案例"""
        return CaseSearchResult(
            id="case-1",
            type="foreshadowing_payoff",
            chunk_id=10,
            keys=["线索"],
            description="伏笔回收判断",
        )

    def fetch_active_case_details(self, case_id):
        """2026-08-18 用于返回包含稳定目标的 active 案例"""
        if case_id != "case-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="thread-1",
            target_ref={"kind": "伏笔疑点", "chunk_id": 10},
        )

    def search_event_history(self, query, *, limit=50):
        """2026-08-30 用于记录严格历史检索并返回预设树根视图"""
        self.calls.append((query, limit))
        return list(self.trees)


def _history_tree(
    tree_id: str,
    root_node_id: str,
    description: str,
    *,
    foreshadow: bool = False,
) -> EventTreeHistoryResult:
    """2026-08-22 用于构造预设历史树根视图（foreshadow=True 即伏笔树根）"""
    return EventTreeHistoryResult(
        tree_id=tree_id,
        root_node_id=root_node_id,
        chapter_id=1,
        chapter_order=1,
        description=description,
        participants=[{"entity": "顾霜", "role": "主体"}],
        cross_chapter=False,
        is_foreshadow_setup=foreshadow,
        foreshadowing_status="open" if foreshadow else None,
    )


def _ledger() -> AnnotationToolLedger:
    """2026-08-18 用于构造带唯一 current 原文的工具账本"""
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=2,
        current_chunk_id=10,
        current_chunk_text=_CHUNK_TEXT,
        allow_future_context=False,
        current_chapter_order=2,
    )


def _tools(service, ledger):
    return build_annotation_tools(service, ledger)


def _find_tool(tools, name):
    return next(candidate for candidate in tools if candidate.name == name)


def _register_payoff_case(service, ledger) -> int:
    """2026-08-18 用于把活动案例登记进账本并返回临时编号

    2026-09-11 案例改检索制：编号只能由 search_pool 回执产生，测试准备亦走该通道。
    """
    tools = _tools(service, ledger)
    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "线索"}))
    return int(view["results"][0]["case_number"])


def test_search_event_registers_authorized_tree_ids() -> None:
    """2026-08-22检索结果把 tree_id 与 root_node_id 登记进授权集合"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_event").invoke({"keyword": "顾霜"}))

    assert view["trees"][0]["tree_id"] == "tree-h"
    assert ledger.authorized_event_ids == {"tree-h", "node-h-root"}
    assert ledger.history_tree_views["tree-h"]["root_node_id"] == "node-h-root"
    assert service.calls == [("顾霜", 20)]
    assert ledger.search_log[-1]["tool"] == "search_event"
    assert ledger.search_log[-1]["hits"] == ["tree-h"]


def test_search_event_rejects_outside_chunk_open_phase() -> None:
    """2026-08-18 用于验证非 chunk_open 阶段检索被拒绝"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    ledger.set_phase("writing")
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="阶段 .* 不允许 search_event"):
        _find_tool(tools, "search_event").invoke({"keyword": "顾霜"})


def test_resolve_foreshadowing_case_rejects_unauthorized_event_id() -> None:
    """2026-09-13 用于验证未经授权的 root_event_id 不能被伏笔解决引用"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match="root_event_id 未由事件回执或 search_event 授权: event-x",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "event-x",
                "event_id": "node-h-root",
            }
        )


def test_resolve_foreshadowing_case_tree_id_mixup_gets_targeted_hint() -> None:
    """2026-09-04 第6章教训回归：把 tree_id 误当 root_event_id 时报错须点名这层混淆

    2026-09-13 取消暂存：apply_event_root 写入即把本章树的根节点 id 登记进
    authorized_event_ids、tree_id 登记进 authorized_tree_ids（真实 id 不外露，
    模型面只用章内局部键）；本测试按写入即生效链路造出一棵已落账的树，再把真实
    tree_id 误当 root_event_id 提交（模型面回执不含 id，这层混淆依旧只能靠报错自纠）。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    ledger.graph = FactGraph()
    ledger.apply_entity(EntityInput(name="顾霜", entity_type="character"))
    ledger.apply_event_root(
        tree_key="t1",
        description="顾霜立誓",
        cause_tree_id=None,
        isforeshadowing=False,
        expected_payoff_family=None,
        payoff_likelihood=None,
    )
    ledger.apply_event_child(tree_key="t1", node_key="e1", order=1, node_type="main", description="顾霜收势")
    real_tree_id = ledger.tree_key_index["t1"]
    real_root_id = ledger.event_trees[real_tree_id]["root_node_id"]
    assert real_root_id in ledger.authorized_event_ids
    assert real_tree_id not in ledger.authorized_event_ids
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationAuthorizationError,
        match=(
            rf"root_event_id 未由事件回执或 search_event 授权: {real_tree_id}"
            r".*这是事件树的 id 而非节点 id.*章内局部键 t1/e1.*root_node_id"
        ),
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": real_tree_id,
                "event_id": real_root_id,
            }
        )


def test_resolve_foreshadowing_case_accepts_chapter_local_event_keys() -> None:
    """2026-09-13 本章事件用章内局部键引用：写入即生效，t1 / t1/e1 直接可用

    取消暂存后 write_event_root / write_event_child 的回执只有章内键（t1、e1），
    真实节点 id 由写入当场生成并登记；resolve_foreshadowing_case 接受章内局部键，
    模型不必转抄 uuid，也不再出现 tree_id 与节点 id 混用。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    ledger.graph = FactGraph()
    ledger.apply_entity(EntityInput(name="顾霜", entity_type="character"))
    ledger.apply_event_root(
        tree_key="t1",
        description="顾霜立誓",
        cause_tree_id=None,
        isforeshadowing=True,
        expected_payoff_family="身份揭晓",
        payoff_likelihood="high",
    )
    ledger.apply_event_child(tree_key="t1", node_key="e1", order=1, node_type="main", description="顾霜收势")
    root_node_id, child_node_id = [event.node_id for event in ledger.bound_payloads["events"]]
    assert ledger.chunk_finished is False
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "t1",
                "event_id": "t1/e1",
            }
        )
    )

    assert resolved["accepted"] is True
    assert ledger.resolved_cases[-1].foreshadowing_root_event_id == root_node_id
    assert ledger.resolved_cases[-1].foreshadowing_event_id == child_node_id


def test_resolve_foreshadowing_case_registers_case_when_number_omitted() -> None:
    """2026-09-13 case_number 可省略：服务端就本次挂树自动登记「伏笔疑点」案例并回执编号

    run c80105cc 实测：编号曾为必填却在模型可见面上零说明，模型读完"章内局部键
    写入即生效"的 docstring 后判定"池里没有该伏笔案例、无法调用"，ch3/ch4 跨回合
    重推 4~8 次共约 3 万字符、只产出 1 次调用。挂树只认树根与挂树事件的键，
    案例只是池内记账，省略编号时由服务端补登记。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    ledger.graph = FactGraph()
    ledger.apply_entity(EntityInput(name="顾霜", entity_type="character"))
    ledger.apply_event_root(
        tree_key="t1",
        description="顾霜立誓",
        cause_tree_id=None,
        isforeshadowing=True,
        expected_payoff_family="身份揭晓",
        payoff_likelihood="high",
    )
    ledger.apply_event_child(tree_key="t1", node_key="e1", order=1, node_type="main", description="顾霜收势")
    tools = _tools(service, ledger)
    pushed_before = len(ledger.pushed_cases)

    receipt = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "reason": "伏笔回收",
                "foreshadowing_action": "payoff",
                "root_event_id": "t1",
                "event_id": "t1/e1",
            }
        )
    )

    assert receipt["accepted"] is True
    assert receipt["action"] == "foreshadowing"
    assert len(ledger.pushed_cases) == pushed_before + 1
    auto_case = ledger.pushed_cases[-1]
    assert auto_case.type == "伏笔疑点"
    assert auto_case.target_ref["kind"] == "伏笔疑点"
    # 回执编号就是自动登记那条案例的运行期编号（模型可直接引用或后续核对）
    assert receipt["case_number"] == ledger.case_number_by_id[auto_case.target_key]
    # 池内记账：自动案例与显式编号同路，本次解决即登记 ResolvedCase（不留活动噪声）
    assert ledger.resolved_cases[-1].action == "foreshadowing"


def test_rejected_foreshadowing_resolve_leaves_no_case_behind() -> None:
    """2026-09-13 校验失败的挂树调用不得在池里留下孤儿案例

    自动登记排在全部挂树校验之后：引用未授权时直接报错、pushed_cases 不变；
    否则本章收尾会把它按活动案例落库，成为后续章节重复裁决的检索噪声。
    """
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)
    pushed_before = len(ledger.pushed_cases)

    with pytest.raises(AnnotationAuthorizationError, match="root_event_id 未由事件回执或 search_event 授权"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "event-x",
                "event_id": "node-h-root",
            }
        )

    assert len(ledger.pushed_cases) == pushed_before


def test_resolve_foreshadowing_case_chapter_key_available_before_finish() -> None:
    """2026-09-13 变化点：章内局部键在 finish_chunk 之前即可用（旧合同要求先域结算）

    旧合同（逐域 finish）下"结算前引用被拒"——t1 / t1/root 报未授权并提示先
    finish_domain("events")；取消暂存后写入即生效：本测试在未调 finish_chunk
    （chunk_finished=False）时让同一组键直接解析到真实节点 id，因此旧调用不再报
    未授权，而是前进到合同校验——埋设事件自身不挂边（event_id == root_event_id）被拒；
    补写子事件后同一路径无需任何收尾即可完成伏笔挂树。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    ledger.graph = FactGraph()
    ledger.apply_entity(EntityInput(name="顾霜", entity_type="character"))
    ledger.apply_event_root(
        tree_key="t1",
        description="顾霜立誓",
        cause_tree_id=None,
        isforeshadowing=True,
        expected_payoff_family="身份揭晓",
        payoff_likelihood="high",
    )
    assert ledger.chunk_finished is False
    # 结算前解析：t1 与根节点别名 t1/root 指向同一真实节点 id（旧合同在结算前为 None）
    resolved_root = ledger.resolve_event_reference("t1")
    assert resolved_root is not None
    assert resolved_root == ledger.resolve_event_reference("t1/root")
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    with pytest.raises(
        AnnotationInputError,
        match=r"event_id 不得与 root_event_id 相同（埋设事件自身不挂边）",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "t1",
                "event_id": "t1/root",
            }
        )
    assert ledger.resolved_cases == []

    # 补写子事件后同一对章内局部键在收尾前即可完成挂树
    ledger.apply_event_child(tree_key="t1", node_key="e1", order=1, node_type="main", description="顾霜收势")
    child_node_id = ledger.event_trees[ledger.tree_key_index["t1"]]["nodes"]["e1"]
    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "t1",
                "event_id": "t1/e1",
            }
        )
    )

    assert resolved["accepted"] is True
    assert ledger.chunk_finished is False
    assert ledger.ready_chunk is None
    assert ledger.resolved_cases[-1].foreshadowing_root_event_id == resolved_root
    assert ledger.resolved_cases[-1].foreshadowing_event_id == child_node_id


def test_resolve_foreshadowing_case_passes_authorized_event_ids() -> None:
    """2026-09-13 先 search_event 授权后 resolve 可把本章事件挂进伏笔树"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-setup", "node-setup", "顾霜立誓", foreshadow=True),
            _history_tree("tree-payoff", "node-payoff", "顾霜兑现承诺"),
        ]
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    _find_tool(tools, "search_event").invoke({"keyword": "顾霜"})
    assert ledger.authorized_event_ids >= {"tree-setup", "node-setup", "tree-payoff", "node-payoff"}

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "伏笔回收",
                "foreshadowing_action": "reinforce",
                "root_event_id": "node-setup",
                "event_id": "node-payoff",
            }
        )
    )

    assert resolved["accepted"] is True
    last = ledger.resolved_cases[-1]
    assert last.action == "foreshadowing"
    assert last.foreshadowing_action == "reinforce"
    assert last.foreshadowing_root_event_id == "node-setup"
    assert last.foreshadowing_event_id == "node-payoff"


def test_resolve_foreshadowing_case_rejects_non_foreshadow_root() -> None:
    """2026-09-13 伏笔即事件树：root_event_id 非伏笔树根（埋设事件）时拒绝并指向发现通道"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=False),
            _history_tree("tree-p", "node-payoff", "精灵身份当众揭示"),
        ],
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)

    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})
    with pytest.raises(
        AnnotationInputError,
        match=r"root_event_id 不是伏笔树的根（埋设事件）: node-h-root",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点强化",
                "foreshadowing_action": "reinforce",
                "root_event_id": "node-h-root",
                "event_id": "node-payoff",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_foreshadowing_case_rejects_event_id_equal_to_root() -> None:
    """2026-09-13 伏笔树合同：埋设事件自身不挂边，event_id == root_event_id 拒绝"""
    service = _EventHistoryService(
        trees=[_history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=True)],
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})

    with pytest.raises(
        AnnotationInputError,
        match=r"event_id 不得与 root_event_id 相同（埋设事件自身不挂边）",
    ):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点续接",
                "foreshadowing_action": "reinforce",
                "root_event_id": "node-h-root",
                "event_id": "node-h-root",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_foreshadowing_case_binds_history_root_with_foreshadow_view() -> None:
    """2026-09-13 伏笔树根经 search_event 树根视图授权后 resolve 通过"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=True),
            _history_tree("tree-p", "node-payoff", "精灵身份当众揭示"),
        ],
    )
    ledger = _ledger()
    tools = _tools(service, ledger)
    case_number = _register_payoff_case(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "疑点被证实",
                "foreshadowing_action": "payoff",
                "root_event_id": "node-h-root",
                "event_id": "node-payoff",
                "expected_payoff_family": "身份揭露",
            }
        )
    )
    assert resolved["accepted"] is True
    last = ledger.resolved_cases[-1]
    assert last.foreshadowing_action == "payoff"
    assert last.foreshadowing_root_event_id == "node-h-root"
    assert last.foreshadowing_event_id == "node-payoff"
    assert last.expected_payoff_family == "身份揭露"
