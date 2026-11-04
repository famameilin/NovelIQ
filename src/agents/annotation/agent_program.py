"""Agent 内部程序面：构造器、原文与全书状态读取、案例办理及独立收尾

各角色有独立局部账本和模型会话，共用同一 run 的事实图、事件树及案例池。
构造器经 Agent 的单条内存事务直接写域，成功后登记自身局部产出。
跨章 event 引用必须来自当前执行的实际读取；finish 仅提出结束请求。
同批写入执行完毕后，程序检查最终状态。
"""

from __future__ import annotations

from typing import Any

from src.agents.program_runtime.contracts import PROGRAM_TOOL_NAME

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
    "write_event",
    "retract_structure",
    "push_case",
)

# 三个职责共享程序入口和收尾信号；事件事实由 write_event 写入
AGENT_BOUND_TOOL_NAMES: tuple[str, ...] = (PROGRAM_TOOL_NAME, FINISH_TOOL_NAME)

# 模型可见引用必须来自本 work 登记或实际读取，目录统一描述当前全书共享状态合同
_AGENT_REFERENCE_SCOPE_TEXT: str = (
    "引用与证据口径：\n"
    "- 实体引用写正文名字 + 大类；运行时解析，图里没有就自动登记，不再写 id；别名分别登记。\n"
    "- 构造器局部键：entity 用 id（形如 a1）；write_event 的每项用 el（如 t1、t2）；"
    "局部键只在本章寻址，不是 UUID，不表示父子层级。\n"
    "- evidence 与 paragraph_id 使用正文段首可见号；原文跨章全局段号须经 read_text 读取。\n"
    "- search_events 按正文顺序返回简洁索引，默认 limit=5、最多20，除末页外返回 limit 条；"
    "search_graph 预览继续按字符预算分页，实体条数用 limit、关系条数用 relation_limit（默认 20）；"
    "用 next_offset/next_relation_offset 续页，事件可按 chapter_id/tree_id 筛选，实体可按 entity_type 筛选。\n"
    "- read_event(node_id=...) / read_entity(entity_id=...) 读取完整详情，read_entity 回执带该实体已有关系；"
    "图树读取不替代原文授权。\n"
    "- write_event(items=[事件参数, ...]) 是唯一事件入口：一次提交一棵事件树；"
    "每项填写事件正文、局部键、证据与 characters；isforeshadowing=True 的伏笔埋设事件必须同时给 "
    "confidence（high/medium/low），非伏笔事件保持 False 且不填 confidence；"
    "数组顺序即树内成员顺序，树 ID 由系统独立生成；"
    "本执行尚未保存的树可以继续提交新成员，沿用原树键、新 el 接在树末尾；已写节点原样重交不新增。"
    "characters 每项写正文名字与大类，character 条目必须同时给 narrative_role/action/emotion"
    "（规则见参数说明）；事件写入后不能重交或补写参与者。"
    "from_chapter_id/to_chapter_id 记录起止章节，缺省当前章。\n"
    "- write_link(kind=parent_child) 连接两棵事件树，两端使用树 ID，空树也可连接，不要求读取成员；"
    "没有现成父树时，可用 write_event(items=[], tree_key=..., title=...) 新建空父树，再连接。"
    "允许多父与共享队列，禁止自引用和环；因果独立记录。"
    "retract_structure(kind,identifier,reason,evidence) 仅撤回本执行未保存的 queue/reference。\n"
    "- write_link 使用实际读回的 source_id/target_id；causal/foreshadowing 必须给 reason 与本章段首 "
    "evidence；parent_child 只须给 reason；\n"
    "foreshadowing 保持独立照应边，不自动合树。\n"
    "- pending(case_type,description)/push_case(case_type,description) 的 case_type 写 "
    "character/relation/dialogue/event；\n"
    "- claim_case(case_id) 指定领取，claim_random_case() 随机领取；可以同时持有多件未提交案例。"
    "办完后 submit_case(case_id)，允许核查后无需修改；提交后该案例只允许读取。"
    "提交回执最多附带十件未预占候选。"
    "下次正常推理可选熟悉候选指定领取，无合适候选或被占用就随机领取，不单独增加选案回合。"
    "业务调用可传 caseid，须先认领；领取与提交仅按各自签名传参。\n"
    "- finish(caseid=None) 仅请求结束，caseid 只关联案例、不传结束内容；同模型本轮不调用工具；"
    "缺口由程序检查后在下一轮消息里点名。\n"
    "- entity/event 不要求指标或对话；annotation/metric 必须提交实际指标并逐条判定全部对话候选。\n\n"
)

# 构造器的目录就是模型知道"能交什么、怎么交"的全部依据。
# finish 使用当前 work 工具表，仅登记结束请求
_AGENT_CONSTRUCTOR_ORDER: tuple[str, ...] = (
    "entity",
    "relation",
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
