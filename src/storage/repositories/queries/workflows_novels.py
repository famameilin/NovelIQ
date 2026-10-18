"从 src/workflows/novels.py 分离的具名物理读取"

from __future__ import annotations

from src.storage.models import Novel


def workflows_novels_delete_novel_1(_session, novel_id):
    return _session.get(Novel, novel_id)
