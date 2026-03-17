from __future__ import annotations

from typing import List, Literal, Optional

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

    speaker: str
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
    foreshadowing_type: Optional[str] = None
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


class DisambiguateResponseModel(BaseModel):
    """
    消歧响应数据结构

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构本地消歧客户端集成 Instructor
    说明: 用于 Instructor 结构化输出的消歧结果模型
    """

    model_config = ConfigDict(frozen=True)

    alias_map: dict[str, str] = Field(
        default_factory=dict,
        description="人名到标准名的映射，key为原名，value为标准名",
    )


class ChunkAnnotation(BaseModel):
    """
    Chunk 标注数据结构

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 迁移数据模型至 Pydantic
    修改内容: 从 dataclass 迁移至 Pydantic BaseModel
    """

    model_config = ConfigDict(frozen=True)

    emotional_valence: str
    event_type: str
    pivot_moment: bool
    cliffhanger: bool
    has_foreshadowing: bool
    foreshadowing_type: Optional[str] = None
    foreshadowing_desc: str = ""
    characters: List[CharacterSnapshot] = Field(default_factory=list)
    relations: List[RelationChangeSnapshot] = Field(default_factory=list)
    dialogues: List[DialogueSnapshot] = Field(default_factory=list)
    character_appearances: List[CharacterAppearance] = Field(default_factory=list)
    chunk_summary: str = ""

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
        }
