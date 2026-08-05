"""
章节级标注 Agent 严格数据合同
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

EmotionalValence = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EventType = Literal["冲突", "铺垫", "转折"]
Confidence = Literal["high", "medium", "low"]
Assertion = Literal["affirmed", "negated"]
FactChangeKind = Literal["assert", "refine", "supersede", "retract"]
RelationChangeKind = Literal["assert", "reinforce", "weaken", "break", "refine", "supersede", "retract"]
Directionality = Literal["directed", "bidirectional"]
CaseState = Literal["active", "consumed", "rejected"]
ForeshadowingType = Literal["物件", "对话", "场景", "人物行为", "其他"]
SetupStatus = Literal["open", "reinforced", "likely_paid_off"]
PayoffLikelihood = Literal["high", "medium"]
SourceKind = Literal["chapter_annotation", "continuity_fact"]

NonEmptyText = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    """2026-08-05 用于统一禁止 Agent 合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", strict=True)


class Evidence(StrictModel):
    """2026-08-05 用于表达全文唯一的章节级结果依据"""

    reason: str = Field(min_length=1)
    chapterid: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_reason(self) -> Evidence:
        """2026-08-05 用于拒绝只含空白字符的 Evidence 理由"""
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("evidence.reason 不能为空")
        return self


class EntityRef(StrictModel):
    """2026-08-05 用于统一表达事实中的实体引用"""

    name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)


class StoryTime(StrictModel):
    """2026-08-05 用于表达结构化故事时间而不混入处理时间"""

    label: str | None = None
    order: int | None = None
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> StoryTime:
        """2026-08-05 用于确保故事时间至少包含一个明确字段"""
        if not self.model_fields_set:
            raise ValueError("story_time 至少需要一个字段")
        return self


class FactParticipant(StrictModel):
    """2026-08-05 用于表达事实参与者及其语义角色"""

    role: str = Field(min_length=1)
    entity: EntityRef


class ChapterSegment(StrictModel):
    """2026-08-05 用于保留章节正式标注中的原始 chunk 锚点"""

    chunk_id: int = Field(ge=0)
    summary: str = Field(min_length=1)
    emotional_valence: EmotionalValence
    event_type: EventType
    pivot_moment: bool = False
    cliffhanger: bool = False


class ChapterFactBase(StrictModel):
    """2026-08-05 用于统一章节原子事实的锚点依据与置信度"""

    chunk_id: int = Field(ge=0)
    evidence: Evidence
    confidence: Confidence


class CharacterFact(ChapterFactBase):
    """2026-08-05 用于表达章节中的人物行为与情绪事实"""

    entity: EntityRef
    role_function: str = Field(min_length=1)
    action: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    emotion: EmotionalValence


class LocationFact(ChapterFactBase):
    """2026-08-05 用于表达实体与地点之间的章节事实"""

    entity: EntityRef
    location: EntityRef
    relation_type: str = Field(min_length=1)


class DialogueFact(ChapterFactBase):
    """2026-08-05 用于表达章节对话及其说话人事实"""

    content: str = Field(min_length=1)
    speaker: EntityRef | None = None
    tone: str | None = None
    is_inner_monologue: bool = False


class EventFact(ChapterFactBase):
    """2026-08-05 用于表达章节事件与参与者"""

    event_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    participants: list[FactParticipant] = Field(default_factory=list)


class RelationFact(ChapterFactBase):
    """2026-08-05 用于表达章节实体关系及变化"""

    from_entity: EntityRef
    to_entity: EntityRef
    relation_type: str = Field(min_length=1)
    change_kind: RelationChangeKind
    directionality: Directionality


class StateFact(ChapterFactBase):
    """2026-08-05 用于表达章节实体状态与时间范围"""

    entity: EntityRef
    predicate: str = Field(min_length=1)
    object: EntityRef | None = None
    value: JsonValue | None = None
    story_time: StoryTime | None = None

    @model_validator(mode="after")
    def validate_object_or_value(self) -> StateFact:
        """2026-08-05 用于确保状态事实在对象和值之间恰好选择一种表达"""
        if (self.object is None) == (self.value is None):
            raise ValueError("state fact 的 object 与 value 必须恰好一个非空")
        return self


class ChapterAnnotation(StrictModel):
    """2026-08-05 用于保存当前完整章节的唯一正式标注候选"""

    chapter_summary: str = Field(min_length=1)
    segments: list[ChapterSegment] = Field(min_length=1)
    characters: list[CharacterFact] = Field(default_factory=list)
    locations: list[LocationFact] = Field(default_factory=list)
    dialogues: list[DialogueFact] = Field(default_factory=list)
    events: list[EventFact] = Field(default_factory=list)
    relations: list[RelationFact] = Field(default_factory=list)
    states: list[StateFact] = Field(default_factory=list)


class ChapterAnnotationPatch(StrictModel):
    """2026-08-05 用于在初始或后文阶段局部修正章节候选"""

    chapter_summary: str | None = None
    segments: list[ChapterSegment] | None = None
    characters: list[CharacterFact] | None = None
    locations: list[LocationFact] | None = None
    dialogues: list[DialogueFact] | None = None
    events: list[EventFact] | None = None
    relations: list[RelationFact] | None = None
    states: list[StateFact] | None = None

    @model_validator(mode="after")
    def validate_non_empty_patch(self) -> ChapterAnnotationPatch:
        """2026-08-05 用于拒绝没有实际提交字段的章节修正"""
        if not self.model_fields_set:
            raise ValueError("revise_finish 至少需要提供一个修正字段")
        return self


class CasePayload(StrictModel):
    """2026-08-05 用于表达需要后续章节继续处理的完整未解决案例"""

    keys: list[str] = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def normalize_and_validate(self) -> CasePayload:
        """2026-08-05 用于清理案例关键词并校验去重后的完整描述"""
        normalized_keys = [key.strip() for key in self.keys]
        if any(not key for key in normalized_keys):
            raise ValueError("case.keys 不允许空字符串")
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValueError("case.keys 不允许重复")
        self.keys = normalized_keys
        self.description = self.description.strip()
        if not self.description:
            raise ValueError("case.description 不能为空")
        return self


class FactPayload(StrictModel):
    """2026-08-05 用于表达可独立发布并投影到数据库图的连续性事实"""

    fact_type: str = Field(min_length=1)
    subject: EntityRef
    predicate: str = Field(min_length=1)
    object: EntityRef | None = None
    value: JsonValue | None = None
    participants: list[FactParticipant] = Field(default_factory=list)
    scope: str = Field(min_length=1)
    story_time: StoryTime | None = None
    assertion: Assertion
    change_kind: FactChangeKind
    linked_fact_id: str | None = None
    confidence: Confidence

    @model_validator(mode="after")
    def validate_fact_change(self) -> FactPayload:
        """2026-08-05 用于校验事实值与版本变化引用合同"""
        if (self.object is None) == (self.value is None):
            raise ValueError("fact 的 object 与 value 必须恰好一个非空")
        if self.change_kind == "assert" and self.linked_fact_id is not None:
            raise ValueError("assert fact 不允许 linked_fact_id")
        if self.change_kind != "assert" and not self.linked_fact_id:
            raise ValueError("事实修订必须提供 linked_fact_id")
        return self


class ForeshadowingPayload(StrictModel):
    """2026-08-05 用于表达已确认伏笔线程的新建或续接结果"""

    has_foreshadowing: Literal[True]
    foreshadowing_type: ForeshadowingType
    setup_kind: str = Field(min_length=1)
    setup_summary: str = Field(min_length=1)
    why_unresolved_now: str = ""
    expected_payoff_family: str = Field(min_length=1)
    payoff_likelihood: PayoffLikelihood
    is_new_setup: bool
    linked_setup_id: str | None = None
    setup_status: SetupStatus
    confidence: Literal["high", "medium"]

    @model_validator(mode="after")
    def validate_setup_link(self) -> ForeshadowingPayload:
        """2026-08-05 用于校验新建与续接伏笔线程的真实 ID 合同"""
        if self.is_new_setup:
            if self.linked_setup_id is not None or self.setup_status != "open":
                raise ValueError("新伏笔必须使用空 linked_setup_id 且状态为 open")
        elif not self.linked_setup_id or self.setup_status == "open":
            raise ValueError("续接伏笔必须提供 linked_setup_id 且状态不能为 open")
        return self


class RejectedPayload(StrictModel):
    """2026-08-05 用于表达来源案例被否定的原因分类"""

    reason_code: str = Field(min_length=1)
    rejected_assumptions: list[str] = Field(default_factory=list)


class PushOutputBase(StrictModel):
    """2026-08-05 用于统一 push 输出的来源案例与唯一 Evidence"""

    source_case_ids: list[str] = Field(default_factory=list)
    evidence: Evidence


class CasePushOutput(PushOutputBase):
    """2026-08-05 用于暂存未解决案例输出"""

    output_kind: Literal["case"]
    payload: CasePayload


class FactPushOutput(PushOutputBase):
    """2026-08-05 用于暂存已解决事实输出"""

    output_kind: Literal["fact"]
    payload: FactPayload


class ForeshadowingPushOutput(PushOutputBase):
    """2026-08-05 用于暂存已确认伏笔输出"""

    output_kind: Literal["foreshadowing"]
    payload: ForeshadowingPayload


class RejectedPushOutput(PushOutputBase):
    """2026-08-05 用于暂存被否定案例输出"""

    output_kind: Literal["rejected"]
    payload: RejectedPayload

    @model_validator(mode="after")
    def validate_sources(self) -> RejectedPushOutput:
        """2026-08-05 用于确保 rejected 始终关联至少一个来源案例"""
        if not self.source_case_ids:
            raise ValueError("rejected 输出必须包含 source_case_ids")
        return self


PushOutput = Annotated[
    CasePushOutput | FactPushOutput | ForeshadowingPushOutput | RejectedPushOutput,
    Field(discriminator="output_kind"),
]


class SearchRequest(StrictModel):
    """2026-08-05 用于约束连续性或后文原文检索输入"""

    query: str = Field(min_length=1, max_length=2000)


class CaseSearchResult(StrictModel):
    """2026-08-05 用于返回可 pull 的活动案例"""

    id: str
    keys: list[str]
    description: str = Field(min_length=1, max_length=100)
    evidence: Evidence
    result_kind: Literal["case"] = "case"
    pullable: Literal[True] = True
    state: CaseState = "active"


class FactSearchResult(StrictModel):
    """2026-08-05 用于返回稳定来源事实 ID 与完整图事实语义"""

    result_kind: Literal["fact"] = "fact"
    fact_id: str
    source_kind: SourceKind
    pullable: Literal[False] = False
    content: dict[str, Any]
    evidence: Evidence


class ForeshadowingSearchResult(StrictModel):
    """2026-08-05 用于返回不可 pull 的真实伏笔线程"""

    result_kind: Literal["foreshadowing"] = "foreshadowing"
    record_id: str
    pullable: Literal[False] = False
    content: dict[str, Any]
    evidence: Evidence


class AfterChunkSearchResult(StrictModel):
    """2026-08-05 用于返回后文检索命中的章节和 chunk 授权锚点"""

    result_kind: Literal["after_chunk"] = "after_chunk"
    chapter_id: int = Field(gt=0)
    chunk_id: int = Field(ge=0)
    excerpt: str


SearchResultItem = Annotated[
    CaseSearchResult | FactSearchResult | ForeshadowingSearchResult | AfterChunkSearchResult,
    Field(discriminator="result_kind"),
]


class SearchResult(StrictModel):
    """2026-08-05 用于返回单次检索的合并结果"""

    results: list[SearchResultItem] = Field(default_factory=list, max_length=50)


class PullRequest(StrictModel):
    """2026-08-05 用于约束本轮接受处理的活动案例集合"""

    ids: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> PullRequest:
        """2026-08-05 用于拒绝重复 pull 同一案例"""
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("pull.ids 不允许重复")
        return self


class PullResult(StrictModel):
    """2026-08-05 用于返回已经进入本轮处理责任的完整案例"""

    cases: list[CaseSearchResult]


class PushRequest(StrictModel):
    """2026-08-05 用于约束一次 push 中的全部运行内候选输出"""

    outputs: list[PushOutput] = Field(min_length=1)


class PushResult(StrictModel):
    """2026-08-05 用于确认候选只进入本轮运行内存"""

    accepted: Literal[True] = True
    staged_count: int = Field(ge=1)


class SuccessAudit(StrictModel):
    """2026-08-05 用于把成功模型与工具审计交给完成事务"""

    attempt_number: int = Field(ge=1, le=3)
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    model_name: str | None = None
    model_provider: str
    duration_ms: int = Field(ge=0)


class TokenUsageRecord(StrictModel):
    """2026-08-05 用于把可信模型 Token 用量交给完成事务"""

    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class AgentRunResult(StrictModel):
    """2026-08-05 用于承载 LangGraph 到达 END 后的完整章节运行结果"""

    run_id: str
    chapter_id: int = Field(gt=0)
    final_annotation: ChapterAnnotation
    initial_finish: ChapterAnnotation
    after_chapter_ids: list[int]
    revision_payload: dict[str, Any]
    initial_case_candidate_ids: list[str]
    rotation_case_ids: list[str]
    pulled_case_ids: list[str]
    staged_outputs: list[PushOutput]
    success_audit: SuccessAudit
    token_usage: list[TokenUsageRecord] = Field(default_factory=list)


class CompletionCase(StrictModel):
    """2026-08-05 用于返回完成事务实际创建或复用的案例"""

    id: str
    keys: list[str]
    description: str
    evidence: Evidence
    state: CaseState


class CompletionFact(StrictModel):
    """2026-08-05 用于返回完成事务实际创建或复用的事实"""

    fact_id: str
    payload: FactPayload
    evidence: Evidence


class CompletionForeshadowing(StrictModel):
    """2026-08-05 用于返回完成事务实际创建或复用的伏笔记录"""

    setup_id: str
    hit_id: int
    payload: ForeshadowingPayload
    evidence: Evidence


class CompletionResult(StrictModel):
    """2026-08-05 用于回读或返回章节唯一完成事务的真实结果"""

    annotation_id: str
    chapter_id: int = Field(gt=0)
    cases: list[CompletionCase] = Field(default_factory=list)
    facts: list[CompletionFact] = Field(default_factory=list)
    foreshadowing: list[CompletionForeshadowing] = Field(default_factory=list)
    rejected_source_case_ids: list[str] = Field(default_factory=list)
    source_case_states: dict[str, CaseState] = Field(default_factory=dict)
