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

2026-10-16 全库 3NF 改造：旧 analysis_outputs / annotation_work / event_nodes /
event_edges / dialogue_records(run,chapter,content) 列退场，上列既有 dataclass
名称与字段语义保持不变；另补各正式关系的读投影行（保存记录、work 状态、对话行、
事实行、伏笔边），投影列全部取自冻结 35 表的明确列或确定性读投影。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    role_function: str | None
    action: str | None
    emotion_score: object


@dataclass(frozen=True)
class DialogueFactRow:
    """2026-08-05 用于向对话与情绪融合消费者暴露数据库图对话事实"""

    chapter_id: int
    speaker: list[str]
    speaker_references: list[dict[str, Any]]
    length: int
    tone: str | None


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


@dataclass(frozen=True)
class SavedAnnotationRecord:
    """已保存的正式章节标注读投影（chapter_annotations 宽表 + 标注 work 的章内角色）

    章号/角色不是标注记录列，由真实执行→work（annotation_run/chapter/role）投影；
    段落情绪条目与覆盖告警另从 analysis_assessments 与固定覆盖规则取得。
    """

    record_id: str
    chapter_id: int
    role: str | None
    execution_id: str
    contract_version: str
    chapter_consolidation_version: str
    summary: str | None
    emotional_valence: int | None
    narrative_function: str | None
    pivot_moment: bool | None
    cliffhanger: bool | None
    created_at: datetime
    saved_at: datetime


@dataclass(frozen=True)
class AnnotationWorkRow:
    """标注 work 读投影（work_items 的标注分支 + 真实尝试与保存事实）

    state 沿用原口径：已有正式标注记录为 saved，否则 pending；
    invocation_id 取该 work 最新一次真实尝试的 execution（无尝试为空）。
    """

    work_id: str
    run_id: str
    chapter_id: int
    role: str
    invocation_id: str | None
    state: str
    saved_at: datetime | None


@dataclass(frozen=True)
class DialogueRecordRow:
    """对话记录读投影（dialogue_records + 由创建执行取得的章号与原文切片）

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

    旧 content JSON 退场：形状由事实行自身列表达，chapter_id 由真实生产来源
    投影（标注 work 已决定的章节或独立选章的 effective_chapter_id），
    人物动态观测的实体/角色/动作/情绪从声明的参与者行读取。
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
    """伏笔语义链路读投影（narrative_links 语义形状 + 端点完整事件的来源章号）

    edge_type 沿用原伏笔边取值，source/target 是完整事件身份；来源章号由该
    事件自身证据的段落所属章节投影，is_active/expired_at 只承接真实观察。
    """

    edge_id: str
    edge_type: str
    source_event_id: str | None
    target_event_id: str | None
    source_chapter_id: int | None
    target_chapter_id: int | None
    is_active: bool | None
    expired_at: datetime | None
