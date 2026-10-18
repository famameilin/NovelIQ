"""
章节标注 Agent 输出与结果模型：账本绑定形态、检索结果与章级运行结果
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .schema import StrictModel
from .vocabulary import RoleFunction, Tone


class BoundCharacterObservation(StrictModel):
    """用于保存从事件人物参与者派生的动态状态"""

    character: str = Field(min_length=1)
    role_function: RoleFunction | None = None
    action: str | None = Field(default=None, min_length=1)
    emotion: int | None = Field(default=None, ge=-2, le=2)


class BoundDialogue(StrictModel):
    """系统绑定有效对话原文位置和语义结果"""

    candidate_index: int = Field(gt=0)
    candidate_key: str
    content: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    speaker: str | None = None
    tone: Tone | None = None
    is_inner_monologue: bool = False


class BoundParagraphLabel(StrictModel):
    """段落级情绪监督绑定结果（paragraph_id 已在账本校验属于本章，无需再绑字符区间）"""

    paragraph_id: int = Field(ge=0)
    emotion: int


class TextSearchResult(StrictModel):
    """查询服务返回配置范围内的原文命中与精确授权段落"""

    chapter_id: int = Field(gt=0)
    paragraph_ids: list[int] = Field(min_length=1)
    content: str = Field(min_length=1)
    keyword_score: float = Field(ge=0)
    semantic_score: float | None = None

    @model_validator(mode="after")
    def validate_paragraph_ids(self) -> TextSearchResult:
        """校验命中段落身份非负且不重复"""
        if any(paragraph_id < 0 for paragraph_id in self.paragraph_ids):
            raise ValueError("TextSearchResult.paragraph_ids 不能为负数")
        if len(set(self.paragraph_ids)) != len(self.paragraph_ids):
            raise ValueError("TextSearchResult.paragraph_ids 不允许重复")
        return self


class SourceReference(StrictModel):
    """跨章寻址只依赖已经存在的原文，不依赖其他 Agent 的产出"""

    chapter_id: int = Field(gt=0)
    paragraph_id: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    text_hash: str

    @model_validator(mode="after")
    def validate_span(self) -> SourceReference:
        if self.char_end <= self.char_start:
            raise ValueError("原文引用必须是非空区间")
        return self
