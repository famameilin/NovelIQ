from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EmotionalValence = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EmotionScore = EmotionalValence
EventType = Literal["冲突", "铺垫", "转折"]
ForeshadowingType = Literal["causal", "thematic"]
ForeshadowingConfidence = Literal["high", "medium", "low"]
DisambigConfidence = Literal["low", "medium", "high"]
RoleFunction = Literal["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
RelationType = Literal["师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从", "友情"]
RelationChange = Literal["强化", "弱化", "新建", "断裂", "无变化"]
ProjectionStatus = Literal["pending", "projected", "failed"]
Directionality = Literal["directed", "symmetric"]
EntityType = Literal["character", "group", "organization", "creature", "artifact"]
ClueType = Literal[
    "none",
    "self_introduction",
    "named_by_other",
    "alias_revealed",
    "appearance_desc",
    "unique_body_marker",
    "kinship_identity",
    "naming_scene",
]
ActionType = Literal["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]
LocationType = Literal["room", "building", "area"]


class LocationAppearance(BaseModel):
    """
    地点出场信息数据结构

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: implement-location-entity-type
    说明: 用于 Phase1 标注阶段识别的地点信息
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    raw_name: str
    location_type: LocationType | None = None


class CharacterAppearance(BaseModel):
    """
    角色出场信息数据结构

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: fix-annotation-disambiguation-issues
    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel
    """

    model_config = ConfigDict(frozen=True)

    raw_name: str
    identity_clue: str
    clue_type: str


class CharacterSnapshot(BaseModel):
    """
    角色快照数据结构

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel
    """

    model_config = ConfigDict(frozen=True)

    name: str
    role_function: str
    action: str
    action_type: str
    emotion_score: str


class RelationChangeSnapshot(BaseModel):
    """
    关系变化快照数据结构

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel
    """

    model_config = ConfigDict(frozen=True)

    from_name: str
    to_name: str
    type: RelationType
    change: RelationChange
    evidence: str
    confidence: float
    source_model: str | None = None
    projection_status: ProjectionStatus = "pending"
    projected_at: str | None = None
    projection_error: str | None = None
    directionality: Directionality = "directed"


class DialogueSnapshot(BaseModel):
    """
    对话快照数据结构

    修改时间: 2026-03-16
    创建者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 添加对话内容字段以支持对话长度计算
    修改内容: 添加 content 字段存储对话内容

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 添加 tone 字段存储对话语气类型

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 添加 evidence 字段，便于追溯未知说话者的判断依据

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 添加 identity_clue 字段，存储 Phase 3 提取的身份线索

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: speaker 改为 list[str] 支持多人同时说话，删除 evidence 字段
    """

    model_config = ConfigDict(frozen=True)

    speaker: list[str] | None = None
    content: str = ""
    tone: str | None = None
    identity_clue: str | None = None


class ForeshadowingResult(BaseModel):
    """
    伏笔分析结果数据结构

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel
    """

    model_config = ConfigDict(frozen=True)

    has_foreshadowing: bool = Field(
        description="当前文本块是否存在伏笔元素。这是单个 chunk 的存在性判断，不表示全书伏笔兑现程度。"
    )
    foreshadowing_type: str | None = None
    anchor_text: str = ""
    anchor_reason: str = ""
    confidence: str

    def to_dict(self) -> dict:
        return {
            "has_foreshadowing": self.has_foreshadowing,
            "foreshadowing_type": self.foreshadowing_type,
            "anchor_text": self.anchor_text,
            "anchor_reason": self.anchor_reason,
            "confidence": self.confidence,
        }


class QuoteCandidate(BaseModel):
    """
    正则提取阶段的候选结构

    创建时间: 2026-03-23
    创建者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    说明: 用于存储正则提取的引号候选及其上下文

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: cleanup-phase3-ctx-context
    修改内容: 移除 ctx_before 和 ctx_after 字段，LLM 有完整 chunk_text 不需要上下文
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="候选序号（1开始）")
    content: str | None = Field(default=None, description="引号内的文字（可为空，从 candidates 匹配获取）")


class DialogueRecordSchema(BaseModel):
    """
    LLM 结构化输出用的 Schema，不包含 content（content 从 candidates 获取）

    创建时间: 2026-04-09
    创建者: TraeAI
    任务: fix-phase3-content-field
    说明: 避免 LLM 返回多余带引号的 content，减少 token 消耗
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="候选序号（1开始）")
    is_dialogue: bool = Field(description="是否为真实对话")
    speaker: list[str] | None = Field(default=None, description="说话人列表，支持多人同时说话，无法确定为 null")
    tone: str | None = Field(default=None, description="语气：强硬/温和/讽刺/恳求/命令/恐惧/惊慌")
    is_inner_monologue: bool = Field(default=False, description="是否为内心独白")
    identity_clue: str | None = Field(default=None, description="身份线索（如自报身份、称呼关系、别名揭示等）")


class DialogueRecord(BaseModel):
    """
    模型判断后的结果结构，写入数据库

    创建时间: 2026-03-23
    创建者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    说明: 用于存储 LLM 判断后的对话结果，包含是否为对话、说话者、语气等信息

    修改时间: 2026-03-29
    创建者: TraeAI
    任务: add-identity-clue-to-dialogue-record
    修改内容: 添加 identity_clue 字段，用于存储对话中提取的身份线索

    修改时间: 2026-04-08
    创建者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: speaker 改为 list[str] 支持多人同时说话，删除 evidence 字段
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="候选序号（1开始）")
    content: str | None = Field(default=None, description="引号内的文字（可为空，从 candidates 匹配获取）")
    is_dialogue: bool = Field(description="是否为真实对话")
    speaker: list[str] | None = Field(default=None, description="说话人列表，支持多人同时说话，无法确定为 null")
    tone: str | None = Field(default=None, description="语气：强硬/温和/讽刺/恳求/命令/恐惧/惊慌")
    is_inner_monologue: bool = Field(default=False, description="是否为内心独白")
    identity_clue: str | None = Field(default=None, description="身份线索（如自报身份、称呼关系、别名揭示等）")


class DialogueAttributionResult(BaseModel):
    """
    对话归属判断结果数据结构

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 用于 LLM 结构化输出的对话归属判断结果模型

    修改时间: 2026-04-09
    创建者: TraeAI
    任务: fix-phase3-content-field
    修改内容: 使用 DialogueRecordSchema 替代 DialogueRecord，避免 LLM 返回 content
    """

    model_config = ConfigDict(frozen=True)

    dialogues: list[DialogueRecordSchema] = Field(default_factory=list, description="对话归属列表")


class RelationRecord(BaseModel):
    """
    关系记录数据结构

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: refactor-phase4-relation-extraction
    说明: 用于存储 LLM 识别的人物关系
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_name: str = Field(alias="from", description="关系发起者")
    to_name: str = Field(alias="to", description="关系接受者")
    type: RelationType = Field(description="关系类型：家族、师徒、敌对、盟友、友情、爱慕、主从、利益")
    change: RelationChange = Field(description="变化类型：无变化、新建、强化、弱化、断裂")
    evidence: str = Field(description="原文依据")


class RelationExtractionResult(BaseModel):
    """
    关系抽取结果数据结构

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: refactor-phase4-relation-extraction
    说明: 用于 LLM 结构化输出的关系抽取结果模型
    """

    model_config = ConfigDict(frozen=True)

    relations: list[RelationRecord] = Field(default_factory=list, description="关系列表")


class HierarchicalRelation(BaseModel):
    """
    层级关系数据结构

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 用于存储实体间的层级关系（belongs_to, member_of等）
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")

    from_entity: str = Field(alias="from", description="源实体名称")
    to_entity: str = Field(alias="to", description="目标实体名称")
    type: str = Field(description="关系类型：belongs_to, member_of, leader_of, affiliated_with")


class DisambiguateResponseModel(BaseModel):
    """
    消歧响应数据结构

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构本地消歧客户端集成 Instructor
    说明: 用于 Instructor 结构化输出的消歧结果模型

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: entity-type-relation-extraction
    修改内容: 新增 entity_types 和 entity_relations 字段

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix/disambig-thinking-save
    修改内容: 新增 _thinking_content 字段保存 thinking 内容

    修改时间: 2026-03-27
    修改者: TraeAI
    任务: disambiguation-state-three-layer
    修改内容: 将 alias_map 重命名为 canonical_decisions，明确表达模型判断而非运行时状态
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")

    canonical_decisions: dict[str, str] = Field(
        default_factory=dict,
        description="模型判断的规范名决策，key为候选名，value为规范名。允许自映射(A->A)表示独立角色。",
    )
    alias_confidence: dict[str, DisambigConfidence] = Field(
        default_factory=dict,
        description="disambiguation confidence per candidate (low/medium/high)",
    )
    entity_types: dict[str, EntityType] = Field(
        default_factory=dict,
        description="实体类型映射，key为实体名称，value为类型（character/group/organization/creature/artifact）",
    )
    entity_relations: list[HierarchicalRelation] = Field(
        default_factory=list,
        description="实体间的层级关系列表",
    )
    thinking_content: str | None = Field(
        default=None,
        description="模型的 thinking 内容（内部使用，不写入数据库）",
        alias="_thinking_content",
    )
    evidence_sources: dict[str, list[str]] = Field(
        default_factory=dict,
        description="每个候选名的证据来源列表，如 ['原文例句', '身份线索', '前文摘要-弱证据']",
    )


class ChunkAnnotation(BaseModel):
    """
    Chunk 标注数据结构

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: parallel-three-phase
    修改内容: 添加 dialogue_lengths 字段支持三阶段并行模式

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: remove-unused-annotation-fields
    修改内容: 移除 relations、character_appearances、chunk_summary 字段

    修改时间: 2026-03-30
    修改者: TraeAI
    任务: feature/chunk-summary-timeline-only
    修改内容: 恢复 chunk_summary 字段，仅用于 Timeline 展示，不参与消歧证据链
    """

    model_config = ConfigDict(frozen=False)

    emotional_valence: str
    event_type: str
    pivot_moment: bool
    cliffhanger: bool
    chunk_summary: str = Field(default="", description="核心事件摘要，30-50字，用于 Timeline 展示。不参与消歧证据链。")
    has_foreshadowing: bool = Field(
        description="当前文本块是否存在伏笔元素。这是分块级标记，不等于 diagnosis.foreshadow_rate。"
    )
    foreshadowing_type: str | None = None
    foreshadowing_desc: str = ""
    characters: list[CharacterSnapshot] = Field(default_factory=list)
    dialogues: list[DialogueSnapshot] = Field(default_factory=list)
    location_appearances: list[LocationAppearance] = Field(default_factory=list)
    dialogue_lengths: list[int] | None = Field(default=None)

    def to_dict(self) -> dict:
        return {
            "emotional_valence": self.emotional_valence,
            "event_type": self.event_type,
            "pivot_moment": self.pivot_moment,
            "cliffhanger": self.cliffhanger,
            "chunk_summary": self.chunk_summary,
            "has_foreshadowing": self.has_foreshadowing,
            "foreshadowing_type": self.foreshadowing_type,
            "foreshadowing_desc": self.foreshadowing_desc,
            "characters": [
                {
                    "name": c.name,
                    "role_function": c.role_function,
                    "action": c.action,
                    "action_type": c.action_type,
                    "emotion_score": c.emotion_score,
                }
                for c in self.characters
            ],
            "dialogues": [
                {
                    "speaker": d.speaker,
                }
                for d in self.dialogues
            ],
            "location_appearances": [
                {
                    "raw_name": loc.raw_name,
                    "location_type": loc.location_type,
                }
                for loc in self.location_appearances
            ],
            "dialogue_lengths": self.dialogue_lengths,
        }
