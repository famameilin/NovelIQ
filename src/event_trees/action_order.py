"""伏笔动作统一按正文披露位置归并，调用顺序只用于同位置的稳定排列"""

from src.storage.models.foreshadowing_action import ForeshadowingAction


def action_order(action: ForeshadowingAction) -> tuple[int, int, int, int, str]:
    positions = [
        (item["paragraph_id"], item.get("char_start", 0))
        for item in action.evidence
        if action.evidence_scope == "paragraph" and "paragraph_id" in item
    ]
    paragraph, start = min(positions, default=(2**31, 0))
    return action.chapter_order, paragraph, start, action.operation_order, action.action_id
