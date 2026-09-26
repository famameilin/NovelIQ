"""Tab 级聚合响应模型（前端每 tab 一个 API）

切片原则：
- 每个 tab 端点只返回该 tab 展示所需的数据；
- 指标类数据一律为服务端聚合后的复合数据，底层原始行（如实体候选
  span 明细）不出现在 tab 响应中，展示主体（LLM 报告/图快照/伏笔线程）
  按展示对象原样透传；
- 沿用仓库事实标准：run_id + 溯源块 + unavailable_reason 三件套，
  不做统一 envelope。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.api.models.graph import GraphMetricsResponse, GraphSnapshotResponse, KeywordItem
from src.api.models.responses import (
    ChapterMetricsResponse,
    ChapterTopicDistribution,
    CharacterStats,
    CharacterStatsAggregate,
    DiagnosisResult,
    EmotionStats,
    EmotionTrendWindow,
    NarrativeStructureStats,
    ParagraphCurvePoint,
    StyleStats,
    TopicDistributionEntry,
    TopicInfo,
    TopicModelMetaInfo,
)


class TopicsOverviewTabResponse(BaseModel):
    """主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词 + 诊断主题标签

    - topics/distribution/chapters 缺模型契约行时为空且 unavailable_reason 非空
    - keywords 口径独立于 LDA（TextRank），不可用原因单独回显
    - topic_labels 为诊断切片（LLM 主题命名，按 topic_id 顺序对齐 topics）
    """

    run_id: str
    model: TopicModelMetaInfo | None = None
    topics: list[TopicInfo] = Field(default_factory=list)
    distribution: list[TopicDistributionEntry] | None = None
    chapters: list[ChapterTopicDistribution] = Field(default_factory=list)
    keywords: list[KeywordItem] = Field(default_factory=list)
    topic_labels: list[str] | None = None
    unavailable_reason: str | None = None
    keyword_unavailable_reason: str | None = None


class EntitySurfaceCount(BaseModel):
    """高频实体名聚合（surface_text + 归一类型 group-by 计数）"""

    surface_text: str
    entity_type: str
    count: int


class LinguisticEntitiesTabResponse(BaseModel):
    """实体与短语 tab：实体类型计数 + 高频实体名 + 固定短语统计

    不含实体候选 span 明细（paragraph_id/字符区间），仅回聚合统计；
    unavailable_reason 表示语言阶段不可用；已运行但没有实体候选时仍展示短语统计。
    """

    run_id: str
    count_by_type: dict[str, int] = Field(default_factory=dict)
    surface_top: list[EntitySurfaceCount] = Field(default_factory=list)
    total_char_count: int = 0
    metric_hit_count: int = 0
    fixed_phrase_density: float | None = None
    four_char_candidate_count: int = 0
    total_hits: int = 0
    unavailable_reason: str | None = None


class DashboardTabResponse(BaseModel):
    """仪表盘 tab：原有 8 个并发请求合并为一次拉取

    各 section 复用既有端点的响应模型；情绪趋势固定全书窗口 20 段。
    """

    run_id: str
    narrative_structure: NarrativeStructureStats | None = None
    emotion_stats: EmotionStats | None = None
    character_stats: CharacterStatsAggregate | None = None
    style_stats: StyleStats | None = None
    chapter_metrics: ChapterMetricsResponse | None = None
    topics: list[TopicInfo] = Field(default_factory=list)
    diagnosis: DiagnosisResult | None = None
    emotion_trend: list[EmotionTrendWindow] = Field(default_factory=list)


class RhythmTabResponse(BaseModel):
    """节奏张力 tab：段落曲线（max_points 展示降采样）+ 叙事结构高潮参数"""

    run_id: str
    curves: list[ParagraphCurvePoint] = Field(default_factory=list)
    narrative_structure: NarrativeStructureStats | None = None


class CharacterFunctionTabResponse(BaseModel):
    """功能与焦点 tab：角色功能分布 + 诊断焦点结构切片

    characters 沿用 /characters 的别名归并与焦点对齐口径。
    """

    run_id: str
    characters: list[CharacterStats] = Field(default_factory=list)
    focus_structure: Literal["single", "dual", "ensemble"] | None = None
    focus_characters: list[str] | None = None
    arc_scores: dict[str, float] | None = None


class CharacterAppearance(BaseModel):
    """图谱页登场次数切片（仅 name + appearance_count）"""

    name: str
    appearance_count: int


class GraphNetworkTabResponse(BaseModel):
    """关系图谱/快照概览 tab：图快照 + 登场次数 + 图算法指标 + 变化总数

    - snapshot/graph_metrics 各自缺失时为 None 并回显 unavailable_reason，
      不以空快照伪造；
    - change_total 为图谱变化总条数（供快照概览计数，不回变化明细）。
    """

    run_id: str
    snapshot: GraphSnapshotResponse | None = None
    character_appearances: list[CharacterAppearance] = Field(default_factory=list)
    graph_metrics: GraphMetricsResponse | None = None
    change_total: int = 0
    unavailable_reason: str | None = None
