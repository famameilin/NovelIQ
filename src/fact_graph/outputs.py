"""
章节标注 Agent 输出与结果模型：账本绑定形态、检索结果与章级运行结果
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：schema.py 大文件拆分——原输出与结果模型段（Bound* / AgentRun* 等）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；依赖 schema 共享件（StrictModel）、
# vocabulary 词表与 inputs 输入模型，schema.py 对全部符号保留 re-export，
# 既有导入方零改动。依赖方向：vocabulary ← inputs ← outputs，严禁反向。

from __future__ import annotations

from pydantic import Field, model_validator

from .schema import StrictModel
from .vocabulary import RoleFunction, Tone


class BoundCharacterObservation(StrictModel):
    """用于保存从事件人物参与者派生的动态状态

    2026-10-04 随 participants 合同放开：三态字段可缺省（模型没写就是 None，
    不再要求必填），消费方按可空处理。
    """

    character: str = Field(min_length=1)
    role_function: RoleFunction | None = None
    action: str | None = Field(default=None, min_length=1)
    emotion: int | None = Field(default=None, ge=-2, le=2)


class BoundDialogue(StrictModel):
    """2026-08-11 用于系统绑定有效对话原文位置和语义结果"""

    candidate_index: int = Field(gt=0)
    candidate_key: str
    content: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    speaker: str | None = None
    tone: Tone | None = None
    is_inner_monologue: bool = False


class BoundParagraphLabel(StrictModel):
    """2026-09-14 段落级情绪监督绑定结果（paragraph_id 已在账本校验属于本章，无需再绑字符区间）"""

    paragraph_id: int = Field(ge=0)
    emotion: int


class TextSearchResult(StrictModel):
    """2026-08-30 用于查询服务返回配置范围内的原文命中与精确授权段落"""

    chapter_id: int = Field(gt=0)
    paragraph_ids: list[int] = Field(min_length=1)
    content: str = Field(min_length=1)
    keyword_score: float = Field(ge=0)
    semantic_score: float | None = None

    @model_validator(mode="after")
    def validate_paragraph_ids(self) -> TextSearchResult:
        """2026-08-30 用于校验命中段落身份非负且不重复"""
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
