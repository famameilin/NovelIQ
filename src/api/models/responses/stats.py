"""
聚合统计响应模型

说明: 自 src/api/models/responses.py 拆出角色统计、叙事结构/情感/风格统计、
全书波动统计与 token 用量统计响应模型，字段与语义保持不变。
"""

from typing import Literal

from pydantic import BaseModel, Field


class CharacterStats(BaseModel):
    """
    角色统计模型

    说明: 初始模型包含 name, appearance_count, role_function, avg_emotion_score
    """

    name: str
    appearance_count: int
    dominant_role_function: str
    role_function_distribution: dict[str, int] = Field(default_factory=dict)
    dominant_role_ratio: float = 0.0
    narrative_focus_score: float | None = None
    is_focus_character: bool = False
    avg_emotion_score: float | None = None


class GlobalStats(BaseModel):
    total_chapters: int | None = None
    total_chars: int | None = None
    avg_mtld: float | None = None
    avg_ttr: float | None = None
    avg_sent_len: float | None = None
    emotion_avg: float | None = None
    emotion_std: float | None = None
    emotion_max: float | None = None
    emotion_min: float | None = None
    rhythm_avg: float | None = None
    rhythm_std: float | None = None
    rhythm_max: float | None = None
    rhythm_min: float | None = None
    # 2026-09-05 A2：词典情绪零信号段落字符加权占比（lexicon 覆盖缺口审计）
    lexicon_zero_hit_share: float | None = None


class NarrativeStructureStats(BaseModel):
    """
    叙事结构统计模型

    2026-08-14 重命名（§13.3）：event_density → chapter_narrative_function_share，
    值语义不变（章节 Agent 标签占比，不再是“事件密度”）
    """

    act1_ratio: float | None = None
    act2_ratio: float | None = None
    act3_ratio: float | None = None
    climax_spacing: float | None = None
    middle_collapse_index: float | None = None
    chapter_narrative_function_share: dict[str, float] | None = None
    cliffhanger_rate: float | None = None
    climax_count: int | None = None
    climax_positions: list[float] | None = None
    climax_heights: list[float] | None = None
    peak_escalation: str | None = None
    dominant_climax_pos: float | None = None


class EmotionStats(BaseModel):
    lexical_pos_neg_ratio: float | None = None
    arc_delta: float | None = None
    positive_ratio: float | None = None
    negative_ratio: float | None = None
    neutral_ratio: float | None = None
    recovery_speed: float | None = None
    chapter_pivot_rate: float | None = None
    lexical_emotion_trend: str | None = None


class CharacterStatsAggregate(BaseModel):
    network_density: float | None = None
    greimas_coverage: float | None = None
    function_coverage_distribution: dict[str, float] | None = None
    antagonist_strength_gap: float | None = None
    relation_change_per_10k_chars: float | None = None
    degree_centrality: dict[str, float] | None = None


class StyleStats(BaseModel):
    tone_distribution: dict[str, float] | None = None
    string_token_diversity: float | None = None
    avg_word_len: float | None = None
    sent_len_std: float | None = None
    dialogue_ratio: float | None = None
    avg_sent_len: float | None = None
    function_word_vector: dict[str, float] | None = None
    category_density: dict[str, float] | None = None


class TokenUsageSummary(BaseModel):
    call_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    accounting_method: Literal["reported", "estimated", "unknown"] = "unknown"
    coverage_status: Literal["recorded_calls", "partial", "unknown"] = "unknown"
    coverage_scope: str = "实际审计请求及已记录的非 Agent 调用；未记录链路不能推断完整"


class TokenUsageByTask(BaseModel):
    """单个任务/调用类型/模型的 token 用量（三者同一形状，共用本模型）"""

    call_count: int
    total_tokens: int


TokenUsageByModel = TokenUsageByTask


class TokenUsageStats(BaseModel):
    summary: TokenUsageSummary = Field(default_factory=TokenUsageSummary)
    by_task: dict[str, TokenUsageByTask] = Field(default_factory=dict)
    by_call_type: dict[str, TokenUsageByTask] = Field(default_factory=dict)
    by_model: dict[str, TokenUsageByModel] = Field(default_factory=dict)
    coverage_gaps: list[str] = Field(default_factory=list)
