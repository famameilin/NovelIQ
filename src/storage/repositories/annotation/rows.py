"""
章节标注读侧行/视图 dataclass

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 annotation/repository.py 提取行/视图模型
（原 34-99 行）
说明: 纯结构搬移，不改字段与行为；ChapterAnnotationRow/
CharacterFactRow/DialogueFactRow/ForeshadowingTreeView 供标注读取
与 API/results 消费者使用。repository.py 与 annotation/__init__.py
保留 re-export，导入方零改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChapterAnnotationRow:
    """2026-08-05 用于向 章节消费者暴露章节 segment 的具名读模型"""

    chapter_id: int
    emotional_valence: int
    event_type: str
    pivot_moment: bool
    cliffhanger: bool
    has_foreshadowing: bool | None = None
    is_strong_setup: bool | None = None
    foreshadowing_desc: str | None = None
    why_unresolved_now: str | None = None
    payoff_likelihood: str | None = None
    # 2026-09-13 伏笔入森林：非埋设章挂树时指向伏笔树根（埋设事件 id）
    foreshadowing_root_event_id: str | None = None
    # 2026-09-05 A1：冻结时系统覆盖告警（旧 payload 无此字段时为空）
    coverage_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CharacterFactRow:
    """2026-08-05 用于向人物与聚合消费者暴露数据库图人物事实"""

    chapter_id: int
    name: str
    surface_name: str
    reference_kind: str
    reference_slot: str | None
    resolved_global_name: str
    global_skip_reason: str | None
    role_function: str
    action: str
    emotion_score: object


@dataclass(frozen=True)
class DialogueFactRow:
    """2026-08-05 用于向对话与情绪融合消费者暴露数据库图对话事实"""

    chapter_id: int
    speaker: list[str]
    speaker_references: list[dict[str, Any]]
    length: int
    tone: str | None
    formal_value: dict[str, Any] = field(default_factory=dict)
    continuity_value: dict[str, Any] = field(default_factory=dict)
    continuity_state: str | None = None
    cutoff_hash: str | None = None


@dataclass(frozen=True)
class ForeshadowingTreeView:
    """2026-09-13 用于向 API 与诊断暴露伏笔树汇总视图（伏笔即事件树）"""

    root_event_id: str
    tree_id: str
    first_chapter_id: int
    last_chapter_id: int
    anchor_chapter_ids: list[int]
    description: str
    payoff_likelihood: str | None
    strength: str | None
    status: str
    active: bool
    latest_reason: str | None
    latest_why_unresolved_now: str | None
