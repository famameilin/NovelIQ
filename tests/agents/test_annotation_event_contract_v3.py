"""契约 v3 事件层测试：全局 event_id 因果引用 + 树结构字段

覆盖：
- schema：EventInput root 带因果前驱拒绝、main/secondary 缺因果前驱拒绝、重复引用拒绝
- tools：write_events 回执返回 event_id；未授权引用拒绝；增量写引用本章已写 id 通过；
        跨章引用（search_event_history 授权）通过；全局文本偏序违反拒绝
"""

from __future__ import annotations

import pytest

from src.agents.annotation.schema import ChunkParagraphInfo, EventInput
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools
from tests.agents.test_annotation_event_history_tools import (
    _EventHistoryService,
    _history_event,
)
from tests.agents.test_annotation_evidence_tools import _call, _find_tool, _ledger


def _two_paragraph_ledger() -> AnnotationToolLedger:
    """2026-08-19 用于构造可形成合法因果链（前文→后文）的双段落账本"""
    chunk_text = "顾霜拔剑。\n顾霜收势。"
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=10,
        current_chunk_text=chunk_text,
        allow_future_context=False,
        current_chapter_order=1,
        paragraph_info=ChunkParagraphInfo(
            paragraph_ids=[0, 1],
            char_spans=[(0, 6), (7, 13)],
            texts=["顾霜拔剑。", "顾霜收势。"],
        ),
    )


def _event_payload(
    *,
    causal_event_refs: list[str] | None = None,
    tree_id: str = "tree-a",
    cause_role: str = "root",
) -> dict:
    return {
        "items": [
            {
                "description": "顾霜拔剑",
                "anchor_paragraph_ids": [0],
                "causal_event_refs": list(causal_event_refs or []),
                "tree_id": tree_id,
                "cause_role": cause_role,
            }
        ]
    }


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_event_input_rejects_root_with_causal_refs() -> None:
    """2026-08-19 用于验证 root 不允许携带因果前驱"""
    with pytest.raises(ValueError, match="cause_role=root 时 causal_event_refs 必须为空"):
        EventInput.model_validate(
            {
                "description": "顾霜拔剑",
                "anchor_paragraph_ids": [0],
                "causal_event_refs": ["event-x"],
                "tree_id": "tree-a",
                "cause_role": "root",
            }
        )


def test_event_input_rejects_main_without_causal_refs() -> None:
    """2026-08-19 用于验证 main/secondary 必须携带至少一个因果前驱"""
    with pytest.raises(ValueError, match="causal_event_refs 至少 1 个"):
        EventInput.model_validate(
            {
                "description": "顾霜拔剑",
                "anchor_paragraph_ids": [0],
                "causal_event_refs": [],
                "tree_id": "tree-a",
                "cause_role": "main",
            }
        )


def test_event_input_rejects_duplicate_causal_refs() -> None:
    """2026-08-19 用于验证因果引用不允许重复"""
    with pytest.raises(ValueError, match="causal_event_refs 不允许重复"):
        EventInput.model_validate(
            {
                "description": "顾霜拔剑",
                "anchor_paragraph_ids": [0],
                "causal_event_refs": ["event-x", "event-x"],
                "tree_id": "tree-a",
                "cause_role": "main",
            }
        )


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


def test_write_events_receipt_returns_event_ids() -> None:
    """2026-08-19 用于验证 write_events 回执返回本轮事件 event_id 供后续引用"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)
    receipt = _call(tools, "write_events", _event_payload())
    expected = ledger.current_event_id(1)
    assert receipt["event_ids"] == [expected]
    assert ledger.authorized_event_ids == {expected}
    assert ledger.event_coords[expected]["char_start"] == 0


def test_write_events_rejects_unauthorized_ref() -> None:
    """2026-08-19 用于验证未授权（本轮未写入/未检索）的事件引用被拒绝"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)
    with pytest.raises(ValueError, match="引用未授权事件: unknown-id"):
        _call(tools, "write_events", _event_payload(causal_event_refs=["unknown-id"], cause_role="main"))


def test_write_events_accepts_incremental_in_chapter_ref() -> None:
    """2026-08-19 用于验证先写前驱拿 id、后写后继引用已写 id 的增量链路"""
    ledger = _two_paragraph_ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)
    _call(tools, "write_events", _event_payload())
    eid_a = ledger.current_event_id(1)
    successor = _event_payload(causal_event_refs=[eid_a], cause_role="main")
    successor["items"][0]["anchor_paragraph_ids"] = [1]
    _call(tools, "write_events", successor)
    bound = ledger.bound_payloads["events"]
    assert bound[0].causal_event_refs == [eid_a]
    assert bound[0].cause_role == "main"


def test_write_events_rejects_same_batch_ref() -> None:
    """2026-08-19 用于验证本轮尚未返回 id 的事件不能被同轮引用（要求分轮写出）"""
    ledger = _ledger()
    tools = build_annotation_tools(_QueryServiceShim(), ledger)
    payload = {
        "items": [
            {
                "description": "前驱事件",
                "anchor_paragraph_ids": [0],
                "tree_id": "tree-a",
                "cause_role": "root",
            },
            {
                "description": "后继事件",
                "anchor_paragraph_ids": [0],
                "causal_event_refs": [ledger.current_event_id(1)],
                "tree_id": "tree-a",
                "cause_role": "main",
            },
        ]
    }
    with pytest.raises(ValueError, match="引用未授权事件"):
        _call(tools, "write_events", payload)


def test_write_events_accepts_cross_chapter_ref_via_search() -> None:
    """2026-08-19 用于验证 search_event_history 授权后可作为跨章因果前驱"""
    service = _EventHistoryService(events=[_history_event("event-a", "前章旧事")])
    ledger = _ledger()
    ledger.current_chapter_order = 2
    tools = build_annotation_tools(service, ledger)
    _find_tool(tools, "search_event_history").invoke({"query": "旧事"})
    assert "event-a" in ledger.authorized_event_ids
    assert ledger.event_coords["event-a"]["chapter_order"] == 1

    _call(tools, "write_events", _event_payload(causal_event_refs=["event-a"], cause_role="main"))
    assert ledger.bound_payloads["events"][0].causal_event_refs == ["event-a"]


def test_write_events_rejects_partial_order_violation() -> None:
    """2026-08-19 用于验证同章内前驱 char_end 晚于后继 char_start 时全局偏序拒绝"""
    ledger = _ledger()
    ledger.current_chapter_order = 1
    tools = build_annotation_tools(_QueryServiceShim(), ledger)
    _call(tools, "write_events", _event_payload())
    eid_a = ledger.current_event_id(1)
    # 同一锚点段落：后继 char_start=0 早于前驱 char_end=6 → 偏序违反
    with pytest.raises(ValueError, match="文本偏序违反"):
        _call(tools, "write_events", _event_payload(causal_event_refs=[eid_a], cause_role="main"))


class _QueryServiceShim:
    """2026-08-19 用于为事件写入提供最小查询服务（无需检索历史）"""

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        del current_text, semantic_limit, rotation_limit
        return [], []

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        del query, hidden_case_ids, limit
        return []

    async def search_text(self, query, *, range_name, limit=50):
        del query, range_name, limit
        return []

    def read_text(self, paragraph_id):
        del paragraph_id
        return ""

    def thread_exists(self, setup_id):
        del setup_id
        return False

    def fetch_active_case_details(self, case_id):
        del case_id
        return None
