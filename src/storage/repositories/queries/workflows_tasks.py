"从 src/workflows/tasks.py 分离的具名物理读取"

from __future__ import annotations

from src.storage.models import Novel


def workflows_tasks_require_novel_1(_session, novel_id):
    return _session.get(Novel, novel_id)
