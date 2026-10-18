"正式事件的文档位置，供投影、连续性订正和读模型统一使用"

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def formal_event_ordinals(declarations: Iterable[Any]) -> dict[str, int]:
    "同记录声明按真实创建时间与本地地址排序，不虚构写入序号"
    rows = sorted(
        declarations,
        key=lambda row: (
            str(getattr(row, "created_at", "") or ""),
            getattr(row, "local_key", "") or "",
            getattr(row, "declaration_id", ""),
        ),
    )
    return {row.declaration_id: ordinal for ordinal, row in enumerate(rows)}
