"""
章节标注读侧行/视图 dataclass

供标注读取与 API/results 消费者使用的具名读投影。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ChapterAnnotationRow:
    """向章节消费者暴露章节 segment 的具名读模型"""

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
    # 非埋设章挂树时指向伏笔树根（埋设事件 id）
    foreshadowing_root_event_id: str | None = None
    # 冻结时系统覆盖告警
    coverage_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CharacterFactRow:
    """向人物与聚合消费者暴露数据库图人物事实"""

    chapter_id: int
    name: str
    surface_name: str
    reference_kind: str
    reference_slot: str | None
    resolved_global_name: str
    global_skip_reason: str | None
    role_function: str | None
    action: str | None
    emotion_score: object


@dataclass(frozen=True)
class DialogueFactRow:
    """向对话与情绪融合消费者暴露数据库图对话事实"""

    chapter_id: int
    speaker: list[str]
    speaker_references: list[dict[str, Any]]
    length: int
    tone: str | None


@dataclass(frozen=True)
class ForeshadowingTreeView:
    """向 API 与诊断暴露伏笔树汇总视图（伏笔即事件树）"""

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


@dataclass(frozen=True)
class SavedAnnotationRecord:
    """已保存的正式章节标注读投影（agent_annotations 宽表自带章号与角色）

    章号/角色是标注记录自身列（写入时归属），段落情绪条目与覆盖告警
    另从 agent_assessments 与固定覆盖规则取得。
    """

    record_id: str
    chapter_id: int
    role: str | None
    agent_id: str
    summary: str | None
    emotional_valence: int | None
    narrative_function: str | None
    pivot_moment: bool | None
    cliffhanger: bool | None
    created_at: datetime
    saved_at: datetime


@dataclass(frozen=True)
class AnnotationRoleRecord:
    """章内标注角色读投影（agent_annotations 产物行 + 真实执行号）

    state：已有正式标注记录为 saved，否则 pending；
    invocation_id 即产物行的真实执行号，saved_at 是保存时间。
    """

    run_id: str
    chapter_id: int
    role: str
    invocation_id: str
    state: str
    saved_at: datetime | None


@dataclass(frozen=True)
class DialogueRecordRow:
    """对话记录读投影（graph_dialogues + 由创建执行取得的章号与原文切片）

    content 按章节正文 [start_char, end_char) 精确切片，不从文档字段读取。
    """

    dialogue_id: str
    chapter_id: int
    candidate_key: str
    start_char: int
    end_char: int
    content: str
    speaker_entity_id: str | None
    tone: str | None
    is_inner_monologue: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class GraphFactRow:
    """图贡献事实读投影（graph_facts 行 + 章节与人物动态观测的具名列）

    形状由事实行自身列表达，chapter_id 由真实生产来源投影（标注 work 决定的
    章节或独立选章的 effective_chapter_id），人物动态观测的实体/角色/动作/情绪
    从声明的参与者行读取。
    """

    fact: Any
    chapter_id: int | None
    operation_order: int | None
    participant_entity_id: str | None = None
    participant_entity_name: str | None = None
    participant_entity_type: str | None = None
    participant_role: str | None = None
    participant_narrative_role: str | None = None
    participant_action: str | None = None
    participant_emotion: int | None = None


@dataclass(frozen=True)
class ForeshadowingEdgeRow:
    """伏笔语义链路读投影（event_links 语义形状 + 端点完整事件的来源章号）

    edge_type 为伏笔边取值，source/target 是完整事件身份；来源章号由该事件
    自身证据的段落所属章节投影，is_active/expired_at 只承接真实观察。
    """

    edge_id: str
    edge_type: str
    source_event_id: str | None
    target_event_id: str | None
    source_chapter_id: int | None
    target_chapter_id: int | None
    is_active: bool | None
    expired_at: datetime | None
