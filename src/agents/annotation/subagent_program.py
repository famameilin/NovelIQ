"""Agent 内部程序面：构造器、原文与全书状态读取、案例办理及独立收尾

各角色有独立局部账本和模型会话，共用同一 run 的事实图、事件树及案例池。
构造器经 Agent 的单条内存事务直接写域，成功后登记自身局部产出。
跨章 event 引用必须来自当前执行的实际读取；finish 校验自身角色并关闭写面。
同批迟到写入只登记拒绝审计，不撤销此前成功的 finish。
"""

from __future__ import annotations

from typing import Any

from src.agents.annotation.event_submission import SUBMIT_EVENTS_TOOL_NAME
from src.agents.annotation.program_contract import PROGRAM_TOOL_NAME

from .subagent_ir import SubagentAnnotation
from .tools import FINISH_TOOL_NAME

# 长章三个角色独立执行，短章使用 solo；展示名供职责文案和日志共用
SUBAGENT_ROLE_LABELS: dict[str, str] = {
    "structure": "实体与关系",
    "event": "事件与参与者",
    "evidence": "对话与章级证据",
}

# Agent 内部程序面的基础工具目录，共享状态读取和案例认领由当前 work 工具表补入
# 构造器编译的业务写入直接调用同一 Agent，finish 关闭自身角色，不等待其他角色
SUBAGENT_TOOL_NAMES: tuple[str, ...] = (
    "search_text",
    "read_text",
    "read_chapter_text",
    "anchor_record",
    "write_link",
    "push_case",
)

# 三个职责共享程序入口、结构化事件入口和收尾工具
SUBAGENT_BOUND_TOOL_NAMES: tuple[str, ...] = (PROGRAM_TOOL_NAME, SUBMIT_EVENTS_TOOL_NAME, FINISH_TOOL_NAME)

# 模型可见引用必须来自本 work 登记或实际读取，目录统一描述当前全书共享状态合同
_SUBAGENT_REFERENCE_SCOPE_TEXT: str = (
    "引用与证据口径：\n"
    "- 实体引用用本 work 登记的局部 id，或 search_graph 实际读回的实体 UUID；别名分别登记。\n"
    "- evidence 与 paragraph_id 使用正文段首可见号；原文跨章全局段号须经 read_text 读取。\n"
    "- search_graph/search_events 分页返回全书共享状态预览，默认 limit=5、最多20，整页至多6000字符；"
    "用 next_offset/next_relation_offset 续页，事件可按 chapter_id/tree_id 筛选，实体可按 entity_type 筛选。\n"
    "- read_event(node_id=...) / read_entity(entity_id=...) 读取完整详情；图树读取不替代原文授权。\n"
    "- event(parent_ref/node_ref) 连接实际读取的节点，明确 main/secondary；其他未保存 work 端点不可连接。\n"
    "- write_link 使用实际读回的 source_id/target_id；foreshadowing 保持独立照应边，不自动合树。\n"
    "- pending 和 push_case 只有 description（1..100 字）；promise_case 只有真实 case_id。\n"
    "- finish(case_delivery={case_id,state,reason}, complete=False) 交付后继续；complete=True 校验并关闭自己的角色。\n"
    "- structure/event 不要求指标或对话；solo/evidence 必须提交实际指标并逐条判定全部对话候选。\n\n"
)

# 八类构造器（§3.1 的目录就是模型知道"能交什么、怎么交"的全部依据）。
# finish 使用当前 work 工具表，校验局部产出后关闭写入
_SUBAGENT_CONSTRUCTOR_ORDER: tuple[str, ...] = (
    "entity",
    "relation",
    "event",
    "participants",
    "dialogue",
    "label",
    "metric",
    "pending",
)


def subagent_gap(subagent: SubagentAnnotation, *, candidate_total: int) -> dict[str, Any]:
    """回报当前职责的实际缺口，不补造指标或对话判定"""
    if subagent.role not in {"solo", "evidence"}:
        # 结构 subagent 与事件 subagent 的完整性口径只有"声明了收尾"；候选与指标不属于它们
        return {"finished": subagent.finished, "missing_candidates": [], "missing_metric": False}
    judged = {item.candidate_index for item in subagent.dialogues}
    return {
        "finished": subagent.finished,
        "missing_candidates": sorted(set(range(1, candidate_total + 1)) - judged),
        "missing_metric": subagent.metric is None,
    }
