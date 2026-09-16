"""章内并行 CodeAct：块代理的局部标注中间表示（内存对象，零新表零迁移）

设计（章内并行 CodeAct 方案 §3/§5/§6）：
- 块代理产出的是**局部标注**，不是正式写入：mention 只是"本块出现过的一个名字"，
  没有实体编号、没有图节点；身份绑定、跨块去重与事件归并留给章节代理裁决；
- 句柄形如 B2:m3（块序 1 基 + 块内键），这是块面与章面之间唯一的寻址面——
  真实 uuid 与运行期编号都不外露，块完成顺序不构成任何语义顺序；
- 每条局部对象自带 evidence=[{paragraph_id, quote}]，构造当场做 NFC 唯一命中核验
  （与读者面同一条硬门槛），没通过核验的引文进不了中间表示；
- 闭集词表一律从 schema.py / tools.py 单源引用，本模块不复制任何词表。

中间表示只活在内存里：既不进数据库，也不进正式账本。章节代理按句柄读取后，
经编译路径落成有序的正式写入调用（见 chapter_merge.py）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .errors import AnnotationStageRejection
from .reader_report import verify_quote_against_paragraph
from .schema import (
    DialogueVerdict,
    EntityType,
    EventParticipantRole,
    NarrativeFunction,
    RoleFunction,
    Tone,
)
from .tools import RELATION_DEFINITIONS

# 待决项类型：块代理判不了、必须由章节代理在章级视野下裁决的事项
PENDING_KINDS: dict[str, str] = {
    "unresolved_reference": "引用无法解析（本块没给出所指对象，需章节代理按历史实体/其他块绑定）",
    "event_continuation": "事件延续（本块事件像是另一块某事件的后继或同一事件的两段）",
    "case_clue": "案例线索（疑似伏笔/疑点，但裁决权在章级）",
    "other": "其他需要章级裁决的事项",
}

# 块内事件联系类型：只表达正文支撑的联系，不自动推导因果
LINK_KINDS: dict[str, str] = {
    "succession": "顺承（先发生/后发生，正文有时间先后的直接依据）",
    "causality": "因果（正文明确说了因为前者所以后者）",
    "same_scene": "同一场（同一时空连续段落里的两个片段）",
    "parallel": "并行（同一时段两处交替叙述）",
}

# 闭集词表单源：全部从 schema/tools 的枚举与注册表派生，块面与章面的报错文案共用
ENTITY_TYPES: tuple[str, ...] = tuple(member.value for member in EntityType)
DIALOGUE_VERDICTS: tuple[str, ...] = tuple(member.value for member in DialogueVerdict)
TONE_VALUES: tuple[str, ...] = tuple(member.value for member in Tone)
PARTICIPANT_ROLES: tuple[str, ...] = tuple(member.value for member in EventParticipantRole)
RUNTIME_ROLES: tuple[str, ...] = tuple(member.value for member in RoleFunction)
NARRATIVE_FUNCTIONS: tuple[str, ...] = tuple(member.value for member in NarrativeFunction)
RELATION_TYPES: tuple[str, ...] = tuple(RELATION_DEFINITIONS)


def _reject(
    message: str,
    *,
    record: str,
    field: str,
    code: str,
    expected: str,
) -> AnnotationStageRejection:
    """用于构造块局部对象的记录级结构化拒绝（模型按 record/field/code 自纠）"""
    return AnnotationStageRejection(
        message,
        record=record,
        field=field,
        code=code,
        expected=expected,
    )


def _require_key(value: Any, *, record: str, field_name: str = "key") -> str:
    """用于校验块内局部键（非空、不含句柄分隔符与路径分隔符）"""
    if not isinstance(value, str) or not value.strip():
        raise _reject(
            f"{field_name} 必须是非空字符串",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="你自定的块内短键，如 m1 / e2 / r1（同一类内唯一）",
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    for illegal, why in ((":", "冒号是句柄分隔符"), ("/", "斜杠留给章级事件树的层级键")):
        if illegal in normalized:
            raise _reject(
                f"{field_name} 不能包含 {illegal}（{why}）",
                record=record,
                field=field_name,
                code="invalid_value",
                expected="纯短键，如 m1、e2、r1",
            )
    return normalized


def _require_text(value: Any, *, record: str, field_name: str) -> str:
    """用于校验非空人类可读文本（NFC 归一 + strip）"""
    if not isinstance(value, str) or not value.strip():
        raise _reject(
            f"{field_name} 必须是非空字符串",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="非空文本",
        )
    return unicodedata.normalize("NFC", value).strip()


def _require_enum(value: Any, allowed: dict[str, str] | tuple[str, ...], *, record: str, field_name: str) -> str:
    """用于把取值限制在单源闭集内（越界值报出全部合法取值，一次自纠）"""
    catalog = list(allowed) if isinstance(allowed, dict) else list(allowed)
    text = value if isinstance(value, str) else str(value)
    if text not in catalog:
        raise _reject(
            f"{field_name} 取值越界：{value!r}",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="合法取值：" + "、".join(catalog),
        )
    return text


def _require_score(value: Any, *, record: str, field_name: str) -> int:
    """用于校验情绪分值（-2..2 整数，排除 bool）"""
    if isinstance(value, bool) or not isinstance(value, int) or not -2 <= value <= 2:
        raise _reject(
            f"{field_name} 必须是 -2..2 的整数",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="-2 强烈负面 / -1 轻微负面 / 0 中性 / 1 轻微正面 / 2 强烈正面",
        )
    return value


@dataclass(frozen=True, slots=True)
class LocalEvidence:
    """通过 NFC 唯一命中核验的逐字引文（块内段落锚点）"""

    paragraph_id: int
    quote: str

    def to_dict(self) -> dict[str, Any]:
        """用于渲染成模型可见的证据视图"""
        return {"paragraph_id": self.paragraph_id, "quote": self.quote}


def normalize_evidence(
    raw: Any,
    *,
    record: str,
    paragraph_text_by_id: dict[int, str],
    field_name: str = "evidence",
    required: bool = True,
) -> tuple[LocalEvidence, ...]:
    """用于把模型提交的证据归一成已核验的 LocalEvidence 序列（不通过即结构化拒绝）

    判据与读者面同一份实现（reader_report.verify_quote_against_paragraph）：
    paragraph_id 属于本块，quote 经 NFC 归一后在该段落内唯一命中。
    """
    if raw is None or raw == []:
        if not required:
            return ()
        raise _reject(
            f"{record} 缺少 {field_name} 逐字引文",
            record=record,
            field=field_name,
            code="missing_evidence",
            expected='[{paragraph_id: 本块段号, quote: "该段内的逐字摘录"}]，至少一条',
        )
    if not isinstance(raw, (list, tuple)):
        raise _reject(
            f"{field_name} 必须是 [{{paragraph_id, quote}}] 数组",
            record=record,
            field=field_name,
            code="invalid_value",
            expected='[{paragraph_id: 本块段号, quote: "逐字摘录"}]',
        )
    entries: list[LocalEvidence] = []
    for index, item in enumerate(raw):
        candidate = item if isinstance(item, dict) else {}
        result = verify_quote_against_paragraph(
            candidate.get("paragraph_id"),
            candidate.get("quote"),
            paragraph_text_by_id,
        )
        if isinstance(result, str):
            raise _reject(
                f"{field_name}[{index}] {result}",
                record=record,
                field=field_name,
                code="evidence_unverified",
                expected="从本块 <paragraph> 里原样摘录（不要改写、不要跨段拼接），过短会不唯一就加长",
            )
        entries.append(LocalEvidence(paragraph_id=result[0], quote=result[1]))
    return tuple(entries)


def _evidence_view(evidence: tuple[LocalEvidence, ...]) -> list[dict[str, Any]]:
    """用于渲染证据列表（章面按句柄读取明细时用）"""
    return [entry.to_dict() for entry in evidence]


@dataclass(slots=True)
class LocalMention:
    """块内的一次实体提及（不是一个已建实体：身份绑定由章节代理裁决）"""

    key: str
    name: str
    entity_type: str
    tags: list[str]
    description: str | None
    attributes: dict[str, Any] | None
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "name": self.name,
            "entity_type": self.entity_type,
            "tags": list(self.tags),
            "description": self.description,
            "attributes": self.attributes,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalRelation:
    """块内两个提及之间的一条关系（两端都是块内局部句柄或已登记名）"""

    key: str
    from_ref: str
    to_ref: str
    relation_type: str
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "from": self.from_ref,
            "to": self.to_ref,
            "relation_type": self.relation_type,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalDialogue:
    """块内一条对话候选的三态判断（candidate 是本块候选序号）"""

    key: str
    candidate_index: int
    verdict: str
    speaker: str | None
    tone: str | None
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "candidate_index": self.candidate_index,
            "verdict": self.verdict,
            "speaker": self.speaker,
            "tone": self.tone,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalParticipant:
    """块内事件参与者的完整字段（character 三态齐备；非 character 只 role）"""

    entity: str
    role: str
    narrative_role: str | None
    action: str | None
    emotion: int | None
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "entity": self.entity,
            "role": self.role,
            "narrative_role": self.narrative_role,
            "action": self.action,
            "emotion": self.emotion,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalEvent:
    """块内一个局部事件（扁平结构：树形由章节代理归并时决定）"""

    key: str
    description: str
    participants: list[LocalParticipant]
    evidence: tuple[LocalEvidence, ...]
    is_foreshadowing: bool = False
    confidence: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "description": self.description,
            "participants": [item.to_dict() for item in self.participants],
            "is_foreshadowing": self.is_foreshadowing,
            "confidence": self.confidence,
            "note": self.note,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalLink:
    """块内两个局部事件之间有正文依据的联系（不自动推导跨块因果）"""

    key: str
    from_event: str
    to_event: str
    kind: str
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "from": self.from_event,
            "to": self.to_event,
            "kind": self.kind,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalLabel:
    """块内一个段落的整段情绪标签（段号即锚点，段落本身就是证据）"""

    paragraph_id: int
    emotion: int
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "paragraph_id": self.paragraph_id,
            "emotion": self.emotion,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalMetricNote:
    """块内对章级指标给出的局部依据（摘要片段/情绪基调/叙事功能）"""

    key: str
    summary: str | None
    emotional_valence: int | None
    narrative_function: str | None
    pivot_moment: bool
    cliffhanger: bool
    evidence: tuple[LocalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "summary": self.summary,
            "emotional_valence": self.emotional_valence,
            "narrative_function": self.narrative_function,
            "pivot_moment": self.pivot_moment,
            "cliffhanger": self.cliffhanger,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class LocalPending:
    """块代理判不了、留给章节代理裁决的待决项

    case_clue 可带 case_id：块内 search_pool 命中的案例编号在块账本里翻成案例 id
    存这里（编号是会话局部的，跨面只有 id 可传），章面按 id 重新登记自己的编号。
    """

    key: str
    kind: str
    detail: str
    evidence: tuple[LocalEvidence, ...]
    handles: list[str]
    case_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """用于渲染明细视图"""
        return {
            "kind": self.kind,
            "detail": self.detail,
            "handles": list(self.handles),
            "case_id": self.case_id,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class BlockAnnotation:
    """一个块代理会话产出的全部局部标注（内存对象，章面按句柄读取）

    会话结束时为空也是合法产出：块内确实没有可标注内容时不要求造假。
    """

    block_index: int
    block_chunk_id: int
    block_text: str
    mentions: list[LocalMention] = field(default_factory=list)
    relations: list[LocalRelation] = field(default_factory=list)
    dialogues: list[LocalDialogue] = field(default_factory=list)
    events: list[LocalEvent] = field(default_factory=list)
    links: list[LocalLink] = field(default_factory=list)
    labels: list[LocalLabel] = field(default_factory=list)
    metric_notes: list[LocalMetricNote] = field(default_factory=list)
    pending: list[LocalPending] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def handle_prefix(self) -> str:
        """用于生成块内句柄前缀（B1、B2 …，1 基块序）"""
        return f"B{self.block_index + 1}"

    def handle(self, key: str) -> str:
        """用于把块内键渲染成章面可见句柄"""
        return f"{self.handle_prefix}:{key}"

    def keys_of(self, kind: str) -> dict[str, Any]:
        """用于按类别取块内对象表（章面的悬空引用与冲突检测共用）"""
        return {item.key: item for item in getattr(self, kind)}

    def index(self) -> dict[str, list[dict[str, Any]]]:
        """用于渲染章面首条消息的紧凑对象索引（只给定位所需字段，明细按句柄读）"""
        return {
            "mentions": [
                {
                    "handle": self.handle(item.key),
                    "name": item.name,
                    "entity_type": item.entity_type,
                    "tags": list(item.tags),
                    "evidence_paragraphs": [entry.paragraph_id for entry in item.evidence],
                }
                for item in self.mentions
            ],
            "relations": [
                {
                    "handle": self.handle(item.key),
                    "from": self.handle(item.from_ref),
                    "to": self.handle(item.to_ref),
                    "relation_type": item.relation_type,
                }
                for item in self.relations
            ],
            "dialogues": [
                {
                    "handle": self.handle(item.key),
                    "candidate_index": item.candidate_index,
                    "verdict": item.verdict,
                    "speaker": self.handle(item.speaker) if item.speaker else None,
                    "tone": item.tone,
                }
                for item in self.dialogues
            ],
            "events": [
                {
                    "handle": self.handle(item.key),
                    "description": item.description,
                    "is_foreshadowing": item.is_foreshadowing,
                    "confidence": item.confidence,
                    "participants": [
                        {
                            "entity": self.handle(part.entity),
                            "role": part.role,
                            "narrative_role": part.narrative_role,
                            "action": part.action,
                            "emotion": part.emotion,
                        }
                        for part in item.participants
                    ],
                }
                for item in self.events
            ],
            "links": [
                {
                    "handle": self.handle(item.key),
                    "from": self.handle(item.from_event),
                    "to": self.handle(item.to_event),
                    "kind": item.kind,
                }
                for item in self.links
            ],
            "labels": [
                {"paragraph_id": item.paragraph_id, "emotion": item.emotion} for item in self.labels
            ],
            "metric_notes": [
                {
                    "handle": self.handle(item.key),
                    "summary": item.summary,
                    "emotional_valence": item.emotional_valence,
                    "narrative_function": item.narrative_function,
                    "pivot_moment": item.pivot_moment,
                    "cliffhanger": item.cliffhanger,
                }
                for item in self.metric_notes
            ],
            "pending": [
                {"handle": self.handle(item.key), "kind": item.kind, "detail": item.detail}
                for item in self.pending
            ],
        }

    def counts(self) -> dict[str, int]:
        """用于回执与统计口径的各类计数"""
        return {
            "mentions": len(self.mentions),
            "relations": len(self.relations),
            "dialogues": len(self.dialogues),
            "events": len(self.events),
            "links": len(self.links),
            "labels": len(self.labels),
            "metric_notes": len(self.metric_notes),
            "pending": len(self.pending),
        }

    def resolve(self, handle: str) -> dict[str, Any] | None:
        """用于按句柄读取单条明细（句柄必须属于本块，未知句柄返回 None）

        块内引用一律以句柄形态出去：章面只认 B<n>:<key> 这一套寻址，块内短键不外露。
        """
        prefix, _, key = handle.partition(":")
        if prefix != self.handle_prefix or not key:
            return None
        for kind in ("mentions", "relations", "dialogues", "events", "links", "metric_notes", "pending"):
            item = self.keys_of(kind).get(key)
            if item is not None:
                return {"kind": kind, "handle": handle, **self.expand(kind, item.to_dict())}
        if key.startswith("label-") and key[len("label-") :].isdigit():
            paragraph_id = int(key[len("label-") :])
            for label in self.labels:
                if label.paragraph_id == paragraph_id:
                    return {"kind": "labels", "handle": handle, **label.to_dict()}
        return None

    def expand(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        """用于把明细里的块内短键引用统一渲染成句柄（单点转换，明细与索引同一口径）"""
        rendered = dict(body)
        if kind == "relations":
            rendered["from"] = self.handle(str(body.get("from")))
            rendered["to"] = self.handle(str(body.get("to")))
        elif kind == "dialogues":
            speaker = body.get("speaker")
            rendered["speaker"] = self.handle(str(speaker)) if speaker else None
        elif kind == "links":
            rendered["from"] = self.handle(str(body.get("from")))
            rendered["to"] = self.handle(str(body.get("to")))
        elif kind == "events":
            participants = []
            for part in body.get("participants") or []:
                item = dict(part)
                item["entity"] = self.handle(str(part.get("entity")))
                participants.append(item)
            rendered["participants"] = participants
        return rendered

    def dangling_references(self) -> list[str]:
        """用于列出块内悬空引用（会话结束时复核，悬空即块失败）"""
        mention_keys = {item.key for item in self.mentions}
        event_keys = {item.key for item in self.events}
        dangling: list[str] = []
        for relation in self.relations:
            for endpoint in (relation.from_ref, relation.to_ref):
                if endpoint not in mention_keys:
                    dangling.append(f"{self.handle(relation.key)} 端点 {endpoint}")
        for dialogue in self.dialogues:
            if dialogue.speaker and dialogue.speaker not in mention_keys:
                dangling.append(f"{self.handle(dialogue.key)} 说话人 {dialogue.speaker}")
        for event in self.events:
            for part in event.participants:
                if part.entity not in mention_keys:
                    dangling.append(f"{self.handle(event.key)} 参与者 {part.entity}")
        for link in self.links:
            for endpoint in (link.from_event, link.to_event):
                if endpoint not in event_keys:
                    dangling.append(f"{self.handle(link.key)} 端点 {endpoint}")
        for item in self.pending:
            for handle in item.handles:
                prefix, _, key = handle.partition(":")
                if prefix == self.handle_prefix and key not in mention_keys and key not in event_keys:
                    dangling.append(f"{self.handle(item.key)} 引用 {handle}")
        return dangling

    def validate(self) -> None:
        """用于在会话结束时复核块内引用闭合（悬空引用即块失败，不走整章失败以外的新路径）"""
        dangling = self.dangling_references()
        if dangling:
            raise AnnotationStageRejection(
                "块内局部标注存在悬空引用：" + "；".join(dangling[:8]),
                record=self.handle_prefix,
                field="local_ir",
                code="dangling_reference",
                expected="引用的键必须是本块已构造对象的键（构造引用前先构造被引对象）",
            )


__all__ = [
    "DIALOGUE_VERDICTS",
    "ENTITY_TYPES",
    "LINK_KINDS",
    "NARRATIVE_FUNCTIONS",
    "PARTICIPANT_ROLES",
    "PENDING_KINDS",
    "RELATION_TYPES",
    "RUNTIME_ROLES",
    "TONE_VALUES",
    "BlockAnnotation",
    "LocalDialogue",
    "LocalEvent",
    "LocalEvidence",
    "LocalLabel",
    "LocalLink",
    "LocalMention",
    "LocalMetricNote",
    "LocalParticipant",
    "LocalPending",
    "LocalRelation",
    "normalize_evidence",
]
