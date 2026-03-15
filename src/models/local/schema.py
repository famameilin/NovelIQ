from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

EmotionalValence = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EmotionalValenceV2 = Literal["positive", "negative", "neutral"]
EmotionScore = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EventType = Literal["冲突", "铺垫", "转折"]
ForeshadowingType = Literal["causal", "thematic"]
ForeshadowingConfidence = Literal["high", "medium", "low"]
RoleFunction = Literal["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
RelationType = Literal["师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从"]
RelationChange = Literal["强化", "弱化", "新建", "断裂", "无变化"]
ClueType = Literal["none", "self_introduction", "named_by_other", "alias_revealed", "appearance_desc"]
ActionType = Literal["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]


# 新增：角色出场信息数据结构
# Created: 2026-03-12, TraeAI, task: fix-annotation-disambiguation-issues
@dataclass(frozen=True)
class CharacterAppearance:
    raw_name: str
    identity_clue: str
    clue_type: ClueType


@dataclass(frozen=True)
class CharacterSnapshot:
    name: str
    role_function: RoleFunction
    action: str
    action_type: ActionType
    emotion_score: EmotionScore


@dataclass(frozen=True)
class RelationChangeSnapshot:
    from_name: str
    to_name: str
    type: RelationType
    change: RelationChange


@dataclass(frozen=True)
class DialogueSnapshot:
    speaker: str


@dataclass(frozen=True)
class ForeshadowingResult:
    """
    伏笔分析结果数据结构

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """

    has_foreshadowing: bool
    foreshadowing_type: Optional[ForeshadowingType]
    anchor_text: str
    anchor_reason: str
    confidence: ForeshadowingConfidence

    def to_dict(self) -> dict:
        return {
            "has_foreshadowing": self.has_foreshadowing,
            "foreshadowing_type": self.foreshadowing_type,
            "anchor_text": self.anchor_text,
            "anchor_reason": self.anchor_reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ChunkAnnotation:
    emotional_valence: EmotionalValence
    event_type: EventType
    pivot_moment: bool
    cliffhanger: bool
    has_foreshadowing: bool
    foreshadowing_type: Optional[ForeshadowingType]
    foreshadowing_desc: str
    characters: List[CharacterSnapshot] = field(default_factory=list)
    relations: List[RelationChangeSnapshot] = field(default_factory=list)
    dialogues: List[DialogueSnapshot] = field(default_factory=list)
    character_appearances: List[CharacterAppearance] = field(default_factory=list)
    chunk_summary: str = ""

    def validate(self) -> None:
        pass

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
