"""
语言结构响应模型

LinguisticGroupStats → ChapterLinguisticStats → LinguisticFeaturesResponse 继承链，
与情绪事件计数模型同文件维护，字段与语义保持一致。
"""

from pydantic import BaseModel, Field


class EmotionEventHolderCount(BaseModel):
    """情绪事件持有者计数（sdp AGT）"""

    holder: str
    event_count: int
    positive_count: int
    negative_count: int


class EmotionEventPredicateCount(BaseModel):
    """情绪事件谓词计数"""

    predicate: str
    polarity: str
    event_count: int


class LinguisticGroupStats(BaseModel):
    """书/章聚合的守恒比例与充分统计量；语言阶段未运行时字段为空"""

    token_total: int | None = None
    sentence_total: int | None = None
    word_length_ratios: dict[str, float] | None = None
    pos_ratios: dict[str, float] | None = None
    sentence_pattern_ratios: dict[str, float] | None = None
    avg_dependency_depth: float | None = None
    max_dependency_depth: int | None = None
    dependency_relation_ratios: dict[str, float] | None = None
    dependency_root_count: int | None = None
    # LTP sdp 情绪事件与 mNEG 修正对照（可加计数，比例查询时算）
    emotion_event_count: int | None = None
    emotion_pos_event_count: int | None = None
    emotion_neg_event_count: int | None = None
    emotion_negated_event_count: int | None = None
    lexicon_pos_count: float | None = None
    lexicon_neg_count: float | None = None
    mneg_pos_count: float | None = None
    mneg_neg_count: float | None = None
    # 句级监督边界（按书边界；标签不足/类别单一时为 null）
    boundary_pos_score_sum: float | None = None
    boundary_neg_score_sum: float | None = None


class ChapterLinguisticStats(LinguisticGroupStats):
    chapter_id: int


class LinguisticFeaturesResponse(LinguisticGroupStats):
    """词性/词长/句式/依存聚合（书级字段 + 章节序列）"""

    run_id: str
    paragraph_count: int = 0
    chapters: list[ChapterLinguisticStats] = Field(default_factory=list)
    unavailable_reason: str | None = None
    # 书级情绪事件明细聚合（人物 × 事件计数等）
    emotion_event_density: float | None = None
    emotion_event_holders: list[EmotionEventHolderCount] = Field(default_factory=list)
    emotion_top_predicates: list[EmotionEventPredicateCount] = Field(default_factory=list)
    mneg_net_delta: float | None = None
    lexicon_net: float | None = None
    mneg_net: float | None = None
