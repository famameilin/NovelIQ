"""
章节标注 Agent 输入模型：Agent 提交面载荷、章内段落坐标与对话候选
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from pydantic import Field, model_validator

from .schema import (
    CLIFFHANGER_DESCRIPTION,
    EMOTION_SCORE_DESCRIPTION,
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ENTITY_TAGS_RULE_TEXT,
    PIVOT_MOMENT_DESCRIPTION,
    StrictModel,
    normalize_semantic_text,
)
from .vocabulary import (
    DialogueParseStatus,
    DialogueVerdict,
    EntityType,
    NarrativeFunction,
    RelationType,
    Tone,
    relation_catalog_text,
)


class EntityInput(StrictModel):
    """提交当前章 明确出现的实体"""

    name: str = Field(min_length=1, description="实体名称（新实体用本章出现的名称，已登记实体用登记名）")
    entity_type: EntityType = Field(
        description="实体大类：character=有生命的（含人/动物/灵兽/妖/器灵），item=无生命物品，"
        "location=地点，organization=组织；有生命就是 character，不要按戏份调整"
    )
    tags: list[str] = Field(
        default_factory=list,
        description=f'可空标签，{ENTITY_TAGS_RULE_TEXT}，如"灵兽""剑灵""法宝"',
    )
    description: str | None = Field(
        default=None,
        description="实体一句话简介（已登记实体不要重复提交）",
    )
    representative: bool | None = Field(
        default=None,
        description="规范名代表标记：True=标记为同名身份的规范名，False=清除该标记，省略=保留现值",
    )

    @model_validator(mode="after")
    def normalize_entity(self) -> EntityInput:
        """规范化实体名称、可选描述和自由标签"""
        self.name = normalize_semantic_text(self.name, label="entity.name")
        normalized_tags: list[str] = []
        for tag in self.tags:
            cleaned = unicodedata.normalize("NFC", tag).strip()
            if cleaned and cleaned not in normalized_tags:
                normalized_tags.append(cleaned)
        if len(normalized_tags) > ENTITY_TAG_MAX_COUNT:
            raise ValueError(f"entity.tags 最多 {ENTITY_TAG_MAX_COUNT} 个标签")
        if any(len(tag) > ENTITY_TAG_MAX_CHARS for tag in normalized_tags):
            raise ValueError(f"entity.tags 每个标签最多 {ENTITY_TAG_MAX_CHARS} 个字")
        self.tags = normalized_tags
        if self.description is not None:
            self.description = normalize_semantic_text(
                self.description,
                label="entity.description",
            )
        return self


class EntityNameRef(StrictModel):
    """实体引用写正文名字与大类，运行时解析并自动登记；不接受 id"""

    name: str = Field(min_length=1, description="正文中的名字或稳定专指称谓")
    entity_type: EntityType = Field(description="实体大类：character/item/location/organization")

    @model_validator(mode="after")
    def normalize_name(self) -> EntityNameRef:
        self.name = normalize_semantic_text(self.name, label="entity_ref.name")
        return self


class RelationInput(StrictModel):
    """以正文名字与大类提交关系，两端由运行时解析并自动登记"""

    from_entity: EntityNameRef
    to_entity: EntityNameRef
    relation_type: RelationType = Field(description=relation_catalog_text())


class EntityDirectoryInput(StrictModel):
    """提交当前章 出现的全部实体（单列表）"""

    entities: list[EntityInput] = Field(default_factory=list)


# 段落级情绪监督：标签随指标整域提交；锚点用"段首可见号"（注入正文每段以 `N：` 开头），
# 标签与 evidence 一律引用该号，落库时再映射回全局 paragraph_id（对持久化无影响）。
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


class DialogueInput(StrictModel):
    """按候选序号提交对话三态判断"""

    candidate_index: int = Field(
        gt=0, description="候选序号，从 1 开始，与 DialogueCandidates 区块的 candidate_index 一致"
    )
    verdict: DialogueVerdict = Field(
        description="判断结果：dialogue=真实对话；inner_monologue=内心独白；"
        "not_dialogue=误判候选（如题字/描写被引号包裹）"
    )
    speaker: str | None = Field(
        default=None,
        description="说话人名称（已登记实体用登记名）；无法确认说话人时留 null",
    )
    # 枚举字段本身即拒绝非法词，不再叠函数级校验（越界值由类型报错，
    # 全词表与「其他」指引由工具层记录级回执给出）
    tone: Tone | None = None

    @model_validator(mode="after")
    def validate_dialogue(self) -> DialogueInput:
        """规范化说话人并约束三态字段组合"""
        if self.verdict == DialogueVerdict.NOT_DIALOGUE:
            if self.speaker is not None or self.tone is not None:
                raise ValueError("not_dialogue 候选只能提交 candidate_index 和 verdict；speaker/tone 必须为 null")
            return self
        if self.speaker is not None:
            self.speaker = normalize_semantic_text(
                self.speaker,
                label="dialogue.speaker",
            )
        return self


class TextEvidence(StrictModel):
    """保存原文段落锚点证据（段落 ID + 字符范围）"""

    paragraph_ids: list[int] = Field(min_length=1, description="全局段落 ID 列表")
    char_start: int = Field(ge=0, description="锚点文本在章文本中的起始字符偏移")
    char_end: int = Field(gt=0, description="锚点文本在章文本中的结束字符偏移")

    @model_validator(mode="after")
    def validate_span(self) -> TextEvidence:
        """保证文本证据段落和字符范围具有有效顺序"""
        if any(paragraph_id < 0 for paragraph_id in self.paragraph_ids):
            raise ValueError("TextEvidence.paragraph_ids 不能为负数")
        if self.char_end <= self.char_start:
            raise ValueError("TextEvidence.char_end 必须大于 char_start")
        if len(set(self.paragraph_ids)) != len(self.paragraph_ids):
            raise ValueError("TextEvidence.paragraph_ids 不允许重复")
        return self


# 段首可见号：正文段落若自带 `N：` 前缀则沿用该号，否则按顺序编 1 基号。
# 注入、evidence、标签三处共用这一个号码空间；全局 paragraph_id 只留在持久化侧。
_PARAGRAPH_NUMBER_PREFIX_RE = re.compile(r"^\s*(\d+)\s*：")


def paragraph_has_visible_prefix(text: str) -> bool:
    """判断段落文本是否已自带 `N：` 段首号（注入时避免重复渲染）"""
    return _PARAGRAPH_NUMBER_PREFIX_RE.match(text) is not None


@dataclass(slots=True)
class ChapterParagraphInfo:
    """保存当前 章内段落坐标映射（注入 prompt 标记和派生事件锚点）

    模型可见的段落号是"段首可见号"——正文每段以 `N：` 开头
    （正文自带该前缀时沿用前缀里的号，否则按块内顺序编 1 基号）；evidence 与
    write_metrics.labels 都提交这个号，服务端按本映射取段落并映射回全局
    paragraph_id 再落库。三组列表内部仍按 0 基 章内序号索引。
    """

    # 0 基 章内序号 → 全局 paragraph_id
    paragraph_ids: list[int]
    # 0 基 章内序号 → (start_char, end_char) 在 章正文内的偏移
    char_spans: list[tuple[int, int]]
    # 0 基 章内序号 → 段落文本
    texts: list[str]

    def __post_init__(self) -> None:
        """校验三组列表长度一致且非空"""
        n = len(self.paragraph_ids)
        if n == 0:
            raise ValueError("ChapterParagraphInfo 不能为空")
        if len(self.char_spans) != n or len(self.texts) != n:
            raise ValueError("paragraph_ids / char_spans / texts 长度不一致")

    def visible_ids(self) -> list[int]:
        """取每段的段首可见号（正文自带 N：前缀时用该号，否则 1 基顺序号）

        自带前缀出现重复号时退回纯 1 基顺序号：号码空间必须一对一，注入的正文
        与 evidence 锚点才不会有歧义。
        """
        ids: list[int] = []
        for index, text in enumerate(self.texts, start=1):
            match = _PARAGRAPH_NUMBER_PREFIX_RE.match(text)
            ids.append(int(match.group(1)) if match else index)
        if len(set(ids)) != len(ids):
            return list(range(1, len(self.texts) + 1))
        return ids

    def text_by_visible_id(self) -> dict[int, str]:
        """取"段首可见号 → 段落文本"映射（evidence/标签按号取段）"""
        return dict(zip(self.visible_ids(), self.texts, strict=True))


class BoundRelationInput(StrictModel):
    """通过实体名称提交本章确认存在的闭合类型关系边（内部系统形态）"""

    from_entity: str = Field(min_length=1, description="关系起点实体（图上的登记名称）")
    to_entity: str = Field(min_length=1, description="关系终点实体（图上的登记名称）")
    relation_type: RelationType = Field(description="闭合关系类型，方向与端点约束如下：\n" + relation_catalog_text())

    @model_validator(mode="after")
    def normalize_relation(self) -> BoundRelationInput:
        """规范化关系两端实体名称"""
        self.from_entity = normalize_semantic_text(
            self.from_entity,
            label="relation.from_entity",
        )
        self.to_entity = normalize_semantic_text(
            self.to_entity,
            label="relation.to_entity",
        )
        if self.from_entity == self.to_entity and self.relation_type != RelationType.SAME_CHARACTER:
            raise ValueError("关系两端不能是同一名称")
        return self


class DialogueCandidate(StrictModel):
    """系统保存对话候选真实原文和位置"""

    candidate_key: str = Field(min_length=1)
    chapter_id: int = Field(gt=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    content: str = Field(min_length=1)
    parse_status: DialogueParseStatus

    @model_validator(mode="after")
    def validate_bounds(self) -> DialogueCandidate:
        """拒绝倒置或空的系统对话区间"""
        if self.end <= self.start:
            raise ValueError("dialogue candidate end 必须大于 start")
        return self
