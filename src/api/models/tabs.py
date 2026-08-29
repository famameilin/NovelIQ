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

from pydantic import BaseModel, Field

from src.api.models.graph import KeywordItem
from src.api.models.responses import (
    ChapterTopicDistribution,
    TopicDistributionEntry,
    TopicInfo,
    TopicModelMetaInfo,
)


class TopicsOverviewTabResponse(BaseModel):
    """主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词一次拉取

    - topics/distribution/chapters 缺模型契约行时为空且 unavailable_reason 非空
    - keywords 口径独立于 LDA（TextRank），不可用原因单独回显
    """

    run_id: str
    model: TopicModelMetaInfo | None = None
    topics: list[TopicInfo] = Field(default_factory=list)
    distribution: list[TopicDistributionEntry] | None = None
    chapters: list[ChapterTopicDistribution] = Field(default_factory=list)
    keywords: list[KeywordItem] = Field(default_factory=list)
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
    unavailable_reason 为实体侧原因，短语统计恒有计数语义。
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
