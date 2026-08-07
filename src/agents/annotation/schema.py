"""
章节级标注 Agent 严格数据合同
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator

EmotionalValence = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EventType = Literal["冲突", "铺垫", "转折"]
Confidence = Literal["high", "medium", "low"]
Assertion = Literal["affirmed", "negated"]
RelationChangeKind = Literal["assert", "reinforce", "weaken", "break", "refine", "supersede", "retract"]
Directionality = Literal["directed", "bidirectional"]
RelationSemantics = Literal["ordinary", "same_character"]
CaseState = Literal["active", "resolved"]
CaseType = Literal["dialogue_speaker"]
ForeshadowingType = Literal["物件", "对话", "场景", "人物行为", "其他"]
SetupStatus = Literal["open", "reinforced", "likely_paid_off"]
PayoffLikelihood = Literal["high", "medium"]
EntityType = Literal["character", "location", "object", "organization"]

NonEmptyText = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    """2026-08-07 用于统一禁止标注 Agent 合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", strict=True)


class GraphEvidence(StrictModel):
    """2026-08-07 用于引用前序章节图版本中可见的事实版本"""

    fact_id: str = Field(min_length=1)
    fact_revision: int = Field(gt=0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reason(self) -> GraphEvidence:
        """2026-08-07 用于拒绝只含空白字符的图事实依据理由"""
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("graph evidence reason 不能为空")
        return self


class TextEvidence(StrictModel):
    """2026-08-07 用于引用当前章节输入或本轮已读取的同 run 原文"""

    reason: str = Field(min_length=1)
    chunk_id: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_reason(self) -> TextEvidence:
        """2026-08-07 用于拒绝只含空白字符的原文依据理由"""
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("text evidence reason 不能为空")
        return self


Evidence = GraphEvidence | TextEvidence


class EvidenceList(RootModel[list[Evidence]]):
    """2026-08-07 用于把全部业务依据固定为非空双源 Evidence 列表"""

    root: list[Evidence] = Field(min_length=1)

    def __iter__(self):
        """2026-08-07 用于按提交顺序遍历 Evidence 列表"""
        return iter(self.root)

    def __len__(self) -> int:
        """2026-08-07 用于返回 Evidence 列表长度"""
        return len(self.root)

    def __getitem__(self, index: int) -> Evidence:
        """2026-08-07 用于按索引读取 Evidence 列表元素"""
        return self.root[index]


class StoryTime(StrictModel):
    """2026-08-07 用于表达结构化故事时间而不混入处理时间"""

    label: str | None = None
    order: int | None = None
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> StoryTime:
        """2026-08-07 用于确保故事时间至少包含一个明确字段"""
        if not self.model_fields_set:
            raise ValueError("story_time 至少需要一个字段")
        return self


def _validate_endpoint(
    *,
    ref: str | None,
    existing_entity_id: int | None,
    label: str,
    required: bool,
) -> None:
    """2026-08-07 用于校验 finish 实体端点只使用一种定位方式"""
    selected = int(ref is not None) + int(existing_entity_id is not None)
    if required and selected != 1:
        raise ValueError(f"{label} 必须恰好提交 ref 或 existing_entity_id")
    if not required and selected > 1:
        raise ValueError(f"{label} 不能同时提交 ref 与 existing_entity_id")


class TextSpan(StrictModel):
    """2026-08-07 用于稳定定位 current 原文中的实体 mention"""

    chunk_id: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> TextSpan:
        """2026-08-07 用于拒绝倒置或空文本区间"""
        if self.end <= self.start:
            raise ValueError("TextSpan.end 必须大于 start")
        return self


class EntityBase(StrictModel):
    """2026-08-07 用于统一 finish 实体目录的稳定引用与依据"""

    ref: str = Field(min_length=1)
    name: str = Field(min_length=1)
    existing_entity_id: int | None = Field(default=None, gt=0)
    mentions: list[TextSpan] = Field(min_length=1)
    confidence: Confidence
    evidence: EvidenceList

    @model_validator(mode="after")
    def normalize_identity(self) -> EntityBase:
        """2026-08-07 用于规范化实体内部引用和名称"""
        self.ref = self.ref.strip()
        self.name = self.name.strip()
        if not self.ref or not self.name:
            raise ValueError("实体 ref 与 name 不能为空")
        return self


class CharacterEntity(EntityBase):
    """2026-08-07 用于声明当前章节明确出现的人物图节点"""


class LocationEntity(EntityBase):
    """2026-08-07 用于声明当前章节明确出现的地点图节点"""

    location_type: str | None = None
    description: str | None = None


class ObjectEntity(EntityBase):
    """2026-08-07 用于声明当前章节明确出现的物品图节点"""

    object_type: str | None = None
    description: str | None = None


class OrganizationEntity(EntityBase):
    """2026-08-07 用于声明当前章节明确出现的组织图节点"""

    organization_type: str | None = None
    description: str | None = None


class EntityDirectory(StrictModel):
    """2026-08-07 用于保存当前章节全部一等图实体目录"""

    characters: list[CharacterEntity] = Field(default_factory=list)
    locations: list[LocationEntity] = Field(default_factory=list)
    objects: list[ObjectEntity] = Field(default_factory=list)
    organizations: list[OrganizationEntity] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> EntityDirectory:
        """2026-08-07 用于确保实体 ref 和既有节点 ID 在 finish 内唯一"""
        entities = [*self.characters, *self.locations, *self.objects, *self.organizations]
        refs = [entity.ref for entity in entities]
        if len(set(refs)) != len(refs):
            raise ValueError("entities 中的 ref 必须全局唯一")
        existing_ids = [
            entity.existing_entity_id
            for entity in entities
            if entity.existing_entity_id is not None
        ]
        if len(set(existing_ids)) != len(existing_ids):
            raise ValueError("同一个 existing_entity_id 在 finish 中只能声明一次")
        return self


class ChapterMetrics(StrictModel):
    """2026-08-07 用于保存逐 chunk 的情绪与叙事结构指标"""

    emotional_valence: EmotionalValence
    event_type: EventType
    pivot_moment: bool = False
    cliffhanger: bool = False


class ChapterFactBase(StrictModel):
    """2026-08-07 用于统一逐 chunk 标注项的稳定引用依据与置信度"""

    ref: str = Field(min_length=1)
    confidence: Confidence
    evidence: EvidenceList

    @model_validator(mode="after")
    def normalize_ref(self) -> ChapterFactBase:
        """2026-08-07 用于拒绝空白标注项 ref"""
        self.ref = self.ref.strip()
        if not self.ref:
            raise ValueError("标注项 ref 不能为空")
        return self


class CharacterObservation(ChapterFactBase):
    """2026-08-07 用于表达人物在当前 chunk 的功能动作与情绪"""

    entity_ref: str | None = None
    entity_existing_entity_id: int | None = Field(default=None, gt=0)
    role_function: str = Field(min_length=1)
    action: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    emotion: EmotionalValence

    @model_validator(mode="after")
    def validate_entity(self) -> CharacterObservation:
        """2026-08-07 用于确保人物观察端点唯一"""
        _validate_endpoint(
            ref=self.entity_ref,
            existing_entity_id=self.entity_existing_entity_id,
            label="character_observation.entity",
            required=True,
        )
        return self


class LocationObservation(ChapterFactBase):
    """2026-08-07 用于表达地点自身属性与状态"""

    location_ref: str | None = None
    location_existing_entity_id: int | None = Field(default=None, gt=0)
    predicate: str = Field(min_length=1)
    value: JsonValue
    story_time: StoryTime | None = None

    @model_validator(mode="after")
    def validate_location(self) -> LocationObservation:
        """2026-08-07 用于确保地点观察端点唯一"""
        _validate_endpoint(
            ref=self.location_ref,
            existing_entity_id=self.location_existing_entity_id,
            label="location_observation.location",
            required=True,
        )
        return self


class Dialogue(ChapterFactBase):
    """2026-08-07 用于表达当前 chunk 对话及稳定原文锚点"""

    content: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    speaker_ref: str | None = None
    speaker_existing_entity_id: int | None = Field(default=None, gt=0)
    tone: str | None = None
    is_inner_monologue: bool = False

    @model_validator(mode="after")
    def validate_dialogue(self) -> Dialogue:
        """2026-08-07 用于校验对话区间和可空说话人端点"""
        if self.end <= self.start:
            raise ValueError("dialogue.end 必须大于 start")
        _validate_endpoint(
            ref=self.speaker_ref,
            existing_entity_id=self.speaker_existing_entity_id,
            label="dialogue.speaker",
            required=False,
        )
        return self


class EventParticipant(StrictModel):
    """2026-08-07 用于表达事件参与者与语义角色"""

    role: str = Field(min_length=1)
    entity_ref: str | None = None
    entity_existing_entity_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_entity(self) -> EventParticipant:
        """2026-08-07 用于确保事件参与者端点唯一"""
        _validate_endpoint(
            ref=self.entity_ref,
            existing_entity_id=self.entity_existing_entity_id,
            label="event.participant",
            required=True,
        )
        return self


class Event(ChapterFactBase):
    """2026-08-07 用于表达当前 chunk 事件参与者与发生地点"""

    event_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    participants: list[EventParticipant] = Field(default_factory=list)
    location_ref: str | None = None
    location_existing_entity_id: int | None = Field(default=None, gt=0)
    story_time: StoryTime | None = None

    @model_validator(mode="after")
    def validate_location(self) -> Event:
        """2026-08-07 用于校验事件可空地点端点"""
        _validate_endpoint(
            ref=self.location_ref,
            existing_entity_id=self.location_existing_entity_id,
            label="event.location",
            required=False,
        )
        return self


class Relation(ChapterFactBase):
    """2026-08-07 用于表达当前 chunk 实体关系及关系版本变化"""

    from_ref: str | None = None
    from_existing_entity_id: int | None = Field(default=None, gt=0)
    to_ref: str | None = None
    to_existing_entity_id: int | None = Field(default=None, gt=0)
    relation_type: str = Field(min_length=1)
    change_kind: RelationChangeKind
    relation_id: str | None = None
    directionality: Directionality = "directed"
    relation_semantics: RelationSemantics = "ordinary"
    representative_ref: str | None = None
    representative_existing_entity_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_relation(self) -> Relation:
        """2026-08-07 用于校验关系端点版本引用和同一人物代表节点"""
        _validate_endpoint(
            ref=self.from_ref,
            existing_entity_id=self.from_existing_entity_id,
            label="relation.from",
            required=True,
        )
        _validate_endpoint(
            ref=self.to_ref,
            existing_entity_id=self.to_existing_entity_id,
            label="relation.to",
            required=True,
        )
        if self.change_kind == "assert":
            if self.relation_id is not None:
                raise ValueError("assert 关系不允许提交 relation_id")
        elif not self.relation_id:
            raise ValueError("非 assert 关系必须提交本轮图搜索可见的 relation_id")
        inactive = self.change_kind in {"break", "retract"}
        if self.relation_semantics == "ordinary":
            if self.representative_ref is not None or self.representative_existing_entity_id is not None:
                raise ValueError("普通关系不允许提交 representative")
            return self
        if self.directionality != "bidirectional":
            raise ValueError("same_character 关系必须使用 bidirectional")
        if inactive:
            if self.representative_ref is not None or self.representative_existing_entity_id is not None:
                raise ValueError("断开 same_character 关系时不允许提交 representative")
        else:
            _validate_endpoint(
                ref=self.representative_ref,
                existing_entity_id=self.representative_existing_entity_id,
                label="relation.representative",
                required=True,
            )
        return self


class State(ChapterFactBase):
    """2026-08-07 用于表达当前 chunk 实体状态与时间范围"""

    entity_ref: str | None = None
    entity_existing_entity_id: int | None = Field(default=None, gt=0)
    predicate: str = Field(min_length=1)
    object_ref: str | None = None
    object_existing_entity_id: int | None = Field(default=None, gt=0)
    value: JsonValue | None = None
    story_time: StoryTime | None = None
    assertion: Assertion = "affirmed"

    @model_validator(mode="after")
    def validate_state(self) -> State:
        """2026-08-07 用于校验状态主体与对象值互斥"""
        _validate_endpoint(
            ref=self.entity_ref,
            existing_entity_id=self.entity_existing_entity_id,
            label="state.entity",
            required=True,
        )
        object_selected = self.object_ref is not None or self.object_existing_entity_id is not None
        if object_selected:
            _validate_endpoint(
                ref=self.object_ref,
                existing_entity_id=self.object_existing_entity_id,
                label="state.object",
                required=True,
            )
        if object_selected == (self.value is not None):
            raise ValueError("state 的 object 与 value 必须恰好一个非空")
        return self


class Foreshadowing(ChapterFactBase):
    """2026-08-07 用于表达当前 chunk 可确认的伏笔事实"""

    foreshadowing_type: ForeshadowingType
    setup_kind: str = Field(min_length=1)
    setup_summary: str = Field(min_length=1)
    why_unresolved_now: str = ""
    expected_payoff_family: str = Field(min_length=1)
    payoff_likelihood: PayoffLikelihood
    is_new_setup: bool
    linked_setup_id: str | None = None
    setup_status: SetupStatus

    @model_validator(mode="after")
    def validate_setup_link(self) -> Foreshadowing:
        """2026-08-07 用于校验新建与续接伏笔线程的真实 ID 合同"""
        if self.is_new_setup:
            if self.linked_setup_id is not None or self.setup_status != "open":
                raise ValueError("新伏笔必须使用空 linked_setup_id 且状态为 open")
        elif not self.linked_setup_id or self.setup_status == "open":
            raise ValueError("续接伏笔必须提供 linked_setup_id 且状态不能为 open")
        return self


class ChapterChunkFinish(StrictModel):
    """2026-08-07 用于保存单个 current chunk 的完整标注"""

    chunk_id: int = Field(ge=0)
    summary: str = Field(min_length=1)
    metrics: ChapterMetrics
    character_observations: list[CharacterObservation]
    location_observations: list[LocationObservation]
    dialogues: list[Dialogue]
    events: list[Event]
    relations: list[Relation]
    states: list[State]
    foreshadowings: list[Foreshadowing]

    @model_validator(mode="after")
    def validate_unique_refs(self) -> ChapterChunkFinish:
        """2026-08-07 用于确保单个 chunk 内标注项 ref 唯一"""
        facts = [
            *self.character_observations,
            *self.location_observations,
            *self.dialogues,
            *self.events,
            *self.relations,
            *self.states,
            *self.foreshadowings,
        ]
        refs = [fact.ref for fact in facts]
        if len(set(refs)) != len(refs):
            raise ValueError(f"chunk {self.chunk_id} 中的标注项 ref 必须唯一")
        return self


class ChunkCoverage(StrictModel):
    """2026-08-07 用于声明单个 current chunk 的全部领域均已检查"""

    chunk_id: int = Field(ge=0)
    entities: Literal[True]
    character_observations: Literal[True]
    location_observations: Literal[True]
    dialogues: Literal[True]
    events: Literal[True]
    relations: Literal[True]
    states: Literal[True]
    foreshadowings: Literal[True]


class ChapterFinish(StrictModel):
    """2026-08-07 用于保存当前章节唯一正式完整标注"""

    chapter_summary: str = Field(min_length=1)
    entities: EntityDirectory
    chunks: list[ChapterChunkFinish] = Field(min_length=1)
    coverage: list[ChunkCoverage] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_global_refs(self) -> ChapterFinish:
        """2026-08-07 用于确保全部 chunk 标注项 ref 在 finish 内全局唯一"""
        refs = [
            fact.ref
            for chunk in self.chunks
            for fact in [
                *chunk.character_observations,
                *chunk.location_observations,
                *chunk.dialogues,
                *chunk.events,
                *chunk.relations,
                *chunk.states,
                *chunk.foreshadowings,
            ]
        ]
        if len(set(refs)) != len(refs):
            raise ValueError("ChapterFinish 中的标注项 ref 必须全局唯一")
        return self


class EntityDirectoryPatch(StrictModel):
    """2026-08-07 用于按实体 ref 局部新增修改或删除目录项"""

    upsert_characters: list[CharacterEntity] | None = None
    upsert_locations: list[LocationEntity] | None = None
    upsert_objects: list[ObjectEntity] | None = None
    upsert_organizations: list[OrganizationEntity] | None = None
    remove_refs: list[str] | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> EntityDirectoryPatch:
        """2026-08-07 用于拒绝没有实体变更的目录补丁"""
        if not self.model_fields_set:
            raise ValueError("entities patch 至少需要一个字段")
        return self


class ChunkFinishPatch(StrictModel):
    """2026-08-07 用于按 chunk_id 和标注项 ref 局部修正 finish"""

    chunk_id: int = Field(ge=0)
    summary: str | None = None
    metrics: ChapterMetrics | None = None
    upsert_character_observations: list[CharacterObservation] | None = None
    upsert_location_observations: list[LocationObservation] | None = None
    upsert_dialogues: list[Dialogue] | None = None
    upsert_events: list[Event] | None = None
    upsert_relations: list[Relation] | None = None
    upsert_states: list[State] | None = None
    upsert_foreshadowings: list[Foreshadowing] | None = None
    remove_refs: list[str] | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> ChunkFinishPatch:
        """2026-08-07 用于拒绝只有定位字段的 chunk 补丁"""
        if self.model_fields_set == {"chunk_id"}:
            raise ValueError("chunk patch 至少需要一个修正字段")
        return self


class ChapterFinishPatch(StrictModel):
    """2026-08-07 用于按 ref 对当前完整 finish 执行局部修正"""

    chapter_summary: str | None = None
    entities: EntityDirectoryPatch | None = None
    chunks: list[ChunkFinishPatch] | None = None
    coverage: list[ChunkCoverage] | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> ChapterFinishPatch:
        """2026-08-07 用于拒绝没有实际提交字段的 finish 修正"""
        if not self.model_fields_set:
            raise ValueError("revise_finish 至少需要提供一个修正字段")
        return self


class SearchRequest(StrictModel):
    """2026-08-07 用于约束连续性或原文检索输入"""

    query: str = Field(min_length=1, max_length=2000)


class CaseSearchResult(StrictModel):
    """2026-08-07 用于返回可解决的活动案例"""

    id: str = Field(min_length=1)
    type: CaseType
    chunkid: int = Field(ge=0)
    keys: list[str] = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=100)
    evidence: EvidenceList
    result_kind: Literal["case"] = "case"
    pullable: Literal[True] = True
    state: Literal["active"] = "active"


class ActiveCaseDetails(CaseSearchResult):
    """2026-08-07 用于在工具后端携带不暴露给 Agent 的稳定案例目标"""

    target_key: str = Field(min_length=1)
    target_ref: dict[str, Any]


class GraphSearchFact(StrictModel):
    """2026-08-07 用于返回可构造 GraphEvidence 的事实版本"""

    fact_id: str
    fact_revision: int = Field(gt=0)
    fact_type: str
    predicate: str
    effective_chunk_id: int = Field(ge=0)
    content: dict[str, Any]
    evidence: EvidenceList


class GraphSearchEntity(StrictModel):
    """2026-08-07 用于返回目标章节截止位置的实体完整状态"""

    existing_entity_id: int = Field(gt=0)
    name: str
    entity_type: EntityType
    state_revision: int = Field(ge=0)
    state: dict[str, Any] = Field(default_factory=dict)


class GraphSearchRelation(StrictModel):
    """2026-08-07 用于返回目标章节截止位置的有效稳定关系"""

    relation_id: str
    relation_revision: int = Field(gt=0)
    from_entity_id: int = Field(gt=0)
    to_entity_id: int = Field(gt=0)
    from_name: str
    to_name: str
    relation_type: str
    directionality: Directionality
    relation_semantics: RelationSemantics
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class GraphSearchResult(StrictModel):
    """2026-08-07 用于返回上一已完成章节的事实实体关系和有限路径"""

    result_kind: Literal["graph"] = "graph"
    pullable: Literal[False] = False
    graph_version_id: str
    facts: list[GraphSearchFact] = Field(default_factory=list)
    entities: list[GraphSearchEntity] = Field(default_factory=list)
    relations: list[GraphSearchRelation] = Field(default_factory=list)
    paths: list[list[str]] = Field(default_factory=list)


class ForeshadowingSearchResult(StrictModel):
    """2026-08-07 用于返回不可 pull 的真实伏笔线程"""

    result_kind: Literal["foreshadowing"] = "foreshadowing"
    record_id: str
    pullable: Literal[False] = False
    content: dict[str, Any]
    evidence: EvidenceList


SearchResultItem = Annotated[
    CaseSearchResult | ForeshadowingSearchResult,
    Field(discriminator="result_kind"),
]


class SearchResult(StrictModel):
    """2026-08-07 用于返回案例池与伏笔线程检索结果"""

    results: list[SearchResultItem] = Field(default_factory=list, max_length=50)


class TextSearchResult(StrictModel):
    """2026-08-07 用于返回原文定位候选而不把搜索结果当作 Evidence"""

    result_kind: Literal["text"] = "text"
    chapter_id: int = Field(gt=0)
    chunk_id: int = Field(ge=0)
    excerpt: str
    keyword_score: float = Field(ge=0)
    semantic_score: float | None = None


class ResolutionEntity(StrictModel):
    """2026-08-07 用于表达案例解决结果中的实体描述"""

    name: str = Field(min_length=1)
    entity_type: Literal["character"]

    @model_validator(mode="after")
    def normalize_name(self) -> ResolutionEntity:
        """2026-08-07 用于拒绝空白解决实体名称"""
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("resolution speaker.name 不能为空")
        return self


class DialogueSpeakerResolution(StrictModel):
    """2026-08-07 用于严格确认历史对话说话人"""

    speaker: ResolutionEntity
    evidence_chunkid: int = Field(ge=0)


class PullRequest(StrictModel):
    """2026-08-07 用于提交单个已确认案例的严格解决结果"""

    case_id: str = Field(min_length=1)
    type: Literal["dialogue_speaker"]
    resolution: DialogueSpeakerResolution


class PulledResult(PullRequest):
    """2026-08-07 用于保存运行内已确认案例及原稳定目标"""

    target_key: str = Field(min_length=1)
    target_ref: dict[str, Any]


class PushCase(StrictModel):
    """2026-08-07 用于提交当前章节新发现且仍未解决的案例"""

    description: str = Field(min_length=1, max_length=100)
    keys: list[str] = Field(min_length=1, max_length=20)
    type: CaseType
    chunkid: int = Field(ge=0)

    @model_validator(mode="after")
    def normalize_case(self) -> PushCase:
        """2026-08-07 用于规范化案例描述关键词并拒绝重复"""
        self.description = unicodedata.normalize("NFC", self.description).strip()
        normalized_keys = [unicodedata.normalize("NFC", key).strip() for key in self.keys]
        if not self.description or any(not key for key in normalized_keys):
            raise ValueError("push description 和 keys 不能为空")
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValueError("push keys 不允许重复")
        self.keys = normalized_keys
        return self


class CaseTargetAnchor(StrictModel):
    """2026-08-07 用于保存 push 在 current 原文中定位的稳定目标锚点"""

    chunk_id: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> CaseTargetAnchor:
        """2026-08-07 用于拒绝倒置的案例目标区间"""
        if self.end <= self.start:
            raise ValueError("case target end 必须大于 start")
        return self


class StagedPushCase(PushCase):
    """2026-08-07 用于保存工具阶段尚未绑定 finish ref 的案例"""

    target_key: str = Field(min_length=1)
    target_anchor: CaseTargetAnchor


class PushedCase(StagedPushCase):
    """2026-08-07 用于保存已绑定最终 finish 标注项的案例"""

    target_ref: dict[str, Any]


class PushResult(StrictModel):
    """2026-08-07 用于确认单个案例只进入本轮运行内存"""

    accepted: Literal[True] = True
    target_key: str = Field(min_length=1)


class PullResult(StrictModel):
    """2026-08-07 用于确认单个案例解决结果只进入本轮运行内存"""

    accepted: Literal[True] = True
    case_id: str = Field(min_length=1)


class SuccessAudit(StrictModel):
    """2026-08-07 用于保存成功模型与工具调用审计"""

    attempt_number: int = Field(ge=1, le=3)
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    model_name: str | None = None
    model_provider: str
    duration_ms: int = Field(ge=0)


class TokenUsageRecord(StrictModel):
    """2026-08-07 用于保存可信模型 Token 用量"""

    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class AgentRunAudit(StrictModel):
    """2026-08-07 用于承载不参与业务读取的运行审计数据"""

    allow_future_context: bool
    initial_finish: ChapterFinish
    revision_payloads: list[dict[str, Any]]
    initial_case_candidate_ids: list[str]
    rotation_case_ids: list[str]
    authorized_text_chunk_ids: list[int]
    visible_graph_fact_refs: list[tuple[str, int]]
    visible_graph_entity_ids: list[int]
    visible_graph_relation_ids: list[str]
    success: SuccessAudit
    token_usage: list[TokenUsageRecord] = Field(default_factory=list)


class AgentRunResult(StrictModel):
    """2026-08-07 用于承载章节 Agent 到达 END 后的正式业务结果"""

    run_id: str
    chapter_id: int = Field(gt=0)
    finish: ChapterFinish
    pulled_results: list[PulledResult]
    pushed_cases: list[PushedCase]
    audit: AgentRunAudit


class CompletionCase(StrictModel):
    """2026-08-07 用于返回完成事务实际创建的活动案例"""

    id: str
    type: CaseType
    chunkid: int = Field(ge=0)
    keys: list[str]
    description: str
    target_ref: dict[str, Any]
    evidence: EvidenceList
    state: CaseState


class CompletionPulledResult(StrictModel):
    """2026-08-07 用于返回完成事务实际写入的案例解决事实版本"""

    case_id: str
    type: CaseType
    resolution: DialogueSpeakerResolution
    target_fact_id: str
    target_fact_revision: int = Field(gt=0)


class CompletionResult(StrictModel):
    """2026-08-07 用于回读或返回章节唯一完成事务的真实结果"""

    annotation_id: str
    graph_version_id: str
    chapter_id: int = Field(gt=0)
    pushed_cases: list[CompletionCase] = Field(default_factory=list)
    pulled_results: list[CompletionPulledResult] = Field(default_factory=list)
