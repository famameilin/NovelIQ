"""
标注 Agent 输出 Schema

阶段 1-4（人物/伏笔/对话/关系）合并为单一结构化输出，
身份消歧以 identity_decisions 形式集成进 agent 输出
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.models.local.schema import LocationAppearance, RelationRecord

EmotionalValence = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EventType = Literal["冲突", "铺垫", "转折"]
RoleFunction = Literal["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
ActionType = Literal["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]


class AgentCharacter(BaseModel):
    """出场人物（合并 Phase1 characters）"""

    name: str = Field(description="人物当前已知的常用名（原文中逐字出现）")
    role_function: RoleFunction = Field(description="主体|客体|发送者|接收者|帮助者|反对者")
    action: str = Field(description="本块中最重要的一个行为，动词短语")
    action_type: ActionType = Field(description="战斗|逃跑|对话|决策|移动|情感|其他")
    emotion_score: EmotionalValence = Field(
        description="strong_positive|mild_positive|neutral|mild_negative|strong_negative"
    )


class AgentForeshadowing(BaseModel):
    """伏笔分析（合并 Phase2）"""

    has_foreshadowing: bool
    foreshadowing_type: str | None = Field(default=None, description="物件|对话|场景|人物行为|其他")
    setup_kind: str | None = Field(
        default=None,
        description="异常物件|异常规则|隐藏身份|明确承诺|明确威胁|倒计时|未解释能力|因果引线|其他",
    )
    anchor_text: str = Field(default="")
    anchor_reason: str = Field(default="")
    setup_summary: str = Field(default="")
    why_unresolved_now: str = Field(default="")
    expected_payoff_family: str = Field(default="")
    payoff_likelihood: str | None = Field(default=None, description="high|medium")
    is_new_setup: bool = False
    linked_setup_id: str | None = None
    setup_status: str | None = Field(default=None, description="open|reinforced|likely_paid_off")
    confidence: str = Field(description="high|medium|low")


class AgentDialogue(BaseModel):
    """对话记录（合并 Phase3）"""

    content: str = Field(description="引号内的对话原文")
    speaker: list[str] | None = Field(default=None, description="说话人列表，无法确定时为空")
    tone: str | None = Field(default=None, description="强硬|温和|讽刺|恳求|命令|恐惧|惊慌")
    is_inner_monologue: bool = False
    identity_clue: str | None = Field(default=None, description="身份线索（如自报身份、称呼关系）")


class IdentityDecision(BaseModel):
    """身份消歧决策（集成进 agent 循环）"""

    name: str = Field(description="当前 chunk 中出现的表面称呼")
    canonical: str = Field(description="对应的规范名（可以等于 name 表示保持独立）")
    entity_type: str = Field(default="character", description="character|group|organization|creature|artifact")
    confidence: str = Field(default="high", description="high|medium|low")
    evidence: str = Field(default="", description="决策依据（原文或身份线索）")


class MergedChunkAnnotation(BaseModel):
    """合并标注输出：阶段 1-4 + 身份消歧决策"""

    emotional_valence: EmotionalValence = Field(
        description="strong_positive|mild_positive|neutral|mild_negative|strong_negative"
    )
    event_type: EventType = Field(description="冲突|铺垫|转折")
    pivot_moment: bool = False
    cliffhanger: bool = False
    chunk_summary: str = Field(description="30-50字核心事件摘要，必须包含出场人名")
    characters: list[AgentCharacter] = Field(default_factory=list)
    location_appearances: list[LocationAppearance] = Field(default_factory=list)
    foreshadowing: AgentForeshadowing | None = None
    dialogues: list[AgentDialogue] = Field(default_factory=list)
    relations: list[RelationRecord] = Field(default_factory=list, description="关系识别结果（合并 Phase4）")
    identity_decisions: list[IdentityDecision] = Field(default_factory=list)
