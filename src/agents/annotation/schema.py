"""
标注 Agent 输出 Schema

阶段 1-4（人物/伏笔/对话/关系）合并为单一结构化输出，
身份消歧以 identity_decisions 形式集成进 agent 输出
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.models.local.schema import LocationAppearance, RelationRecord

EmotionalValence = Literal["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
EventType = Literal["冲突", "铺垫", "转折"]
RoleFunction = Literal["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
ActionType = Literal["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]
EvidencePurpose = Literal["identity", "relation", "foreshadowing", "other"]


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

    @model_validator(mode="after")
    def validate_thread_contract(self) -> AgentForeshadowing:
        """
        2026-08-02 用于在 finish 阶段校验伏笔新建与既有线程续接合同
        """
        if self.has_foreshadowing:
            if self.confidence not in {"high", "medium"}:
                raise ValueError("positive foreshadowing confidence must be high or medium")
            if not self.foreshadowing_type:
                raise ValueError("positive foreshadowing requires foreshadowing_type")
            if not self.setup_kind:
                raise ValueError("positive foreshadowing requires setup_kind")
            if len(self.setup_summary.strip()) < 4:
                raise ValueError("positive foreshadowing requires setup_summary")
            if self.payoff_likelihood not in {"high", "medium"}:
                raise ValueError("positive foreshadowing requires high or medium payoff_likelihood")
            if self.setup_status not in {"open", "reinforced", "likely_paid_off"}:
                raise ValueError("positive foreshadowing requires setup_status")
            if self.is_new_setup:
                if self.linked_setup_id is not None:
                    raise ValueError("new foreshadowing setup must not have linked_setup_id")
                if self.setup_status != "open":
                    raise ValueError("new foreshadowing setup requires setup_status=open")
            else:
                if not self.linked_setup_id or not self.linked_setup_id.strip():
                    raise ValueError("existing foreshadowing setup requires linked_setup_id")
                if self.setup_status == "open":
                    raise ValueError("existing foreshadowing setup cannot use setup_status=open")
            return self

        if any(
            (
                self.foreshadowing_type is not None,
                self.setup_kind is not None,
                bool(self.setup_summary.strip()),
                bool(self.why_unresolved_now.strip()),
                bool(self.expected_payoff_family.strip()),
                self.payoff_likelihood is not None,
                self.is_new_setup,
                self.linked_setup_id is not None,
                self.setup_status is not None,
            )
        ):
            raise ValueError("negative foreshadowing result must not include setup thread fields")
        return self


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


class HistoricalEvidenceCitation(BaseModel):
    """Agent 对历史自然段证据的结构化引用"""

    evidence_id: str = Field(min_length=1, description="历史原文工具返回的稳定证据 ID")
    purpose: EvidencePurpose = Field(description="identity|relation|foreshadowing|other")
    claim: str = Field(min_length=1, description="该历史证据支持的具体判断")


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
    historical_evidence_citations: list[HistoricalEvidenceCitation] = Field(
        default_factory=list,
        description="对本轮历史取证返回证据的结构化引用",
    )


class MergedChunkAnnotationPatch(BaseModel):
    """校验失败后的合并标注局部修正结构"""

    emotional_valence: EmotionalValence | None = None
    event_type: EventType | None = None
    pivot_moment: bool | None = None
    cliffhanger: bool | None = None
    chunk_summary: str | None = None
    characters: list[AgentCharacter] | None = None
    location_appearances: list[LocationAppearance] | None = None
    foreshadowing: AgentForeshadowing | None = None
    dialogues: list[AgentDialogue] | None = None
    relations: list[RelationRecord] | None = None
    identity_decisions: list[IdentityDecision] | None = None
    historical_evidence_citations: list[HistoricalEvidenceCitation] | None = None

    @model_validator(mode="after")
    def validate_non_empty_patch(self) -> MergedChunkAnnotationPatch:
        """
        2026-08-03 用于确保 revise_finish 至少提交一个明确修正字段
        """
        if not self.model_fields_set:
            raise ValueError("局部修正至少需要提供一个字段")
        return self
