"""
章节标注图节点注入文案：轮次预算提醒、缺域收尾提醒与进度账本渲染
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：graph.py 大文件拆分——预算/缺域提醒与进度账本文案 helpers 迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与文案内容；graph.py 对全部符号保留 re-export，
# 既有导入方零改动。本模块只依赖 tools，不反向依赖 graph。

from __future__ import annotations

from .tools import _DOMAIN_ORDER, AnnotationToolLedger


def _turn_budget_reminder(remaining: int, *, total: int | None = None, subagent_face: bool = False) -> str:
    """2026-09-05 用于构造临近内部循环上限时模型可见的收尾提醒

    2026-09-05 第3章死锁：模型空转 15 轮 40 次检索 0 写入后撞硬顶，
    全程看不到轮次预算。此提醒为纯消息注入（不改工具开放与路由），
    只对本次请求生效、不写入状态消息链，避免多轮提醒在历史中堆积。

    2026-09-13 末轮点名收尾：run c80105cc 第 4 章实测——末轮文案只说
    "提交全部已确认内容"，模型把写入排在前面、finish_chunk 留给"下一轮"，该轮
    结束后撞硬顶、整章作废（第 15 轮思考里计划含 finish_chunk，实际只发出 3 个
    写入调用）。末轮必须点名唯一的收尾动作，并说明收尾可与写入同批提交。
    2026-09-18 收尾工具更名 finish；收尾工具与 execute_code 同为绑定面上的工具，
    同一条回复里并列发出即可（收尾判定在本批全部调用处理完后执行）。
    2026-09-18 两面的撞顶后果不同，按面分文案：写者面撞顶=整章作废（内容没提交），
    subagent 面的写入即生效、撞顶只是会话收束（已写入的都算数），所以 subagent 面
    不能沿用"本章作废"这句假话，并带上分母让模型自己算还剩几轮。
    2026-10-02 恢复 subagent 面：随章内三子代理路径一并加回（0.2.0 重构曾摘除）。
    """
    if subagent_face:
        if remaining <= 1:
            return (
                "【轮次预算】本轮是本 subagent 内部循环的最后一轮：把该写的记录与 finish 放在"
                "同一批提交（写入写进程序，finish 单独调用即可）；本轮结束仍未写完按会话自然收束"
                "处理——已写入的记录都已生效，未写完的部分留作缺口，不要再发起新的检索。"
            )
        scope = f"{remaining}/{total} 轮" if total else f"{remaining} 轮"
        return (
            f"【轮次预算】剩余 {scope}（含本轮）将触发内部循环上限：请尽快提交已确认内容并调用 "
            "finish 收尾（不要留到下一轮），不要再用新检索消耗轮次。"
        )
    if remaining <= 1:
        return (
            "【轮次预算】本轮是内部循环的最后一轮：写入与收尾放在同一批次提交，"
            "并在本批次里调用 finish ——收尾判定在本批全部调用处理完后执行；"
            "本轮结束仍未收尾则本章作废，不要再发起新的检索。"
        )
    return (
        f"【轮次预算】剩余 {remaining} 轮（含本轮）将触发内部循环上限："
        "请尽快提交已确认内容，把剩余轮次留给写入与 finish 收尾，"
        "不要再用新检索消耗轮次。"
    )


# 2026-09-13 尚无内容领域对应的补齐工具
_MISSING_CONTENT_TOOL_HINTS = {
    "entities": "write_entity（登记本章出现的实体）",
    "metrics": "write_metrics（摘要、叙事指标与段落情绪标签，必填）",
    "events": "write_event（根/子事件与参与者，确实没有事件可跳过）",
    "relations": "write_relation（本章确实没有关系可跳过）",
    "dialogues": "write_dialogue（按候选表逐条判定，确实没有可跳过）",
}


def _missing_domains_reminder(missing: list[str]) -> str | None:
    """2026-09-13 用于构造无工具回复重发前的"还没收尾"提醒

    写入即生效，收尾由唯一 finish 表达：纯文本汇报既不是写入也不是收尾，
    调用层把无工具回复视同调用故障重发，此提醒只注入重发请求（不写入状态消息链、
    不改工具开放与路由），把"还缺什么内容、怎么收尾"直接交给模型。

    2026-09-13 写者面全放开：五个写入工具从首轮起全部在工具面上，缺哪个域就报
    哪个域的补齐工具，不再有"实体未写、其余领域工具随后解锁"的分支。
    2026-09-19 双路径定案：本图服务 agent 路径（单块章，程序面）——模型可见面
    是 [execute_code, finish]，本提醒随 finish 回执注入同一程序面会话。
    """
    ordered = [domain for domain in _DOMAIN_ORDER if domain in missing]
    head = "【收尾提醒】本章还没收尾（纯文本汇报不算写入，也不是收尾）："
    tail = "。确认写完后调用 finish 收尾，本章才冻结；确实为空的领域直接收尾即可。"
    if not ordered:
        return f"{head}请确认已写完并调用 finish 收尾{tail}"
    detail = "、".join(f"{domain}（{_MISSING_CONTENT_TOOL_HINTS[domain]}）" for domain in ordered)
    return f"{head}尚无内容的领域：{detail}{tail}"


def _index_ranges(values: list[int]) -> str:
    """2026-09-14 用于把候选编号列表压成区间文本（1,3,4,5,9 → "1,3-5,9"）"""
    if not values:
        return ""
    parts: list[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def _progress_block(ledger: AnnotationToolLedger, remaining_turns: int, max_iterations: int) -> str:
    """2026-09-14 构造写者面每回合注入的【进度账本】（每回合注入最新进展）

    块内只放**动态状态**（域账本现值+剩余回合）；"已判不重扫、判完即写"等处理规则
    是静态行为合同，2026-09-14 上提 SYSTEM_PROMPT。与收尾提醒同款：只对当次
    请求生效、不写入状态消息链；案例链不注入（09-11 "不注入案例"裁决），只覆盖五个
    写入域。
    """
    work_progress = getattr(ledger, "work_progress", None)
    if callable(work_progress):
        return str(work_progress(remaining_turns, max_iterations))
    lines = [
        "【进度账本】本轮时刻的本章已写入状态，由系统注入。",
        f"剩余回合 {remaining_turns}/{max_iterations}（含本轮）。",
    ]
    entities = ledger.entity_ledger()
    if entities:
        rendered = []
        for row in entities:
            # 大类排在 id 之前：它一经登记不可变更，写错只能被拒（重写实体靠这行回忆）
            extras = [str(row.get("entity_type") or ""), f"id={row['id']}"]
            if row.get("tags"):
                extras.append("标签:" + "、".join(row["tags"]))
            if row.get("aliases"):
                extras.append("别名:" + "、".join(row["aliases"]))
            rendered.append(f"{row['el']}={row['name']}(" + "；".join(item for item in extras if item) + ")")
        lines.append(f"实体({len(entities)})：" + "；".join(rendered))
    else:
        lines.append("实体：未写入")
    relations = ledger.relation_ledger()
    if relations:
        lines.append(f"关系({len(relations)})：" + "；".join(relations))
    else:
        lines.append("关系：未写入")
    trees = ledger.event_ledger()
    if trees:
        parts = []
        for tree_key, entry in trees.items():
            flags = f"伏笔={str(bool(entry['foreshadowing'])).lower()}"
            if entry.get("confidence"):
                flags += f"·confidence={entry['confidence']}"
            children = "，".join(f"{child} {child_type}" for child, child_type in entry["children"].items()) or "无子"
            parts.append(f'{tree_key}="{entry["root"]}"({flags}；children: {children}；主链尾 {entry["trunk_tail"]})')
        lines.append(f"事件树({len(trees)})：" + "；".join(parts))
    else:
        lines.append("事件树：未写入")
    dialogue = ledger.dialogue_ledger()
    pending = _index_ranges(dialogue["pending"]) or "无"
    judged_line = f"对话：已判定 {dialogue['written']}/{dialogue['total']}；未判定编号：{pending}"
    if dialogue["judged"]:
        ordered = sorted(dialogue["judged"].items(), key=lambda kv: int(kv[0]))
        verdicts = "，".join(f"{idx}={value}" for idx, value in ordered)
        judged_line += f"；已判定值：{verdicts}"
    lines.append(judged_line)
    lines.append("指标：已写入" if ledger.metrics_payload is not None else "指标：未写入")
    return "\n".join(lines)
