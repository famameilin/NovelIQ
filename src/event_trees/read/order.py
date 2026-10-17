"""正式事件的文档位置，供投影、连续性订正和读模型统一使用

2026-10-16 全库 3NF 改造（35 表冻结结构）：章级声明不再有 JSON payload 序号列，
同记录事件的写入次序由声明行的真实创建时间与真实 EL 本地地址给出
（不从命令哈希推断顺序）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def formal_event_ordinals(declarations: Iterable[Any]) -> dict[str, int]:
    """同记录声明按真实创建时间与本地地址排序，不虚构写入序号"""
    rows = sorted(
        declarations,
        key=lambda row: (
            str(getattr(row, "created_at", "") or ""),
            getattr(row, "local_key", "") or "",
            getattr(row, "declaration_id", ""),
        ),
    )
    return {row.declaration_id: ordinal for ordinal, row in enumerate(rows)}
