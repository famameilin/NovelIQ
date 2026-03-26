from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadResponse(BaseModel):
    novel_id: str
    filename: str
    status: str = "uploaded"
    message: str = "文件上传成功"


class AnalyzeResponse(BaseModel):
    novel_id: str
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = "分析任务已启动"


class StatusResponse(BaseModel):
    """
    2026-03-12: Claude修改，添加task_id字段
    """

    novel_id: str
    task_id: str | None = None
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    stage: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EmotionCurvePoint(BaseModel):
    chunk_id: int
    pos_density: float
    neg_density: float
    net_density: float
    smoothed_density: float


class RhythmCurvePoint(BaseModel):
    chunk_id: int
    tension_proxy: float
    tension_composite: float


class CharacterStats(BaseModel):
    name: str
    appearance_count: int
    role_function: str
    avg_emotion_score: float | None = None


class ChunkStyle(BaseModel):
    chunk_id: int
    mtld: float | None = None
    ttr: float | None = None
    avg_sent_len: float | None = None
    d_value: float | None = None
    pause_density: float | None = None
    fight_density: float | None = None
    dialogue_ratio: float | None = None
    sensory_density: float | None = None
    metaphor_density: float | None = None


class ChunkCharacter(BaseModel):
    name: str
    role_function: str | None = None
    action: str | None = None
    emotion_score: str | None = None


class ChunkRelation(BaseModel):
    from_char: str
    to_char: str
    type: str
    change: str


class ChunkDialogue(BaseModel):
    speaker: str | None = None
    length: int | None = None


class ChunkAnnotation(BaseModel):
    chunk_id: int
    emotional_valence: str | None = None
    event_type: str | None = None
    pivot_moment: bool | None = None
    cliffhanger: bool | None = None
    has_foreshadowing: bool | None = None
    foreshadowing_type: str | None = None
    foreshadowing_desc: str | None = None
    characters: list[ChunkCharacter] = []
    relations: list[ChunkRelation] = []
    dialogues: list[ChunkDialogue] = []


class CharacterRelation(BaseModel):
    chunk_id: int
    from_char: str
    to_char: str
    type: str
    change: str


class HierarchicalRelation(BaseModel):
    """
    层级关系模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加层级关系导出到JSON功能
    """

    rel_id: int
    rel_type: str
    first_chunk: int | None = None
    last_chunk: int | None = None
    from_entity: str
    to_entity: str


class GlobalStats(BaseModel):
    total_chunks: int | None = None
    total_chars: int | None = None
    avg_mtld: float | None = None
    avg_ttr: float | None = None
    avg_sent_len: float | None = None
    rhythm_avg: float | None = None
    rhythm_std: float | None = None
    rhythm_max: float | None = None
    rhythm_min: float | None = None
    global_avg_sent_len: float | None = None
    global_avg_ttr: float | None = None


class NarrativeStructureStats(BaseModel):
    act1_ratio: float | None = None
    act2_ratio: float | None = None
    act3_ratio: float | None = None
    climax_spacing: float | None = None
    middle_collapse_index: float | None = None
    event_density: dict[str, float] | None = None
    cliffhanger_rate: float | None = None


class EmotionStats(BaseModel):
    pos_neg_ratio: float | None = None
    positive_ratio: float | None = None
    negative_ratio: float | None = None
    neutral_ratio: float | None = None
    recovery_speed: float | None = None
    pivot_moment_density: float | None = None
    lexical_emotion_trend: str | None = None


class CharacterStatsAggregate(BaseModel):
    network_density: float | None = None
    protagonist_betweenness: float | None = None
    greimas_coverage: float | None = None
    function_coverage_distribution: dict[str, float] | None = None
    antagonist_strength_gap: float | None = None
    relation_change_freq: float | None = None
    degree_centrality: dict[str, float] | None = None


class StyleStats(BaseModel):
    tone_distribution: dict[str, float] | None = None
    vocab_breadth: float | None = None
    avg_word_len: float | None = None
    sent_len_std: float | None = None
    function_word_vector: dict[str, float] | None = None
    category_density: dict[str, float] | None = None


class CultureStats(BaseModel):
    idiom_density: float | None = None
    classical_sentence_ratio: float | None = None
    imagery_density: float | None = None


class ChunkCulture(BaseModel):
    chunk_id: int
    imagery_lexicon_density: float | None = None


class TopicInfo(BaseModel):
    topic_id: int
    words: list[str]
    weight: float


class DiagnosisResult(BaseModel):
    foreshadow_rate: float | None = None
    arc_scores: list[float] | dict[str, float] | None = None
    narrative_type: str | None = None
    topic_labels: list[str] | None = None
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


class NovelResultsResponse(BaseModel):
    novel_id: str
    novel_info: dict[str, Any]
    emotion_curve: list[EmotionCurvePoint]
    rhythm_curve: list[RhythmCurvePoint]
    characters: list[CharacterStats]
    topics: list[TopicInfo]
    diagnosis: DiagnosisResult | None = None
    chunk_styles: list[ChunkStyle] = []
    chunk_annotations: list[ChunkAnnotation] = []
    character_relations: list[CharacterRelation] = []
    global_stats: GlobalStats | None = None
    narrative_structure: NarrativeStructureStats | None = None
    emotion_stats: EmotionStats | None = None
    character_stats: CharacterStatsAggregate | None = None
    style_stats: StyleStats | None = None
    culture_stats: CultureStats | None = None
    chunk_cultures: list[ChunkCulture] = []


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


class ReanalyzeResponse(BaseModel):
    novel_id: str
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = "重新分析任务已启动"


class TaskInfoResponse(BaseModel):
    """
    任务信息响应模型

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    修改内容: 移除 db_path 字段，添加 run_id 字段

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: API接口参数统一优化
    修改内容: 移除 run_id 字段，统一使用 task_id
    """

    task_id: str
    novel_id: str
    status: str
    created_at: datetime | None = None


class TaskListResponse(BaseModel):
    novel_id: str
    tasks: list[TaskInfoResponse]


class BatchDeleteNovelsRequest(BaseModel):
    """
    批量删除小说请求模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能
    """

    novel_ids: list[str] = Field(..., description="要删除的小说ID列表")


class BatchDeleteNovelsResponse(BaseModel):
    """
    批量删除小说响应模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能
    """

    success: bool
    message: str
    deleted_count: int
    failed_count: int
    deleted_ids: list[str]
    failed_ids: list[dict[str, str]]  # [{"novel_id": "xxx", "reason": "错误原因"}]


class BatchDeleteTasksRequest(BaseModel):
    """
    批量删除任务请求模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能
    """

    task_ids: list[str] = Field(..., description="要删除的任务ID列表")


class BatchDeleteTasksResponse(BaseModel):
    """
    批量删除任务响应模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能
    """

    success: bool
    message: str
    deleted_count: int
    failed_count: int
    deleted_ids: list[str]
    failed_ids: list[dict[str, str]]  # [{"task_id": "xxx", "reason": "错误原因"}]


class TokenUsageRecord(BaseModel):
    id: int
    novel_id: str
    chunk_id: int | None = None
    task_type: str
    call_type: str
    model: str
    prompt_tokens: int
    completion_tokens: int | None = None
    total_tokens: int
    created_at: str


class TokenUsageSummary(BaseModel):
    call_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0


class TokenUsageByTask(BaseModel):
    call_count: int
    total_tokens: int


class TokenUsageByModel(BaseModel):
    call_count: int
    total_tokens: int


class TokenUsageStats(BaseModel):
    summary: TokenUsageSummary = TokenUsageSummary()
    by_task: dict[str, TokenUsageByTask] = {}
    by_model: dict[str, TokenUsageByModel] = {}
