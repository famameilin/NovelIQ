"""LTP 语言结构输出结构与段落特征结果（《分析能力扩展路线图》§5.3）

段落语言特征的最小事实单元是"词元级结构数据 + 可加充分统计量"：
tokens / dependency_arcs 保存原始结构，word_length_counts / pos_counts /
sentence_pattern_counts / dependency 统计量全部守恒可加，比例由查询层计算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LtpToken:
    """词元结构：段内字符区间闭开 [local_start_char, local_end_char)"""

    token_index: int
    text: str
    local_start_char: int
    local_end_char: int
    pos_tag: str
    pos_group: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_index": self.token_index,
            "text": self.text,
            "local_start_char": self.local_start_char,
            "local_end_char": self.local_end_char,
            "pos_tag": self.pos_tag,
            "pos_group": self.pos_group,
        }


@dataclass(frozen=True)
class LtpDependencyArc:
    """依存边：LTP 坐标系 ROOT=0、词元索引 1 起（文档 §C2）"""

    dependent_index: int
    head_index: int
    relation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependent_index": self.dependent_index,
            "head_index": self.head_index,
            "relation": self.relation,
        }


@dataclass(frozen=True)
class LtpEntityCandidate:
    """LTP NER 实体候选（字符区间闭开；候选不代表正式图谱事实）"""

    surface_text: str
    raw_entity_type: str
    normalized_entity_type: str | None
    local_start_char: int
    local_end_char: int


@dataclass(frozen=True)
class LtpSdpArc:
    """语义依存弧（sdp，2026-09-05 B 批）：head/dependent 均为段内全局 token_index

    LTP sdp 输出为逐句 dict {'head','dependent','label'}；head 侧为谓词，
    dependent 侧为论元/修饰（AGT=施事、DATV=对象、mNEG=否定、mDEPD=程度）。
    """

    head_index: int
    dependent_index: int
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "head_index": self.head_index,
            "dependent_index": self.dependent_index,
            "label": self.label,
        }


@dataclass(frozen=True)
class EmotionEvent:
    """LTP 语义情绪事件（2026-09-05 B 批）

    情绪词典只承担谓词极性候选标记；持有者/对象/否定/程度全部来自 sdp 模型判定。
    """

    predicate: str
    predicate_token_index: int
    polarity: str  # "positive" | "negative"
    holder: str | None
    target: str | None
    negated: bool
    degree_words: tuple[str, ...]
    local_start_char: int
    local_end_char: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicate": self.predicate,
            "predicate_token_index": self.predicate_token_index,
            "polarity": self.polarity,
            "holder": self.holder,
            "target": self.target,
            "negated": self.negated,
            "degree_words": list(self.degree_words),
            "local_start_char": self.local_start_char,
            "local_end_char": self.local_end_char,
        }


@dataclass(frozen=True)
class ParagraphLinguisticResult:
    """单个段落的语言结构基础结果"""

    ltp_token_count: int
    tokens: list[LtpToken]
    word_length_counts: dict[str, int]
    pos_counts: dict[str, int]
    sentence_count: int
    sentence_pattern_counts: dict[str, int]
    dependency_arcs: list[LtpDependencyArc]
    dependency_node_count: int
    dependency_root_count: int
    dependency_depth_sum: int
    dependency_depth_max: int
    dependency_relation_counts: dict[str, int]
    entities: list[LtpEntityCandidate] = field(default_factory=list)
    # 2026-09-05 B 批：sdp 语义弧与词典情绪事件（sdp 任务关闭时为空）
    sdp_arcs: list[LtpSdpArc] = field(default_factory=list)
    emotion_events: list[EmotionEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ltp_token_count": self.ltp_token_count,
            "tokens": [t.to_dict() for t in self.tokens],
            "word_length_counts": self.word_length_counts,
            "pos_counts": self.pos_counts,
            "sentence_count": self.sentence_count,
            "sentence_pattern_counts": self.sentence_pattern_counts,
            "dependency_arcs": [a.to_dict() for a in self.dependency_arcs],
            "dependency_node_count": self.dependency_node_count,
            "dependency_root_count": self.dependency_root_count,
            "dependency_depth_sum": self.dependency_depth_sum,
            "dependency_depth_max": self.dependency_depth_max,
            "dependency_relation_counts": self.dependency_relation_counts,
            "entities": [
                {
                    "surface_text": e.surface_text,
                    "raw_entity_type": e.raw_entity_type,
                    "normalized_entity_type": e.normalized_entity_type,
                    "local_start_char": e.local_start_char,
                    "local_end_char": e.local_end_char,
                }
                for e in self.entities
            ],
            "sdp_arcs": [a.to_dict() for a in self.sdp_arcs],
            "emotion_events": [e.to_dict() for e in self.emotion_events],
        }