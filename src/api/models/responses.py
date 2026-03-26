from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
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
    task_id: Optional[str] = None
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    stage: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


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
    avg_emotion_score: Optional[float] = None


class ChunkStyle(BaseModel):
    chunk_id: int
    mtld: Optional[float] = None
    ttr: Optional[float] = None
    avg_sent_len: Optional[float] = None
    d_value: Optional[float] = None
    pause_density: Optional[float] = None
    fight_density: Optional[float] = None
    dialogue_ratio: Optional[float] = None
    sensory_density: Optional[float] = None
    metaphor_density: Optional[float] = None
    cultural_density: Optional[float] = None


class ChunkCharacter(BaseModel):
    name: str
    role_function: Optional[str] = None
    action: Optional[str] = None
    emotion_score: Optional[str] = None


class ChunkRelation(BaseModel):
    from_char: str
    to_char: str
    type: str
    change: str


class ChunkDialogue(BaseModel):
    speaker: Optional[str] = None
    length: Optional[int] = None


class ChunkAnnotation(BaseModel):
    chunk_id: int
    emotional_valence: Optional[str] = None
    event_type: Optional[str] = None
    pivot_moment: Optional[bool] = None
    cliffhanger: Optional[bool] = None
    has_foreshadowing: Optional[bool] = None
    foreshadowing_type: Optional[str] = None
    foreshadowing_desc: Optional[str] = None
    characters: List[ChunkCharacter] = []
    relations: List[ChunkRelation] = []
    dialogues: List[ChunkDialogue] = []


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
    first_chunk: Optional[int] = None
    last_chunk: Optional[int] = None
    from_entity: str
    to_entity: str


class GlobalStats(BaseModel):
    total_chunks: Optional[int] = None
    total_chars: Optional[int] = None
    avg_mtld: Optional[float] = None
    avg_ttr: Optional[float] = None
    avg_sent_len: Optional[float] = None
    rhythm_avg: Optional[float] = None
    rhythm_std: Optional[float] = None
    rhythm_max: Optional[float] = None
    rhythm_min: Optional[float] = None
    global_avg_sent_len: Optional[float] = None
    global_avg_ttr: Optional[float] = None


class NarrativeStructureStats(BaseModel):
    act1_ratio: Optional[float] = None
    act2_ratio: Optional[float] = None
    act3_ratio: Optional[float] = None
    climax_spacing: Optional[float] = None
    middle_collapse_index: Optional[float] = None
    event_density: Optional[Dict[str, float]] = None
    cliffhanger_rate: Optional[float] = None


class EmotionStats(BaseModel):
    pos_neg_ratio: Optional[float] = None
    positive_ratio: Optional[float] = None
    negative_ratio: Optional[float] = None
    neutral_ratio: Optional[float] = None
    recovery_speed: Optional[float] = None
    pivot_moment_density: Optional[float] = None
    lexical_emotion_trend: Optional[str] = None


class CharacterStatsAggregate(BaseModel):
    network_density: Optional[float] = None
    protagonist_betweenness: Optional[float] = None
    greimas_coverage: Optional[float] = None
    function_coverage_distribution: Optional[Dict[str, float]] = None
    antagonist_strength_gap: Optional[float] = None
    relation_change_freq: Optional[float] = None
    degree_centrality: Optional[Dict[str, float]] = None


class StyleStats(BaseModel):
    tone_distribution: Optional[Dict[str, float]] = None
    vocab_breadth: Optional[float] = None
    avg_word_len: Optional[float] = None
    sent_len_std: Optional[float] = None
    function_word_vector: Optional[Dict[str, float]] = None
    category_density: Optional[Dict[str, float]] = None


class CultureStats(BaseModel):
    idiom_density: Optional[float] = None
    classical_sentence_ratio: Optional[float] = None
    imagery_density: Optional[float] = None


class ChunkCulture(BaseModel):
    chunk_id: int
    imagery_density: Optional[float] = None


class TopicInfo(BaseModel):
    topic_id: int
    words: List[str]
    weight: float


class DiagnosisResult(BaseModel):
    foreshadow_rate: Optional[float] = None
    arc_scores: Optional[Union[List[float], Dict[str, float]]] = None
    narrative_type: Optional[str] = None
    topic_labels: Optional[List[str]] = None
    diagnosis: Optional[str] = None
    value_logic_type: Optional[str] = None
    value_logic_reason: Optional[str] = None
    power_stance_score: Optional[int] = None
    power_stance_reason: Optional[str] = None
    common_people_dignity: Optional[int] = None
    dignity_reason: Optional[str] = None
    cultural_depth_score: Optional[int] = None
    cultural_depth_reason: Optional[str] = None
    narrative_arc_type: Optional[str] = None


class NovelResultsResponse(BaseModel):
    novel_id: str
    novel_info: Dict[str, Any]
    emotion_curve: List[EmotionCurvePoint]
    rhythm_curve: List[RhythmCurvePoint]
    characters: List[CharacterStats]
    topics: List[TopicInfo]
    diagnosis: Optional[DiagnosisResult] = None
    chunk_styles: List[ChunkStyle] = []
    chunk_annotations: List[ChunkAnnotation] = []
    character_relations: List[CharacterRelation] = []
    global_stats: Optional[GlobalStats] = None
    narrative_structure: Optional[NarrativeStructureStats] = None
    emotion_stats: Optional[EmotionStats] = None
    character_stats: Optional[CharacterStatsAggregate] = None
    style_stats: Optional[StyleStats] = None
    culture_stats: Optional[CultureStats] = None
    chunk_cultures: List[ChunkCulture] = []


class ErrorResponse(BaseModel):
    detail: str
    error_type: str
    status_code: int


class ResultsWriteResponse(BaseModel):
    success: bool
    message: str
    file_path: Optional[str] = None
    novel_id: str
    novel_name: Optional[str] = None
    missing_fields: Optional[List[str]] = None


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
    created_at: Optional[datetime] = None


class TaskListResponse(BaseModel):
    novel_id: str
    tasks: List[TaskInfoResponse]


class BatchDeleteNovelsRequest(BaseModel):
    """
    批量删除小说请求模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能
    """

    novel_ids: List[str] = Field(..., description="要删除的小说ID列表")


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
    deleted_ids: List[str]
    failed_ids: List[Dict[str, str]]  # [{"novel_id": "xxx", "reason": "错误原因"}]


class BatchDeleteTasksRequest(BaseModel):
    """
    批量删除任务请求模型

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 新增批量删除功能
    """

    task_ids: List[str] = Field(..., description="要删除的任务ID列表")


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
    deleted_ids: List[str]
    failed_ids: List[Dict[str, str]]  # [{"task_id": "xxx", "reason": "错误原因"}]


class TokenUsageRecord(BaseModel):
    id: int
    novel_id: str
    chunk_id: Optional[int] = None
    task_type: str
    call_type: str
    model: str
    prompt_tokens: int
    completion_tokens: Optional[int] = None
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
    by_task: Dict[str, TokenUsageByTask] = {}
    by_model: Dict[str, TokenUsageByModel] = {}
