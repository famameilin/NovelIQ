"""
API 响应模型包

说明: 读侧响应模型（任务与小说域 DTO 留在 src/api/models/tasks.py）
原 src/api/models/responses.py 按资源域拆分为 tasks/curves/chapters/stats/
topics/linguistic/entities 子模块；本包全量 re-export 原有公开名，
`from src.api.models.responses import X` 与 `from src.api.models.responses.xxx import X`
两种导入方式均可使用，现有导入方零改动。
"""

from src.api.models.responses.chapters import (
    BookAggregateStats,
    ChapterAnnotation,
    ChapterCharacter,
    ChapterDialogue,
    ChapterMetricsResponse,
    ChapterMetricSummary,
    ChapterRelation,
    ForeshadowingTreeResponse,
)
from src.api.models.responses.curves import (
    EmotionTrendWindow,
    ParagraphCurvePoint,
)
from src.api.models.responses.entities import (
    CharacterRelation,
    EntityCandidate,
    HierarchicalRelation,
    LinguisticEntitiesResponse,
    LinguisticPhrasesResponse,
    PosCentroidEntry,
    PosCoverageEntry,
    Word2VecModelInfo,
    Word2VecStatsResponse,
)
from src.api.models.responses.linguistic import (
    ChapterLinguisticStats,
    EmotionEventHolderCount,
    EmotionEventPredicateCount,
    LinguisticFeaturesResponse,
    LinguisticGroupStats,
)
from src.api.models.responses.stats import (
    CharacterStats,
    CharacterStatsAggregate,
    EmotionStats,
    GlobalStats,
    NarrativeStructureStats,
    StyleStats,
    TokenUsageByModel,
    TokenUsageByTask,
    TokenUsageStats,
    TokenUsageSummary,
)
from src.api.models.responses.topics import (
    ChapterTopicAggregateResponse,
    ChapterTopicDistribution,
    DiagnosisResult,
    ErrorResponse,
    ResultsWriteResponse,
    TopicAggregateResponse,
    TopicDistributionEntry,
    TopicEmotionEntry,
    TopicEmotionResponse,
    TopicInfo,
    TopicModelMetaInfo,
    TopicSeriesPoint,
    TopicSeriesResponse,
    TopicShiftCandidate,
    TopicShiftConfig,
    TopicShiftResponse,
)

__all__ = [
    "BookAggregateStats",
    "ChapterAnnotation",
    "ChapterCharacter",
    "ChapterDialogue",
    "ChapterLinguisticStats",
    "ChapterMetricSummary",
    "ChapterMetricsResponse",
    "ChapterRelation",
    "ChapterTopicAggregateResponse",
    "ChapterTopicDistribution",
    "CharacterRelation",
    "CharacterStats",
    "CharacterStatsAggregate",
    "DiagnosisResult",
    "EmotionStats",
    "EmotionTrendWindow",
    "EmotionEventHolderCount",
    "EmotionEventPredicateCount",
    "EntityCandidate",
    "ErrorResponse",
    "ForeshadowingTreeResponse",
    "GlobalStats",
    "HierarchicalRelation",
    "LinguisticEntitiesResponse",
    "LinguisticFeaturesResponse",
    "LinguisticGroupStats",
    "LinguisticPhrasesResponse",
    "NarrativeStructureStats",
    "ParagraphCurvePoint",
    "PosCentroidEntry",
    "PosCoverageEntry",
    "ResultsWriteResponse",
    "StyleStats",
    "TokenUsageByModel",
    "TokenUsageByTask",
    "TokenUsageStats",
    "TokenUsageSummary",
    "TopicAggregateResponse",
    "TopicDistributionEntry",
    "TopicEmotionEntry",
    "TopicEmotionResponse",
    "TopicInfo",
    "TopicModelMetaInfo",
    "TopicSeriesPoint",
    "TopicSeriesResponse",
    "TopicShiftCandidate",
    "TopicShiftConfig",
    "TopicShiftResponse",
    "Word2VecModelInfo",
    "Word2VecStatsResponse",
]
