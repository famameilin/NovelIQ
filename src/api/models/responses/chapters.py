"""章节级响应模型：章节指标汇总、章节标注（人物/关系/对话）与伏笔树结果视图"""

from typing import Any

from pydantic import BaseModel, Field


class StyleMetricBlock(BaseModel):
    """风格与密度指标块：章节汇总与全书聚合共用同一批字段"""

    total_chars: int
    total_tokens: int
    pos_density: float | None = None
    neg_density: float | None = None
    net_density: float | None = None
    fight_density: float | None = None
    exclaim_per_100_chars: float | None = None
    question_per_100_chars: float | None = None
    pause_per_100_chars: float | None = None
    dialogue_ratio: float | None = None
    avg_sent_len: float | None = None
    sent_len_std: float | None = None
    ttr: float | None = None
    mtld: float | None = None


class ChapterMetricSummary(StyleMetricBlock):
    """章节汇总（由段落充分统计量聚合）"""

    chapter_id: int
    paragraph_count: int
    narrative_function: str | None = None
    pivot_moment: bool | None = None
    cliffhanger: bool | None = None
    emotional_valence: int | None = None


class BookAggregateStats(StyleMetricBlock):
    """全书聚合"""

    total_chapters: int
    total_paragraphs: int
    chapter_narrative_function_share: dict[str, float] = Field(default_factory=dict)
    chapter_pivot_rate: float | None = None
    chapter_cliffhanger_rate: float | None = None
    chapter_emotional_valence_share: dict[int, float] = Field(default_factory=dict)


class ChapterMetricsResponse(BaseModel):
    """章节指标响应（章节汇总 + 全书聚合）"""

    chapters: list[ChapterMetricSummary] = Field(default_factory=list)
    book: BookAggregateStats


class ChapterCharacter(BaseModel):
    name: str
    surface_name: str | None = None
    reference_kind: str | None = None
    reference_slot: str | None = None
    resolved_global_name: str | None = None
    global_skip_reason: str | None = None
    role_function: str | None = None
    action: str | None = None
    emotion_score: str | None = None


class ChapterRelation(BaseModel):
    from_char: str
    to_char: str
    from_reference_kind: str | None = None
    to_reference_kind: str | None = None
    resolved_from_global_name: str | None = None
    resolved_to_global_name: str | None = None
    reference_skip_reason: str | None = None
    type: str
    change: str


class ChapterDialogue(BaseModel):
    speaker: list[str] | None = None
    speaker_references: list[dict[str, Any]] = []
    length: int | None = None


class ChapterAnnotation(BaseModel):
    chapter_id: int
    emotional_valence: int | None = None
    event_type: str | None = None
    pivot_moment: bool | None = None
    cliffhanger: bool | None = None
    has_foreshadowing: bool | None = Field(
        default=None,
        description=("本章 是否包含伏笔元素。这是分块级存在性标记，不等于全书伏笔回收预期，更不是严格全文事实回收率。"),
    )
    is_strong_setup: bool | None = Field(
        default=None,
        description="当前伏笔树根是否强伏笔（strength=high），用于前端后续展示高精度伏笔。",
    )
    foreshadowing_desc: str | None = None
    why_unresolved_now: str | None = None
    payoff_likelihood: str | None = None
    # 非埋设章挂树时指向伏笔树根（埋设事件 id）
    foreshadowing_root_event_id: str | None = None
    # 冻结时系统覆盖告警（如对话候选>0但载荷为空）
    coverage_warnings: list[str] = []
    characters: list[ChapterCharacter] = []
    relations: list[ChapterRelation] = []
    dialogues: list[ChapterDialogue] = []


class ForeshadowingTreeResponse(BaseModel):
    """伏笔树结果视图（伏笔即事件树），供诊断 drill-down 和结果导出复用"""

    root_event_id: str
    tree_id: str
    first_chapter_id: int
    last_chapter_id: int
    anchor_chapter_ids: list[int] = []
    description: str
    payoff_likelihood: str | None
    strength: str | None
    status: str
    active: bool
    latest_reason: str | None = None
    latest_why_unresolved_now: str | None = None
