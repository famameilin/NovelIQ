"""程序面工具返回结构：目录与诊断面共用同一份说明来源"""

from __future__ import annotations

import json
from typing import Any

# 工具函数本身的返回值（不是 execute_code 外层回执）：key 是工具名，值是该工具的真实形状
TOOL_RETURN_SHAPES: dict[str, Any] = {
    "search_text": [
        {
            "content": "命中原文，超长截断",
            "truncated": "是否截断",
            "keyword_score": "命中查询词项数，相近项为0",
            "semantic_score": "语义相近分，仅相近项有",
            "chapter_id": "真实章号",
            "paragraph_ids": ["真实段号"],
            "capability": "current_text 或 other_text",
            "next_offset": "下一页偏移，仅末条在还有下一页时给出",
        }
    ],
    "read_text": {
        "chapter_id": "真实章号",
        "paragraph_id": "真实段号",
        "char_start": "片段起点",
        "char_end": "片段终点",
        "text_hash": "片段原文摘要",
        "content": "实际原文",
        "source_ref": "证据来源ID",
    },
    "read_chapter_text": {
        "chapter_id": "真实章号",
        "paragraph_id": "真实段号",
        "char_start": "片段起点",
        "char_end": "片段终点",
        "text_hash": "片段原文摘要",
        "content": "实际原文",
        "source_ref": "证据来源ID",
    },
    "search_events": {
        "events": [
            {
                "event_id": "真实事件ID，read_event 的 node_id 也填它",
                "chapter_id": "真实章号",
                "tree_id": "所属事件树ID，作 parent_child 端点时填它",
                "from": "起始章号或null",
                "to": "结束章号或null",
                "saved": "是否已正式保存",
                "is_foreshadow_setup": "是否伏笔根",
                "title": "标题",
                "event_type": "事件类型",
                "status": "事件状态",
                "problem": "问题，只有 compact=false 才有",
                "summary": "概要，只有 compact=false 才有",
                "evidence_paragraph_id": "证据段号或null，只有 compact=false 才有",
                "evidence": "证据列表，只有 compact=false 才有",
            }
        ],
        "trees": [
            {
                "tree_id": "事件树ID，作 parent_child 端点时填它",
                "tree_key": "树标识或null",
                "title": "树标题",
                "description": "树说明",
                "event_count": "成员事件数，空树为0",
                "from": "树内最早起始章或null",
                "to": "树内最晚结束章或null",
                "parent_tree_ids": ["已挂的父树ID"],
                "child_tree_ids": ["已挂的子树ID"],
                "is_top_level": "是否没有父树",
            }
        ],
        "total": "命中总数",
        "next_offset": "下一页偏移或null，null 表示没有下一页",
    },
    "read_event": {
        "node_id": "事件ID，与 event_id 相同",
        "event_id": "事件ID",
        "kind": "固定 event；读诊断对象时是对应对象类型",
        "chapter_id": "真实章号",
        "saved": "是否已正式保存",
        "content": "事件正文：title/problem/summary/event_type/status/participants/evidence_paragraph_id/from/to 等",
        "tree_id": "所属事件树ID或null",
        "tree_event_ids": ["同树事件ID"],
        "event_line_ids": ["所属事件线树ID"],
    },
    "search_graph": {
        "entities": [{"id": "实体ID", "name": "规范名", "entity_type": "大类"}],
        "relations": [{"source_id": "实体ID", "target_id": "实体ID", "relation_type": "关系类型"}],
        "total_entities": "实体总数",
        "total_relations": "关系总数",
        "next_offset": "实体下一页偏移或null",
        "next_relation_offset": "关系下一页偏移或null",
    },
    "read_entity": {
        "id": "实体ID",
        "name": "规范名",
        "entity_type": "大类",
        "attributes": "属性对象",
        "relations": [
            {
                "source_id": "实体ID",
                "source_name": "规范名",
                "target_id": "实体ID",
                "target_name": "规范名",
                "relation_type": "关系类型",
            }
        ],
    },
    "search_cases": [
        {"case_id": "真实案例ID", "case_type": "四类之一", "claimed": "是否已领取", "submitted": "是否已提交"}
    ],
    "read_metrics": {
        "aggregate": "全局指标",
        "pivots": ["转折点"],
        "high_tension": ["高张力段"],
        "foreshadowing": ["伏笔来源"],
        "foreshadow_expectation": "伏笔回收预期",
        "relation_changes": ["关系变化"],
        "graph_signals": "图谱统计",
    },
    "read_topics": {"topics": [{"topic_id": "真实主题ID", "words": "主题词", "label": "标签"}]},
    "claim_case": {"status": "claimed、submitted 或 taken", "case_id": "真实案例ID"},
    "claim_random_case": {
        "status": "claimed 或 empty",
        "case_id": "成功时的真实案例ID",
        "case_type": "四类之一",
        "description": "案例说明",
    },
    "submit_case": {
        "status": "submitted",
        "case_id": "已提交案例ID",
        "candidates": [{"case_id": "可领案例ID", "case_type": "四类之一", "description": "案例说明"}],
    },
    "push_case": {"case_id": "真实案例ID"},
    "anchor_record": {"accepted": True, "record": "对象键", "source_ref": "证据来源ID"},
    "write_link": {"status": "written", "kind": "关联类型", "connection_id": "关联身份"},
    "write_event": {
        "status": "written",
        "tree_id": "事件树独立ID",
        "results": [{"status": "written", "record": "记录键", "content": "该事件读回内容，同 read_event"}],
        "failed": [],
        "warnings": "可选，条目级提示",
    },
    "retract_structure": {"status": "withdrawn", "kind": "queue 或 reference", "identifier": "撤回对象ID"},
    "finish": {"status": "end_requested"},
}

# 构造器统一返回写入回执：成功带 record 与 ref，被拒带 record/field/code/expected/message
WRITE_RECEIPT_NOTE = (
    "写入回执：status=written 带 record 与 ref；"
    "被拒时 status=rejected 带 record/field/code/expected/message"
)

_RETURN_NOTE_MAX_CHARS = 700


def render_return_note(shape: Any) -> str:
    """把返回结构压成目录里的一行；超长按字符截断"""
    text = json.dumps(shape, ensure_ascii=False, separators=(",", ":"))
    if len(text) > _RETURN_NOTE_MAX_CHARS:
        text = f"{text[:_RETURN_NOTE_MAX_CHARS]}…"
    return text
