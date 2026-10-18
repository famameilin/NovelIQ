"""诊断受控标签词表

诊断结果 genre_labels / style_labels 字段的取值域（闭集）。词表随契约走——
agent 侧校验（src/agents/diagnosis/schema.py）与 api 读侧归一
（src/api/services/results_queries/diagnosis.py）共用这一份，不各写一套。
"""

from __future__ import annotations

GENRE_LABEL_VALUES: tuple[str, ...] = ("科幻", "悬疑", "历史", "仙侠", "玄幻", "都市", "通用")
STYLE_LABEL_VALUES: tuple[str, ...] = (
    "硬核",
    "史诗",
    "哲思",
    "严肃",
    "黑暗",
    "慢热",
    "高概念",
    "实验性",
    "热血",
    "轻松",
    "寓言性",
    "冷峻",
    "权谋",
    "爽文",
)
