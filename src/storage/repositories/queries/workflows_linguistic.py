"从 src/workflows/linguistic.py 分离的具名物理读取"

from __future__ import annotations

from typing import cast

from sqlalchemy import bindparam, update
from sqlalchemy.sql.schema import Table as SaTable

from src.storage.models import ParagraphMetric


def workflows_linguistic_apply_mneg_correction_1(_session, params):
    metric_table = cast(SaTable, ParagraphMetric.__table__)
    statement = (
        update(metric_table)
        .where(
            metric_table.c.run_id == bindparam("b_run_id"), metric_table.c.paragraph_id == bindparam("b_paragraph_id")
        )
        .values(positive_weight_sum=bindparam("b_pos"), negative_weight_sum=bindparam("b_neg"))
    )
    return _session.execute(statement, params, execution_options={"synchronize_session": False}).rowcount
