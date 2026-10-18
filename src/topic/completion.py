"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from src.storage import Storage


def is_topic_model_complete(session: Storage, run_id: str) -> bool:
    """LDA 构建事实、每段终态与完整 K 维分布齐备后，才能在恢复时跳过主题阶段

    inference_paragraph_count 是读取投影（complete 状态的正式聚合），
    与下面的 complete 计数同源，实际门禁仍在"每段完整 K 维分布"。
    """
    model = session.paragraphs.fetch_topic_model_run(run_id)
    if model is None:
        return False
    row = session.reads.topic_completion_is_topic_model_complete_1(model, run_id)
    return (
        row["total"] > 0
        and row["settled"] == row["total"]
        and row["complete"] == row["full_distributions"] == model.inference_paragraph_count
    )
