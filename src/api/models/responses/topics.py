"""
主题与诊断响应模型

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（models/responses.py → responses/ 包）
说明: 自 src/api/models/responses.py 拆出主题信息、主题聚合/序列/变化/情感统计、
诊断结果（DiagnosisResult）、通用错误与结果写盘响应模型（§5.8/§5.11 等），
字段与语义保持不变。
"""

from typing import Literal

from pydantic import BaseModel, Field


class TopicInfo(BaseModel):
    topic_id: int
    words: list[str]
    weight: float
    label: str | None = None


class TopicModelMetaInfo(BaseModel):
    """topic_model_runs 契约行的 API 元数据视图（§5.8）"""

    model_key: str
    library_version: str
    pipeline_version: str
    num_topics: int
    artifact_key: str


class TopicDistributionEntry(BaseModel):
    topic_id: int
    weight: float


class TopicAggregateResponse(BaseModel):
    """全书主题分布（§5.11 D1）：sum(w*t)/sum(t)，分母每段一行"""

    run_id: str
    level: Literal["book"] = "book"
    model: TopicModelMetaInfo | None = None
    token_total: int | None = None
    distribution: list[TopicDistributionEntry] | None = None
    unavailable_reason: str | None = None


class ChapterTopicDistribution(BaseModel):
    chapter_id: int
    chapter_sequence: int
    chapter_title: str
    token_total: int | None = None
    distribution: list[TopicDistributionEntry] | None = None


class ChapterTopicAggregateResponse(BaseModel):
    """章节主题分布：按 chapters.sequence 排序，章节分母为该章段落推断 token 和"""

    run_id: str
    level: Literal["chapter"] = "chapter"
    model: TopicModelMetaInfo | None = None
    chapters: list[ChapterTopicDistribution] = Field(default_factory=list)
    unavailable_reason: str | None = None


class TopicSeriesPoint(BaseModel):
    paragraph_id: int
    chapter_id: int
    chapter_sequence: int
    start_position: int
    token_count: int
    weights: list[float]


class TopicSeriesResponse(BaseModel):
    """段落主题序列（D1）：完整 K 维权重，横轴真实字符位置"""

    run_id: str
    model: TopicModelMetaInfo | None = None
    num_topics: int | None = None
    points: list[TopicSeriesPoint] = Field(default_factory=list)
    unavailable_reason: str | None = None


class TopicShiftConfig(BaseModel):
    """主题变化候选版本化配置（D2）"""

    window_size: int
    min_tokens_per_window: int
    score_threshold: float
    max_candidates: int


class TopicShiftCandidate(BaseModel):
    position: int
    paragraph_start: int
    paragraph_end: int
    score: float
    window_token_total: int


class TopicShiftResponse(BaseModel):
    """主题变化候选点（D2）：topic_shift_score 为以 2 为底、范围 [0,1] 的 JS 散度"""

    candidates: list[TopicShiftCandidate] = Field(default_factory=list)
    config: TopicShiftConfig
    unavailable_reason: str | None = None


class TopicEmotionEntry(BaseModel):
    topic_id: int
    emotion: float | None
    weighted_token_total: float | None


class TopicEmotionResponse(BaseModel):
    """主题-情感统计（D3）：sum(w*t*net_density)/sum(w*t)，空值段落双向排除"""

    run_id: str
    model: TopicModelMetaInfo | None = None
    emotion: list[TopicEmotionEntry] = Field(default_factory=list)
    unavailable_reason: str | None = None


class DiagnosisResult(BaseModel):
    foreshadow_expectation: float | None = Field(
        default=None,
        description=("伏笔回收预期，基于 setup thread ledger 加权估算的近似值，取值范围 0-1，不是严格全文事实回收率。"),
    )
    arc_scores: dict[str, float] | None = None
    genre_labels: list[str] | None = None
    style_labels: list[str] | None = None
    topic_labels: dict[str, str] | list[str] | None = None
    emotion_avg: float | None = None
    lexicon_zero_hit_share: float | None = None
    diagnosis: str | None = None
    value_logic_type: str | None = None
    value_logic_reason: str | None = None
    power_stance_score: int | None = None
    power_stance_reason: str | None = None
    common_people_dignity: int | None = None
    dignity_reason: str | None = None
    cultural_depth_score: int | None = None
    cultural_depth_reason: str | None = None
    narrative_arc_type: str | None = None
    focus_structure: Literal["single", "dual", "ensemble"] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    core_cast: list[str] | None = None
    theme_color: str | None = Field(default=None, description="小说主题色，十六进制格式，如 #4A90D9")


class ErrorResponse(BaseModel):
    detail: str
    error_type: str
    status_code: int


class ResultsWriteResponse(BaseModel):
    success: bool
    message: str
    file_path: str | None = None
    novel_id: str
    novel_name: str | None = None
    missing_fields: list[str] | None = None
