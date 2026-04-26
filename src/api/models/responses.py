from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadResponse(BaseModel):
    novel_id: str
    filename: str
    status: str = "uploaded"
    message: str = "文件上传成功"


class CreateTaskResponse(BaseModel):
    """
    创建并启动任务响应

    创建时间: 2026-04-19
    创建者: Codex (GPT-5)
    任务: task-api-decouple
    说明: 对应 POST /api/novels/{novel_id}/tasks。
    """

    novel_id: str
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = "分析任务已创建并启动"


class ResumeTaskResponse(BaseModel):
    """
    继续任务响应

    创建时间: 2026-04-19
    创建者: Codex (GPT-5)
    任务: task-api-decouple
    说明: 对应 POST /api/novels/{novel_id}/tasks/{task_id}/resume。
    """

    novel_id: str
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = "分析任务已继续执行"


class StatusResponse(BaseModel):
    """
    2026-03-12: Claude修改，添加task_id字段

    2026-04-07: TraeAI修改，添加详细进度字段
    任务: implement-task-cancellation
    说明: 添加 sub_stage, current, total, message, llm_outputs 字段，
          使 HTTP 轮询也能返回详细进度信息，与 WebSocket 行为一致
    """

    novel_id: str
    task_id: str | None = None
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    stage: str | None = None
    sub_stage: str | None = None
    current: int | None = None
    total: int | None = None
    message: str | None = None
    llm_outputs: list[str] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ChunkCurvePoint(BaseModel):
    chunk_id: int
    pos_density: float | None = None
    neg_density: float | None = None
    net_density: float | None = None
    smoothed_density: float | None = None
    tension_proxy: float | None = None
    tension_composite: float | None = None
    surface_tension: float | None = None


class CharacterStats(BaseModel):
    """
    角色统计模型

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: 扩展角色统计字段
    说明: 初始模型包含 name, appearance_count, role_function, avg_emotion_score

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: 扩展角色统计字段
    修改内容:
      - 将 role_function 重命名为 dominant_role_function
      - 新增 role_function_distribution 字段
      - 新增 dominant_role_ratio 字段
      - 新增 protagonist_score 字段
      - 新增 is_protagonist 字段

    """

    name: str
    appearance_count: int
    dominant_role_function: str
    role_function_distribution: dict[str, int] = Field(default_factory=dict)
    dominant_role_ratio: float = 0.0
    protagonist_score: float | None = None
    is_protagonist: bool | None = None
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
    imagery_lexicon_density: float | None = None


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
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: ChunkAnnotation 新增字段

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: speaker 改为 list[str] 支持多人同时说话
    """

    speaker: list[str] | None = None
    length: int | None = None


class ChunkAnnotation(BaseModel):
    chunk_id: int
    emotional_valence: str | None = None
    event_type: str | None = None
    pivot_moment: bool | None = None
    cliffhanger: bool | None = None
    has_foreshadowing: bool | None = Field(
        default=None,
        description=(
            "当前 chunk 是否包含伏笔元素。"
            "这是分块级存在性标记，不等于全书伏笔回收预期，"
            "更不是严格全文事实回收率。"
        ),
    )
    is_strong_setup: bool | None = Field(
        default=None,
        description="当前伏笔判断是否已经通过强伏笔门槛筛选，用于前端后续展示高精度 setup。",
    )
    foreshadowing_type: str | None = None
    setup_kind: str | None = None
    foreshadowing_desc: str | None = None
    setup_summary: str | None = None
    why_unresolved_now: str | None = None
    expected_payoff_family: str | None = None
    payoff_likelihood: str | None = None
    linked_setup_id: str | None = None
    characters: list[ChunkCharacter] = []
    relations: list[ChunkRelation] = []
    dialogues: list[ChunkDialogue] = []


class ForeshadowingThreadResponse(BaseModel):
    """
    Setup thread 结果视图。

    创建时间: 2026-04-26
    修改者: Codex
    任务: phase2-setup-pool
    说明: 提供 setup ledger 的稳定 API 响应模型，供诊断 drill-down 和结果导出复用。
    """

    setup_id: str
    first_chunk_id: int
    last_chunk_id: int
    anchor_chunk_ids: list[int] = []
    setup_summary: str
    setup_kind: str
    expected_payoff_family: str
    payoff_likelihood: str
    strength: str
    status: str
    active: bool
    latest_reason: str | None = None
    latest_why_unresolved_now: str | None = None


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
    """
    叙事结构统计模型

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: 叙事时间轴功能设计评估
    修改内容: 新增多高潮剖面字段 (climax_count, climax_positions, climax_heights, peak_escalation, dominant_climax_pos)
    """

    act1_ratio: float | None = None
    act2_ratio: float | None = None
    act3_ratio: float | None = None
    climax_spacing: float | None = None
    middle_collapse_index: float | None = None
    event_density: dict[str, float] | None = None
    cliffhanger_rate: float | None = None
    climax_count: int | None = None
    climax_positions: list[float] | None = None
    climax_heights: list[float] | None = None
    peak_escalation: str | None = None
    dominant_climax_pos: float | None = None


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
    dialogue_ratio: float | None = None
    avg_sent_len: float | None = None
    function_word_vector: dict[str, float] | None = None
    category_density: dict[str, float] | None = None


class TopicInfo(BaseModel):
    topic_id: int
    words: list[str]
    weight: float
    label: str | None = None


class DiagnosisResult(BaseModel):
    foreshadow_expectation: float | None = Field(
        default=None,
        description=(
            "伏笔回收预期，基于 setup thread ledger 加权估算的近似值，"
            "取值范围 0-1，不是严格全文事实回收率。"
        ),
    )
    arc_scores: dict[str, float] | None = None
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
    protagonist: str | None = None
    main_characters: list[str] | None = None
    core_cast: list[str] | None = None
    theme_color: str | None = Field(default=None, description="小说主题色，十六进制格式，如 #4A90D9")


class NovelResultsResponse(BaseModel):
    novel_id: str
    novel_info: dict[str, Any]
    chunk_curves: list[ChunkCurvePoint] = []
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
    accounting_method: Literal["estimated"] = "estimated"
    coverage_status: Literal["complete", "partial"] = "complete"


class TokenUsageByTask(BaseModel):
    call_count: int
    total_tokens: int


class TokenUsageByModel(BaseModel):
    call_count: int
    total_tokens: int


class TokenUsageStats(BaseModel):
    summary: TokenUsageSummary = Field(default_factory=TokenUsageSummary)
    by_task: dict[str, TokenUsageByTask] = Field(default_factory=dict)
    by_call_type: dict[str, TokenUsageByTask] = Field(default_factory=dict)
    by_model: dict[str, TokenUsageByModel] = Field(default_factory=dict)
    coverage_gaps: list[str] = Field(default_factory=list)
