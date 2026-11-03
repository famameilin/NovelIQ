"""案例会话的领取批量与事件案例树身份"""

import re

CASE_SESSION_CLAIM_BATCH = 4


def event_case_tree_id(description: str) -> str | None:
    """从事件案例说明中取正式树身份，非事件案例返回 None"""
    match = re.search(r"事件树\s+([0-9a-f-]{36})", description)
    return match.group(1) if match else None
