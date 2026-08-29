"""分析流水线阶段进度常量（原 settings.json progress 段，2026-08-28 常量化）"""

from __future__ import annotations

#: 各阶段完成时的累计进度百分比；阶段起点=上一阶段完成点，preprocess 起点=0
STAGE_PROGRESS_MILESTONES: dict[str, float] = {
    "preprocess": 10.0,
    "annotate": 75.0,
    "linguistic": 80.0,
    "aggregate": 90.0,
    "topic_model": 95.0,
    "diagnose": 100.0,
}
