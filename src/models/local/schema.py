from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EmotionalValenceV1 = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EmotionalValenceV2 = Literal["positive", "negative", "neutral"]
EmotionalValence = Literal[
    "strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative", "positive", "negative"
]
EmotionScore = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EventType = Literal["冲突", "铺垫", "转折"]
ForeshadowingType = Literal["causal", "thematic"]
ForeshadowingConfidence = Literal["high", "medium", "low"]
RoleFunction = Literal["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
RelationType = Literal["师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从"]
RelationChange = Literal["强化", "弱化", "新建", "断裂", "无变化"]
ClueType = Literal["none", "self_introduction", "named_by_other", "alias_revealed", "appearance_desc"]
ActionType = Literal["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]


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
    type: str
    change: str


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
    """

    model_config = ConfigDict(frozen=True)

    speaker: str | None = None
    content: str = ""


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

    has_foreshadowing: bool
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
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="候选序号（1开始）")
    ctx_before: str = Field(default="", description="引号前的上下文")
    content: str = Field(description="引号内的文字")
    ctx_after: str = Field(default="", description="引号后的上下文")


class DialogueRecord(BaseModel):
    """
    模型判断后的结果结构，写入数据库

    创建时间: 2026-03-23
    创建者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    说明: 用于存储 LLM 判断后的对话结果，包含是否为对话、说话者、语气等信息
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="候选序号（1开始）")
    content: str = Field(description="引号内的文字")
    is_dialogue: bool = Field(description="是否为真实对话")
    speaker: str | None = Field(default=None, description="说话人，无法确定为 null")
    tone: str | None = Field(default=None, description="语气：强硬/温和/讽刺/恳求/命令/恐惧/惊慌")
    is_inner_monologue: bool = Field(default=False, description="是否为内心独白")
    evidence: str = Field(default="", description="判断依据（用于调试）")


class DialogueAttribution(BaseModel):
    """
    单条对话归属数据结构（已废弃，请使用 DialogueRecord）

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 用于存储单条对话的说话者归属判断结果

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 标记为废弃，建议使用 DialogueRecord
    """

    model_config = ConfigDict(frozen=True)

    index: int = Field(description="对话序号（1开始）")
    speaker: str = Field(description="说话者名称")


class DialogueAttributionResult(BaseModel):
    """
    对话归属判断结果数据结构

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 用于 LLM 结构化输出的对话归属判断结果模型

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 使用 DialogueRecord 替代 DialogueAttribution
    """

    model_config = ConfigDict(frozen=True)

    dialogues: list[DialogueRecord] = Field(default_factory=list, description="对话归属列表")


class HierarchicalRelation(BaseModel):
    """
    层级关系数据结构

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 用于存储实体间的层级关系（belongs_to, member_of等）
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

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
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    alias_map: dict[str, str] = Field(
        default_factory=dict,
        description="人名到标准名的映射，key为原名，value为标准名",
    )
    entity_types: dict[str, str] = Field(
        default_factory=dict,
        description="实体类型映射，key为实体名称，value为类型（character/group/organization）",
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
    """

    model_config = ConfigDict(frozen=False)

    emotional_valence: str
    event_type: str
    pivot_moment: bool
    cliffhanger: bool
    has_foreshadowing: bool
    foreshadowing_type: str | None = None
    foreshadowing_desc: str = ""
    characters: list[CharacterSnapshot] = Field(default_factory=list)
    relations: list[RelationChangeSnapshot] = Field(default_factory=list)
    dialogues: list[DialogueSnapshot] = Field(default_factory=list)
    character_appearances: list[CharacterAppearance] = Field(default_factory=list)
    chunk_summary: str = ""
    dialogue_lengths: list[int] | None = Field(default=None)

    def to_dict(self) -> dict:
        return {
            "emotional_valence": self.emotional_valence,
            "event_type": self.event_type,
            "pivot_moment": self.pivot_moment,
            "cliffhanger": self.cliffhanger,
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
            "relations": [
                {
                    "from": r.from_name,
                    "to": r.to_name,
                    "type": r.type,
                    "change": r.change,
                }
                for r in self.relations
            ],
            "dialogues": [
                {
                    "speaker": d.speaker,
                }
                for d in self.dialogues
            ],
            "character_appearances": [
                {
                    "raw_name": ca.raw_name,
                    "identity_clue": ca.identity_clue,
                    "clue_type": ca.clue_type,
                }
                for ca in self.character_appearances
            ],
            "chunk_summary": self.chunk_summary,
            "dialogue_lengths": self.dialogue_lengths,
        }
