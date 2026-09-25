"""search_event 授权链路与 write_event 伏笔挂树测试

覆盖：
- 检索返回历史事件树根视图并把 tree_id/root_node_id 登记进授权集合
- 本章事件写入即生效：write_event 当场把树的根节点 id 与 tree_id 登记进
  authorized_event_ids / authorized_tree_ids，无需任何域结算
  （2026-09-14 写入面重构：根/子合并进 apply_event，el 层级键挂树、无 order）
- 非 chapter_open 阶段拒绝检索
- 2026-09-18 案例裁决工具删净（resolve_dialogue_case / resolve_fact_case /
  resolve_foreshadowing_case）：伏笔树挂边能力下沉到 write_event 的
  foreshadowing_action + root_event_id，本文件按同等强度验证——授权解析
  （unknown_reference）、章内局部键可用、非伏笔根拒绝（not_foreshadowing_root）、
  自挂拒绝（invalid_value）、两字段必须同给（invalid_call），以及写入路径自发的
  无案例解决项（ResolvedCase.case_id=""，不进案例池）
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.errors import AnnotationAuthorizationError, AnnotationStageRejection
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import (
    EntityInput,
    EventTreeHistoryResult,
    SearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

_CHUNK_TEXT = "“住手”回荡"


class _EventHistoryService:
    """2026-08-18 用于记录检索调用并返回预设历史事件树的测试查询服务"""

    def __init__(
        self,
        trees: list[EventTreeHistoryResult] | None = None,
    ) -> None:
        self.trees = trees or []
        self.calls: list[tuple[str, int]] = []

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """2026-09-11 案例改检索制：本文件不再走案例路径，返回空池即可"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    def fetch_active_case_details(self, case_id):
        """2026-08-18 用于满足查询服务的案例详情合同（本文件不消费）"""
        del case_id
        return None

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
        current_chapter_text=_CHUNK_TEXT,
        allow_future_context=False,
        current_chapter_order=2,
    )


def _tools(service, ledger):
    return build_annotation_tools(service, ledger)


def _find_tool(tools, name):
    return next(candidate for candidate in tools if candidate.name == name)


def _write_chapter_tree(
    ledger: AnnotationToolLedger,
    *,
    isforeshadowing: bool = False,
    confidence: str | None = None,
) -> None:
    """2026-09-14 用于直接经账本落账一棵本章事件树（t1 根 + t1/e1 main 子节点）

    写入面重构后根/子合并进 apply_event：根 el=树键、子 el=树键/节点键，
    树内先后=调用顺序；伏笔属性（isforeshadowing/confidence）只挂在根上。
    """
    ledger.graph = FactGraph()
    ledger.apply_entity(EntityInput(name="顾霜", entity_type="character"), el="顾霜")
    ledger.apply_event(
        el="t1",
        isroot=True,
        description="顾霜立誓",
        isforeshadowing=isforeshadowing,
        confidence=confidence,
    )
    ledger.apply_event(el="t1/e1", isroot=False, node_type="main", description="顾霜收势")


def _attach_call(
    *,
    el: str,
    root_event_id: str,
    action: str = "reinforce",
    isroot: bool = False,
    node_type: str | None = "main",
    description: str = "顾霜收势",
    isforeshadowing: bool = False,
    confidence: str | None = None,
) -> dict:
    """2026-09-18 用于构造 write_event 挂树调用参数（写入节点 + 指定伏笔树根）"""
    payload: dict = {
        "el": el,
        "isroot": isroot,
        "description": description,
        "foreshadowing_action": action,
        "root_event_id": root_event_id,
    }
    if node_type is not None:
        payload["type"] = node_type
    if isforeshadowing:
        payload["isforeshadowing"] = isforeshadowing
        payload["confidence"] = confidence
    return payload


def _attach(tools, **kwargs) -> dict:
    """2026-09-18 用于直接调用 write_event 挂树并解析成功回执"""
    return json.loads(_find_tool(tools, "write_event").invoke(_attach_call(**kwargs)))


def _tree(ledger: AnnotationToolLedger) -> dict:
    """2026-09-18 用于取本章 t1 事件树（真实 uuid 只在账本内部）"""
    return ledger.event_trees[ledger.tree_key_index["t1"]]


def test_search_event_registers_authorized_tree_ids() -> None:
    """2026-08-22 检索结果登记授权；2026-09-19 id 纪律收敛授权面

    树视图只带根节点 id（不再暴露 tree_id/root_node_id/chapter_id 等内部键），
    授权集合只登记根节点 id——tree_id 曾被一并放行为事件引用（P0），已修复。
    """
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_event").invoke({"keyword": "顾霜"}))

    assert view["trees"][0]["id"] == "node-h-root"
    assert set(view["trees"][0]) == {
        "id",
        "chapter_order",
        "description",
        "participants",
        "is_foreshadow_setup",
        "foreshadowing_status",
        "payoff_likelihood",
    }
    assert ledger.authorized_event_ids == {"node-h-root"}
    assert ledger.authorized_tree_ids == {"tree-h"}
    assert ledger.history_tree_views["tree-h"]["root_node_id"] == "node-h-root"
    assert service.calls == [("顾霜", 20)]
    assert ledger.search_log[-1]["tool"] == "search_event"
    assert ledger.search_log[-1]["hits"] == ["顾霜进入山门"]


def test_search_event_rejects_outside_chunk_open_phase() -> None:
    """2026-08-18 用于验证非 chapter_open 阶段检索被拒绝"""
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    ledger.set_phase("writing")
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError):
        _find_tool(tools, "search_event").invoke({"keyword": "顾霜"})


def test_write_event_foreshadowing_rejects_unauthorized_root() -> None:
    """2026-09-18 挂树能力下沉到写入路径：未经授权的 root_event_id 仍被拒（unknown_reference）

    原 resolve_foreshadowing_case 的授权解析由 write_event 承继：root_event_id 经
    ledger.resolve_event_reference 解析，解析不到即结构化拒绝，且不登记
    ResolvedCase、不产生任何案例池记账。
    """
    service = _EventHistoryService(trees=[_history_tree("tree-h", "node-h-root", "顾霜进入山门")])
    ledger = _ledger()
    _write_chapter_tree(ledger)
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationStageRejection) as exc_info:
        _find_tool(tools, "write_event").invoke(_attach_call(el="t1/e1", root_event_id="event-x"))

    receipt = exc_info.value.receipt()
    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "root_event_id"
    assert receipt["code"] == "unknown_reference"
    assert "event-x" in receipt["message"]
    assert ledger.resolved_cases == []


def test_write_event_foreshadowing_requires_both_fields() -> None:
    """2026-09-18 foreshadowing_action 与 root_event_id 必须同时给，缺一即 invalid_call

    取值只认 schema.FORESHADOWING_ACTIONS（reinforce/payoff），非法动作同样落在
    invalid_call，被拒的调用不登记 ResolvedCase。
    """
    ledger = _ledger()
    _write_chapter_tree(ledger)
    tools = _tools(_EventHistoryService(), ledger)
    write_event = _find_tool(tools, "write_event")

    with pytest.raises(AnnotationStageRejection) as missing_root:
        write_event.invoke(
            {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜收势",
             "foreshadowing_action": "reinforce"}
        )
    assert missing_root.value.receipt()["code"] == "invalid_call"
    assert missing_root.value.receipt()["field"] == "foreshadowing_action"

    with pytest.raises(AnnotationStageRejection) as bad_action:
        write_event.invoke(
            {"el": "t1/e1", "isroot": False, "type": "main", "description": "顾霜收势",
             "foreshadowing_action": "decay", "root_event_id": "t1"}
        )
    assert bad_action.value.receipt()["code"] == "invalid_call"
    assert ledger.resolved_cases == []


def test_write_event_foreshadowing_rejects_tree_id_as_root() -> None:
    """2026-09-18 把 tree_id 误当 root_event_id 提交仍被拒（unknown_reference）

    2026-09-14 写入即生效：apply_event 建树即把本章树根节点 id 登记进
    authorized_event_ids、tree_id 登记进 authorized_tree_ids（真实 id 不外露，
    模型面只用章内局部键）；tree_id 不是节点 id，解析不到即拒绝。
    """
    service = _EventHistoryService()
    ledger = _ledger()
    _write_chapter_tree(ledger, isforeshadowing=True, confidence="high")
    real_tree_id = ledger.tree_key_index["t1"]
    real_root_id = ledger.event_trees[real_tree_id]["root_node_id"]
    assert real_root_id in ledger.authorized_event_ids
    assert real_tree_id not in ledger.authorized_event_ids
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationStageRejection) as exc_info:
        _find_tool(tools, "write_event").invoke(
            _attach_call(el="t1/e1", root_event_id=real_tree_id)
        )

    receipt = exc_info.value.receipt()
    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "root_event_id"
    assert receipt["code"] == "unknown_reference"
    assert real_tree_id in receipt["message"]
    assert ledger.resolved_cases == []


def test_write_event_foreshadowing_accepts_chapter_local_keys() -> None:
    """2026-09-14 本章事件用章内局部键引用：写入即生效，t1 / t1/e1 直接可用

    写入面重构后 write_event 的回执只有章内键（t1、t1/e1），真实节点 id 由写入
    当场生成并登记；root_event_id 接受章内局部键（t1 指本章伏笔树根），模型不必
    转抄 uuid。成功时写入路径自己登记一条无案例的 ResolvedCase。
    """
    ledger = _ledger()
    _write_chapter_tree(ledger, isforeshadowing=True, confidence="high")
    tree = _tree(ledger)
    root_node_id, child_node_id = tree["nodes"]["root"], tree["nodes"]["e1"]
    assert ledger.chapter_finished is False
    tools = _tools(_EventHistoryService(), ledger)

    resolved = _attach(tools, el="t1/e1", root_event_id="t1", action="reinforce")

    assert resolved["status"] == "written"
    assert resolved["record"] == "t1/e1"
    assert resolved["content"]["foreshadowing"] == {
        "action": "reinforce",
        "root_event_id": root_node_id,
        "event_id": child_node_id,
    }
    assert [event.node_id for event in ledger.bound_payloads["events"]] == [root_node_id, child_node_id]
    last = ledger.resolved_cases[-1]
    assert last.foreshadowing_root_event_id == root_node_id
    assert last.foreshadowing_event_id == child_node_id


def test_write_event_foreshadowing_records_caseless_resolved_entry() -> None:
    """2026-09-18 写入路径自发的挂边不是案例裁决：ResolvedCase.case_id="" 且不动案例池

    原 resolve_foreshadowing_case 省略编号时会在池里自动登记「伏笔疑点」案例；
    该自动登记随工具删除，挂边只追加一条无案例条目（target_key=""、
    target_ref 只带当前 chapter_id），池内不新增任何案例。
    """
    ledger = _ledger()
    _write_chapter_tree(ledger, isforeshadowing=True, confidence="high")
    tools = _tools(_EventHistoryService(), ledger)
    pushed_before = len(ledger.pushed_cases)

    receipt = _attach(tools, el="t1/e1", root_event_id="t1", action="payoff")

    entry = ledger.resolved_cases[-1]
    assert entry.case_id == ""
    assert entry.action == "foreshadowing"
    assert entry.type == ""
    assert entry.target_key == ""
    assert entry.target_ref == {"chapter_id": 2}
    assert entry.foreshadowing_action == "payoff"
    assert len(ledger.pushed_cases) == pushed_before
    assert receipt["content"]["foreshadowing"]["action"] == "payoff"


def test_write_event_foreshadowing_chapter_key_available_before_finish() -> None:
    """2026-09-13 变化点：章内局部键在 finish 之前即可用（旧合同要求先域结算）

    取消暂存后写入即生效：未调 finish（chapter_finished=False、ready_chapter=None）时
    t1 / t1/root 就解析到同一真实节点 id，子事件也在同一路径上无需任何收尾即可挂树。
    """
    ledger = _ledger()
    ledger.graph = FactGraph()
    ledger.apply_entity(EntityInput(name="顾霜", entity_type="character"), el="顾霜")
    ledger.apply_event(
        el="t1",
        isroot=True,
        description="顾霜立誓",
        isforeshadowing=True,
        confidence="high",
    )
    assert ledger.chapter_finished is False
    # 结算前解析：t1 与根节点别名 t1/root 指向同一真实节点 id（旧合同在结算前为 None）
    resolved_root = ledger.resolve_event_reference("t1")
    assert resolved_root is not None
    assert resolved_root == ledger.resolve_event_reference("t1/root")
    tools = _tools(_EventHistoryService(), ledger)

    resolved = _attach(tools, el="t1/e1", root_event_id="t1", action="reinforce")

    child_node_id = _tree(ledger)["nodes"]["e1"]
    assert resolved["status"] == "written"
    assert ledger.chapter_finished is False
    assert ledger.ready_chapter is None
    assert ledger.resolved_cases[-1].foreshadowing_root_event_id == resolved_root
    assert ledger.resolved_cases[-1].foreshadowing_event_id == child_node_id


def test_write_event_foreshadowing_uses_authorized_history_root() -> None:
    """2026-09-13 先 search_event 授权后 write_event 可把本章事件挂进历史伏笔树"""
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-setup", "node-setup", "顾霜立誓", foreshadow=True),
            _history_tree("tree-payoff", "node-payoff", "顾霜兑现承诺"),
        ]
    )
    ledger = _ledger()
    _write_chapter_tree(ledger)
    tools = _tools(service, ledger)

    _find_tool(tools, "search_event").invoke({"keyword": "顾霜"})
    # 2026-09-19 id 纪律：授权集合只登记根节点 id，tree_id 不再放行为事件引用
    assert ledger.authorized_event_ids >= {"node-setup", "node-payoff"}
    assert "tree-setup" not in ledger.authorized_event_ids
    assert "tree-payoff" not in ledger.authorized_event_ids

    receipt = _attach(tools, el="t1/e1", root_event_id="node-setup", action="reinforce")

    assert receipt["status"] == "written"
    assert receipt["content"]["foreshadowing"]["root_event_id"] == "node-setup"
    last = ledger.resolved_cases[-1]
    assert last.action == "foreshadowing"
    assert last.foreshadowing_action == "reinforce"
    assert last.foreshadowing_root_event_id == "node-setup"
    assert last.foreshadowing_event_id == _tree(ledger)["nodes"]["e1"]


def test_write_event_foreshadowing_rejects_non_foreshadow_root_without_case_noise() -> None:
    """2026-09-13 伏笔即事件树：root_event_id 非伏笔树根时拒绝，且不在池里留案例噪声

    自动登记早已退役：校验失败的挂边调用 pushed_cases 不变、resolved_cases 也不增长，
    否则本章收尾会把它按活动案例落库，成为后续章节重复裁决的检索噪声。
    """
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=False),
            _history_tree("tree-p", "node-payoff", "精灵身份当众揭示"),
        ],
    )
    ledger = _ledger()
    _write_chapter_tree(ledger)
    tools = _tools(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})
    pushed_before = len(ledger.pushed_cases)

    with pytest.raises(AnnotationStageRejection) as exc_info:
        _find_tool(tools, "write_event").invoke(
            _attach_call(el="t1/e1", root_event_id="node-h-root", action="reinforce")
        )

    receipt = exc_info.value.receipt()
    assert receipt["record"] == "t1/e1"
    assert receipt["field"] == "root_event_id"
    assert receipt["code"] == "not_foreshadowing_root"
    assert "node-h-root" in receipt["message"]
    assert ledger.resolved_cases == []
    assert len(ledger.pushed_cases) == pushed_before


def test_write_event_foreshadowing_rejects_self_attach() -> None:
    """2026-09-13 伏笔树合同：埋设事件自身不挂边（invalid_value）

    挂树事件就是本次写入的节点：章内局部键 t1 一并作 el 与 root_event_id 时
    解析到同一个节点 id，写入路径按"不能挂到自己身上"拒绝，不登记 ResolvedCase。
    """
    ledger = _ledger()
    _write_chapter_tree(ledger, isforeshadowing=True, confidence="high")
    tools = _tools(_EventHistoryService(), ledger)

    with pytest.raises(AnnotationStageRejection) as exc_info:
        _find_tool(tools, "write_event").invoke(
            _attach_call(
                el="t1",
                isroot=True,
                node_type=None,
                description="顾霜立誓",
                root_event_id="t1",
                isforeshadowing=True,
                confidence="high",
            )
        )

    receipt = exc_info.value.receipt()
    assert receipt["record"] == "t1/root"
    assert receipt["field"] == "root_event_id"
    assert receipt["code"] == "invalid_value"
    assert ledger.resolved_cases == []


def test_write_event_foreshadowing_binds_history_foreshadow_root() -> None:
    """2026-09-14 历史伏笔树根经 search_event 授权后可由写入路径挂边（payoff 回收）

    旧 resolve_foreshadowing_case 的可选根属性更新（payoff_likelihood）随工具删除；
    根属性在写入时由 isforeshadowing/confidence 决定，挂边只记录 action/root/event。
    """
    service = _EventHistoryService(
        trees=[
            _history_tree("tree-h", "node-h-root", "白芷承认精灵族身份", foreshadow=True),
            _history_tree("tree-p", "node-payoff", "精灵身份当众揭示"),
        ],
    )
    ledger = _ledger()
    _write_chapter_tree(ledger)
    tools = _tools(service, ledger)
    _find_tool(tools, "search_event").invoke({"keyword": "白芷"})

    resolved = _attach(tools, el="t1/e1", root_event_id="node-h-root", action="payoff")

    child_node_id = _tree(ledger)["nodes"]["e1"]
    assert resolved["status"] == "written"
    assert resolved["content"]["foreshadowing"] == {
        "action": "payoff",
        "root_event_id": "node-h-root",
        "event_id": child_node_id,
    }
    last = ledger.resolved_cases[-1]
    assert last.case_id == ""
    assert last.foreshadowing_action == "payoff"
    assert last.foreshadowing_root_event_id == "node-h-root"
    assert last.foreshadowing_event_id == child_node_id
