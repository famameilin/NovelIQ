"""Agent 内部程序面：构造器、原文与全书状态读取、案例办理及独立收尾

各角色有独立局部账本和模型会话，共用同一 run 的事实图、事件树及案例池。
构造器经 Agent 的单条内存事务直接写域，成功后登记自身局部产出。
跨章 event 引用必须来自当前执行的实际读取；finish 仅提出结束请求。
同批写入执行完毕后，程序检查最终状态。
"""

from __future__ import annotations

from typing import Any

from src.agents.annotation.program_contract import PROGRAM_TOOL_NAME

from .agent_ir import AgentAnnotation
from .tools import FINISH_TOOL_NAME

# 长章三个角色独立执行，短章使用 annotation；展示名供职责文案和日志共用
AGENT_ROLE_LABELS: dict[str, str] = {
    "entity": "实体与关系",
    "event": "事件与参与者",
    "metric": "对话与章级证据",
}

# Agent 内部程序面的基础工具目录，共享状态读取和案例认领由当前 work 工具表补入
# 构造器编译的业务写入直接调用同一 Agent，程序检查自身角色，不等待其他角色
AGENT_TOOL_NAMES: tuple[str, ...] = (
    "search_text",
    "read_text",
    "read_chapter_text",
    "anchor_record",
    "write_link",
    "push_case",
)

# 三个职责共享程序入口和收尾信号；事件事实由既有 event 构造器写入
AGENT_BOUND_TOOL_NAMES: tuple[str, ...] = (PROGRAM_TOOL_NAME, FINISH_TOOL_NAME)

# 模型可见引用必须来自本 work 登记或实际读取，目录统一描述当前全书共享状态合同
_AGENT_REFERENCE_SCOPE_TEXT: str = (
    "引用与证据口径：\n"
    "- 实体引用写正文名字 + 大类；运行时解析，图里没有就自动登记，不再写 id；别名分别登记。\n"
    "- evidence 与 paragraph_id 使用正文段首可见号；原文跨章全局段号须经 read_text 读取。\n"
    "- search_events 按正文顺序返回简洁索引，默认 limit=5、最多20，除末页外返回 limit 条；"
    "search_graph 预览继续按字符预算分页；"
    "用 next_offset/next_relation_offset 续页，事件可按 chapter_id/tree_id 筛选，实体可按 entity_type 筛选。\n"
    "- read_event(node_id=...) / read_entity(entity_id=...) 读取完整详情；图树读取不替代原文授权。\n"
    "- event(el,title,problem,summary,event_type,status,evidence,progress=None) 写事件。"
    "回执 event_id 是正式事件身份；from_chapter_id/to_chapter_id 记录起止章节，缺省当前章。"
    "包含用 write_link(kind=contains) 显式建立，因果独立记录。\n"
    "- write_link 使用实际读回的 source_id/target_id；foreshadowing 保持独立照应边，不自动合树。\n"
    "- pending(case_type,description)/push_case(case_type,description) 显式归入人物/关系/对话/事件之一；"
    "- promise_case 只填真实 case_id."
    "所有调用可传 caseid，须先认领；关联失败仅 warning。\n"
    "- finish(caseid=None) 仅请求结束，同模型本轮不调用工具；程序缺项提示后继续同一会话。\n"
    "- entity/event 不要求指标或对话；annotation/metric 必须提交实际指标并逐条判定全部对话候选。\n\n"
)

# 八类构造器的目录就是模型知道"能交什么、怎么交"的全部依据。
# finish 使用当前 work 工具表，仅登记结束请求
_AGENT_CONSTRUCTOR_ORDER: tuple[str, ...] = (
    "entity",
    "relation",
    "event",
    "participants",
    "dialogue",
    "label",
    "metric",
    "pending",
    "plotline",
    "foreshadow_action",
)


def agent_gap(agent: AgentAnnotation, *, candidate_total: int) -> dict[str, Any]:
    """回报当前职责的实际缺口，不补造指标或对话判定"""
    if agent.role not in {"annotation", "metric"}:
        # 实体 agent 与事件 agent 的完整性口径只有"完成了收尾"；候选与指标不属于它们
        return {"finished": agent.finished, "missing_candidates": [], "missing_metric": False}
    judged = {item.candidate_index for item in agent.dialogues}
    return {
        "finished": agent.finished,
        "missing_candidates": sorted(set(range(1, candidate_total + 1)) - judged),
        "missing_metric": agent.metric is None,
    }
