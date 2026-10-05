"""章内三代理并发：单个 subagent 的程序面（八类构造器 + 完整工具面 + subagent 会话运行器）

设计（《章内多代理重设计-三代理并发版》§3/§3.1/§4）：

- **三个 subagent 的模型可见面完全相同（不按域裁剪）**：`execute_code`、`submit_events` 与 `finish`
  三项（八类构造器、检索与案例登记装在 execute_code 的 description 里，事件可直接提交数据）。
  域分工只写在职责文案里，不通过拿掉工具或构造器实现——依据是 run c80105cc 的实测
  （工具按域渐进解锁时，模型在多个回合反复确认能力缺口，67% 思考落在锁定轮，
  锁定轮只发 14% 调用）。
- **构造器写入生效**（2026-09-18）：构造器只做校验与写参构造，运行时立即把这笔写入交给
  生产单条事务边界（`graph._execute_call`，与写者面同一个实现）——成功才落 journal、
  才回 `{status:"written", record, ref}`；被拒的那一条只作废自己（journal 不动，
  模型拿到 record/field/code/expected 当场自纠，程序继续跑后面的语句）。
  实体/事件的落库 el 按角色命名空间化（`角色:局部键`，见 namespace_el），
  所以三个 subagent 各自的 a1/t1 互不占用；同名实体由生产写入自己会合。
- **subagent 之间共享章级账本**（同一个 AnnotationToolLedger、同一份工具表）：
  案例编号全章唯一，授权足迹也不再需要落库相位搬运。
- **2026-10-02 对齐 0.2.0 工具面**：检索面收成 `search_text`（0.2.0 起标注只检索原文），
  案例面只剩 `push_case`（裁决机器与 search_pool/promise_case/close_case 已退役）；
  relation 构造器去 change_kind（关系变化归 write_link），event 构造器去伏笔挂树参数，
  dialogue 构造器去 candidate_key 订正路径（0.2.0 write_dialogue 无订正入口）。
- 当前批次无失败且显式 `finish` 的职责缺口清零时直接结束，省去模型复述完成的回合
  无工具回复或轮次上限只结束会话，runner 仍检查是否交付完整
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入（大文件拆分聚合面）。

# 创建时间：2026-10-02　创建者：Trae
# 任务：subagent_program.py 大文件拆分——回执 helpers + 规范化 + 构造器账本 +
# build_subagent_constructors + build_subagent_finish_tool 迁出至 subagent_constructors.py，
# SubagentProgramRuntime/SubagentRunOutcome 迁出至 subagent_runtime.py，
# run_subagent_agent 迁出至 subagent_runner.py；本模块保留角色/工具面常量与缺口计算
# 并对迁出符号 re-export（block_codeact 等外部导入方零改动）。
# 说明：纯结构搬移，不改任何运行逻辑与签名。

from __future__ import annotations

from typing import Any

from .event_submission import SUBMIT_EVENTS_TOOL_NAME
from .program import PROGRAM_TOOL_NAME
from .subagent_ir import SUBAGENT_ROLES, SubagentAnnotation
from .tools import FINISH_TOOL_NAME

# 三个 subagent 的名字（多块章三条并发；单块章走 runner 的 agent 路径）：单源在
# subagent_ir（prompts 的职责范围文案按同一份角色名建表），本模块只转出
# subagent 的展示名（职责文案与日志共用）
SUBAGENT_ROLE_LABELS: dict[str, str] = {
    "structure": "实体与关系",
    "event": "事件与参与者",
    "evidence": "对话与章级证据",
}

# 三个 subagent 在 execute_code 程序面里的工具目录（检索 + 案例登记）。顺序与分组只影响
# 模型可见目录的排列，三个 subagent 拿到的是同一份；正式写入工具与章级 finish 都不在其中
# （subagent 写不出去任何正式记录）。2026-10-02 对齐 0.2.0 工具面：检索只剩 search_text，
# 案例面只剩 push_case（search_pool/promise_case/close_case 随裁决机器退役）。
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

# 2026-09-18 本面的引用与证据口径（渲染在构造器目录之前，全局定义一次）。
# 为什么必须有这一块：构造器的实体引用走 _require_known_entity_id，只认"本 subagent 登记过的
# id"；而正式工具的 docstring 教的是"填 run 级 id 或本章 的 el 键"（写者面真的收这两者）。
# 两面共用一份 tools.py 文案，subagent 程序面若照抄就会教错——模型按外部 id 写
# relation(from_id=<id>) 只会连吃 unknown_reference 拒绝。
_SUBAGENT_REFERENCE_SCOPE_TEXT: str = (
    "引用与证据口径：\n"
    "- 实体引用（relation 的 from_id/to_id、participants 的 entity_id、dialogue 的 speaker_id、"
    "pending 的 keys）写你在本 subagent 用 entity() 登记过的 id；别名、称号分别登记成不同 id。\n"
    "- 证据（evidence、paragraph_id）写正文段首可见号：每段开头的 `N：` 里的 N，一个整数即可，"
    "服务端按号取段、不需要抄原文；号码越界会被拒并回报合法号范围。\n"
    "- push_case(record_id=...) 指向的是产出记录：写写入回执里的 record 原值（照抄，不要自己拼）："
    "实体形如 structure/entity/a1、事件形如 event/t1、对话形如 evidence/dialogue/…，"
    "且必须是本章已经写出来的记录——疑点登记只记账，语义改动由那条记录自己承担。\n"
    "- 本章原文用 read_chapter_text(paragraph_id=段首可见号)；跨章 search_text 命中里的全局段落号"
    "用 read_text(paragraph_id=全局段落号)。两者都返回 source_ref，不要自行换算或构造引用。\n"
    "- push_case 的 evidence_refs 逐字照抄读取回执的 source_ref（不是段落号）；"
    "search_text 命中不产生 source_ref，先读取那一段再登记证据。\n\n"
)

# 八类构造器（§3.1 的目录就是模型知道"能交什么、怎么交"的全部依据）。
# 收尾不是构造器：subagent 的 finish 是面上一等工具（见 build_subagent_finish_tool）。
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

# subagent 关键产出缺失时的续跑上限：attempt_number 到本值即放行（缺口在章收尾面上可见降级），
# subagent 级重试有界（1 次续跑），不做无限修
_SUBAGENT_GATE_ATTEMPTS = 2


def subagent_gap(subagent: SubagentAnnotation, *, candidate_total: int) -> dict[str, Any]:
    """用于判一个 subagent "交完了没有"：没声明收尾、候选缺判定、指标缺提交

    写入在构造器里就生效，subagent 自己的遗漏在章收尾相位没有模型通道可补，所以缺口只能
    在这里判出来：不完整即续跑一次（同一个会话，产出记录与轮次预算都还在），仍不完整才
    放行并把缺口交给章收尾面的可见降级（指标中性兜底、未判候选按 not_dialogue 默认——
    与单 agent 收尾的 `_default_undecided_dialogues` 同口径）。
    """
    if subagent.role != "evidence":
        # 结构 subagent 与事件 subagent 的完整性口径只有"声明了收尾"；候选与指标不属于它们
        return {"finished": subagent.finished, "missing_candidates": [], "missing_metric": False}
    judged = {item.candidate_index for item in subagent.dialogues}
    return {
        "finished": subagent.finished,
        "missing_candidates": sorted(set(range(1, candidate_total + 1)) - judged),
        "missing_metric": subagent.metric is None,
    }


def subagent_gap_is_clean(gap: dict[str, Any]) -> bool:
    """用于判缺口是否已经消掉（续跑一次后仍不完整即放行）"""
    return bool(gap.get("finished")) and not gap.get("missing_candidates") and not gap.get("missing_metric")


from .subagent_constructors import (  # noqa: E402
    build_subagent_constructors as build_subagent_constructors,
)
from .subagent_constructors import (
    build_subagent_finish_tool as build_subagent_finish_tool,
)
from .subagent_runner import run_subagent_agent as run_subagent_agent  # noqa: E402
from .subagent_runtime import (  # noqa: E402
    SubagentProgramRuntime as SubagentProgramRuntime,
)
from .subagent_runtime import (
    SubagentRunOutcome as SubagentRunOutcome,
)

__all__ = [
    "SUBAGENT_BOUND_TOOL_NAMES",
    "SUBAGENT_ROLES",
    "SUBAGENT_ROLE_LABELS",
    "SUBAGENT_TOOL_NAMES",
    "SubagentProgramRuntime",
    "SubagentRunOutcome",
    "build_subagent_constructors",
    "build_subagent_finish_tool",
    "subagent_gap",
    "subagent_gap_is_clean",
    "run_subagent_agent",
]
