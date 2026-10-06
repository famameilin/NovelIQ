"""当前 work 会话的临近轮次上限提醒"""

from __future__ import annotations


def _turn_budget_reminder(remaining: int, *, total: int | None = None) -> str:
    """提醒只属于本次请求；是否保存由角色必需产物和显式 finish 决定"""
    if remaining <= 1:
        return (
            "【轮次预算】本轮是当前 work 内部循环的最后一轮：把已确认记录与 finish 放在"
            "同一批提交。只有通过角色校验的 finish 才能保存；未成功收尾的 work 将失败并由"
            "队列决定是否重试，不要再发起新的检索。"
        )
    scope = f"{remaining}/{total} 轮" if total else f"{remaining} 轮"
    return (
        f"【轮次预算】剩余 {scope}（含本轮）将触发内部循环上限：请尽快提交已确认内容并调用 "
        "finish 收尾（不要留到下一轮），不要再用新检索消耗轮次。"
    )
