"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from src.storage import Storage


def is_linguistic_complete(session: Storage, run_id: str) -> bool:
    """恢复任务只复用覆盖全部段落的语言完成事实，不能把首批数据当作阶段完成

    完成事实是 paragraph_metrics.linguistic_completed_at 非空（不靠词元行数
    推断）：零词元段落同样有完成行（零词元≠未处理）。
    """
    row = session.reads.linguistic_completion_is_linguistic_complete_1(run_id)
    return row["total"] > 0 and row["completed"] == row["total"]
