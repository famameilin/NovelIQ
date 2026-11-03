"""章级叙事指标与段落情绪标注契约"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.event_trees.vocabulary import EMOTION_SCORE_DESCRIPTION
from src.text_processing.normalize import normalize_semantic_text


class StrictModel(BaseModel):
    "指标输入拒绝额外字段"

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


PIVOT_MOMENT_DESCRIPTION = (
    "本章是否标记为叙事转折点（布尔，独立字段）。narrative_function 说的是本章自身的叙事功能，"
    "本字段说的是本章是否构成转折点，两者各自判断、允许不一致。"
)


CLIFFHANGER_DESCRIPTION = "本章是否以悬念收尾（布尔，追读钩子）。"


class NarrativeFunction(StrEnum):
    """本章在叙事结构中的功能，只能取一个

    冲突=已展开的矛盾在本章有一次正面交锋；铺垫=本章埋下后文要用的条件、线索或关系；
    转折=本章改变了人物的处境、立场或认知。按本章最主要的作用判。
    """

    CONFLICT = "冲突"
    SETUP = "铺垫"
    TURNING_POINT = "转折"


class ParagraphLabelInput(StrictModel):
    """一个段落的情绪标签

    paragraph_id 取正文段首可见号（每段开头的 `N：` 里那个 N）。
    """

    paragraph_id: int = Field(ge=1, description="段首可见号（正文每段开头的 `N：`）")
    emotion: int = Field(ge=-2, le=2, description=f"整段情绪分值。{EMOTION_SCORE_DESCRIPTION}")


class ChapterMetricsInput(StrictModel):
    """提交当前章 摘要和叙事指标"""

    summary: str = Field(min_length=1)
    emotional_valence: int = Field(ge=-2, le=2, description=EMOTION_SCORE_DESCRIPTION)
    narrative_function: NarrativeFunction
    pivot_moment: bool = Field(default=False, description=PIVOT_MOMENT_DESCRIPTION)
    cliffhanger: bool = Field(default=False, description=CLIFFHANGER_DESCRIPTION)
    labels: list[ParagraphLabelInput] = Field(
        default_factory=list,
        description="段落级情绪标签（每章自选 2-3 段；按 paragraph_id 去重，重复提交以最后一次为准）",
    )

    @model_validator(mode="after")
    def normalize_summary(self) -> ChapterMetricsInput:
        """规范化当前章 摘要；labels 按 paragraph_id 去重（后写覆盖）"""
        self.summary = normalize_semantic_text(self.summary, label="summary")
        deduped: dict[int, ParagraphLabelInput] = {}
        for label in self.labels:
            deduped[label.paragraph_id] = label
        self.labels = list(deduped.values())
        return self
