"workflows preprocess 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import Run


def workflows_preprocess_generate_paragraph_embeddings_1(_session, run_id):
    return _session.execute(select(Run.novelid).where(Run.id == run_id)).scalar_one_or_none()
