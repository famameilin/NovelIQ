"""章内三代理并发：单个 agent 的局部标注

三个 agent 各持整章正文、各管一类产出、**互不通信**：结构 agent 交 entity/relation，
事件 agent 交 event/participants，证据 agent 交 dialogue/label/metric/pending；
实体引用写正文名字与大类，由运行时解析并自动登记；事件用 el 路径，对话用候选号；
每条记录自带 evidence=段首可见号，构造当场只校验"号在本章且存在"；
闭集词表一律从 schema.py / tools.py 单源引用，本模块不复制任何词表。

**本模块的数据类只承载"这个 agent 已经写成了什么"**：构造器先经生产单条事务边界写入，
成功后才把记录落进这里。所以本模块的列表既是进度账本，也是后续引用的唯一依据——
引用一个没写成功的键，构造器当场结构化拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.event_trees.vocabulary import (
    EventChildType,
    EventParticipantRole,
)
from src.fact_graph.inputs import EntityNameRef
from src.fact_graph.vocabulary import (
    RELATION_DEFINITIONS,
    Confidence,
    DialogueVerdict,
    EntityType,
    NarrativeFunction,
    RoleFunction,
    Tone,
)

from .ir_validation import _reject, _require_paragraph_id

# 章内 agent 的角色名：长章开三条职责 agent 并发（短章走整章 annotation 路径；
# 职责范围文案在 prompts.AGENT_ROLE_SCOPES）

# 待决项类型：agent 判不了、要留给案例池/后续章节的事项
PENDING_KINDS: dict[str, str] = {
    "unresolved_reference": "引用无法解析（正文里的人名/称号在本章找不到对应实体）",
    "event_continuation": "事件延续（本章事件像是既有事件树某节点的后继或同一事件的两段）",
    "case_clue": "案例线索（疑似伏笔/疑点，交案例池统一裁决）",
    "other": "其他需要统一裁决的事项",
}

# 闭集词表单源：全部从 schema/tools 的枚举与注册表派生，三个 agent 的报错文案共用
ENTITY_TYPES: tuple[str, ...] = tuple(member.value for member in EntityType)
DIALOGUE_VERDICTS: tuple[str, ...] = tuple(member.value for member in DialogueVerdict)
TONE_VALUES: tuple[str, ...] = tuple(member.value for member in Tone)
PARTICIPANT_ROLES: tuple[str, ...] = tuple(member.value for member in EventParticipantRole)
RUNTIME_ROLES: tuple[str, ...] = tuple(member.value for member in RoleFunction)
NARRATIVE_FUNCTIONS: tuple[str, ...] = tuple(member.value for member in NarrativeFunction)
EVENT_CHILD_TYPES: tuple[str, ...] = tuple(member.value for member in EventChildType)
CONFIDENCE_VALUES: tuple[str, ...] = tuple(member.value for member in Confidence)
RELATION_TYPES: tuple[str, ...] = tuple(RELATION_DEFINITIONS)

# el 层级路径与角色命名空间分隔符的权威定义在 schema；落库 el 一律按 `角色:局部键`
# 命名空间化（见 namespace_el），本模块只用于核验落库形态

# 待决项种类 → 案例池 type（案例池的 type 是自由文本，这里是唯一的机械映射处；
# 构造器与连接层共用同一份，疑点入池与写法分歧入池口径只有一处）
PENDING_CASE_TYPES: dict[str, str] = {
    "unresolved_reference": "实体别名待核",
    "event_continuation": "事件延续待核",
    "case_clue": "伏笔疑点",
    "other": "其他疑点",
}

# 案例 description 上限（案例池列约束：人类可读说明 ≤100 字）


@dataclass(frozen=True, slots=True)
class AgentEvidence:
    """按 id 锚定的一条证据（段首可见号，正文每段开头的 `N：` 里的 N）"""

    paragraph_id: int

    def to_dict(self) -> dict[str, Any]:
        """用于渲染成模型可见的证据视图"""
        return {"paragraph_id": self.paragraph_id}


def normalize_evidence(
    raw: Any,
    *,
    record: str,
    paragraph_text_by_id: dict[int, str],
    field_name: str = "evidence",
    required: bool = True,
) -> tuple[AgentEvidence, ...]:
    """用于把模型提交的证据归一成按 id 锚定的 AgentEvidence（不合格即结构化拒绝）

    只按 id 锚定：evidence 是**单个段首可见号整数**，校验只要求"号在本章且存在"
    （服务端按号取段），不逐字比对引文。给成数组（多号）或号越界时结构化拒绝，
    并在 expected 里列出合法号范围 1..N。
    """
    if raw is None or raw == []:
        if not required:
            return ()
        raise _reject(
            f"{record} 缺少 {field_name}",
            record=record,
            field=field_name,
            code="missing_evidence",
            expected=f"单个段首可见号整数（正文每段开头的 `N：`，范围 1..{len(paragraph_text_by_id)}）",
        )
    if isinstance(raw, bool) or not isinstance(raw, int):
        code = "multiple_evidence_ids" if isinstance(raw, (list, tuple)) else "invalid_value"
        raise _reject(
            f"{field_name} 只接受单个段首可见号整数：{raw!r}",
            record=record,
            field=field_name,
            code=code,
            expected=f"单个段首可见号整数（正文每段开头的 `N：`，范围 1..{len(paragraph_text_by_id)}）",
        )
    _require_paragraph_id(
        raw,
        record=record,
        field_name=field_name,
        paragraph_text_by_id=paragraph_text_by_id,
    )
    return (AgentEvidence(paragraph_id=raw),)


def _evidence_view(evidence: tuple[AgentEvidence, ...]) -> list[dict[str, Any]]:
    """用于渲染证据列表（回执与审计用）"""
    return [entry.to_dict() for entry in evidence]


@dataclass(slots=True)
class AgentEntity:
    """结构 agent 登记的一个实体（id=富登记锚点键，name=正文名字）"""

    id: str
    name: str
    entity_type: str
    tags: list[str] = field(default_factory=list)
    description: str | None = None
    representative: bool | None = None
    evidence: tuple[AgentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "tags": list(self.tags),
            "description": self.description,
            "representative": self.representative,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class AgentRelation:
    """结构 agent 写的一条闭合关系边（两端写正文名字与大类）

    本章只确认局部关系（建边），不携带 change_kind 关系变化——跨章关系变化由
    write_link 关联工具承担。
    """

    from_entity: EntityNameRef
    to_entity: EntityNameRef
    relation_type: str
    evidence: tuple[AgentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "from_entity": self.from_entity.model_dump(mode="json"),
            "to_entity": self.to_entity.model_dump(mode="json"),
            "relation_type": self.relation_type,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class AgentParticipant:
    """事件 agent 挂到一个事件节点上的参与者（名字与大类由运行时自动登记）

    role/narrative_role/action/emotion 均可缺省——role 未知词与
    缺省由生产面按实体登记大类给默认，叙事功能近义词归一、情绪分值钳制在构造层完成。
    """

    name: str
    entity_type: str
    role: str | None = None
    narrative_role: str | None = None
    action: str | None = None
    emotion: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "name": self.name,
            "entity_type": self.entity_type,
            "role": self.role,
            "narrative_role": self.narrative_role,
            "action": self.action,
            "emotion": self.emotion,
        }


@dataclass(slots=True)
class AgentEvent:
    """事件 agent 写的一个事件节点（el 层级路径表达树形，树内先后=调用顺序）"""

    el: str
    isroot: bool
    description: str
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    progress: str | None = None
    isforeshadowing: bool = False
    confidence: str | None = None
    node_type: str | None = None
    participants: list[AgentParticipant] = field(default_factory=list)
    evidence: tuple[AgentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "el": self.el,
            "isroot": self.isroot,
            "description": self.description,
            "title": self.title,
            "problem": self.problem,
            "summary": self.summary,
            "event_type": self.event_type,
            "status": self.status,
            "progress": self.progress,
            "isforeshadowing": self.isforeshadowing,
            "confidence": self.confidence,
            "type": self.node_type,
            "participants": [item.to_dict() for item in self.participants],
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class AgentDialogue:
    """证据 agent 对一条对话候选的判定（说话人写正文名字与 character 大类）"""

    candidate_index: int
    verdict: str
    speaker: EntityNameRef | None = None
    tone: str | None = None
    evidence: tuple[AgentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "candidate_index": self.candidate_index,
            "verdict": self.verdict,
            "speaker": self.speaker.model_dump(mode="json") if self.speaker else None,
            "tone": self.tone,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class AgentLabel:
    """证据 agent 给一个段落打的整段情绪标签（段落号本身就是锚点，无引文）"""

    paragraph_id: int
    emotion: int

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {"paragraph_id": self.paragraph_id, "emotion": self.emotion}


@dataclass(slots=True)
class AgentMetric:
    """证据 agent 一次性提交的章级指标（整域一次提交，无引文）"""

    summary: str | None = None
    emotional_valence: int | None = None
    narrative_function: str | None = None
    pivot_moment: bool = False
    cliffhanger: bool = False

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "summary": self.summary,
            "emotional_valence": self.emotional_valence,
            "narrative_function": self.narrative_function,
            "pivot_moment": self.pivot_moment,
            "cliffhanger": self.cliffhanger,
        }


@dataclass(slots=True)
class AgentPending:
    """局部待决记录：显式归入案例类型 + 普通文字说明"""

    case_type: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"case_type": self.case_type, "description": self.description}


@dataclass(slots=True)
class AgentAnnotation:
    """一个 agent 的全部产出（构造器写入生效后落在它上面：本 agent 已写成的记录）

    记录按"自然键"去重（实体=本 agent id、事件=el、对话=候选号、标签=段首号、指标=整域），
    同键重写=更新语义，与正式写入同口径。
    """

    role: str
    chapter_label: str | None = None
    entities: list[AgentEntity] = field(default_factory=list)
    relations: list[AgentRelation] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    dialogues: list[AgentDialogue] = field(default_factory=list)
    labels: list[AgentLabel] = field(default_factory=list)
    metric: AgentMetric | None = None
    pending: list[AgentPending] = field(default_factory=list)
    plotlines: list[dict[str, Any]] = field(default_factory=list)
    foreshadow_actions: list[dict[str, Any]] = field(default_factory=list)
    coverage: tuple[int, ...] = ()
    finished: bool = False

    def event_keys(self) -> dict[str, AgentEvent]:
        """用于取本 agent 已构造的事件表（participants 引用校验用）"""
        return {item.el: item for item in self.events}

    def entity_ids(self) -> dict[str, AgentEntity]:
        """用于取本 agent 的实体引用表（relation/participants/dialogue/pending 引用校验用）"""
        return {item.id: item for item in self.entities}

    def counts(self) -> dict[str, int]:
        """用于回执里的各域进度（与正式写入的 progress 同形）"""
        return {
            "entities": len(self.entities),
            "relations": len(self.relations),
            "events": len(self.events),
            "dialogues": len(self.dialogues),
            "labels": len(self.labels),
            "metrics": 1 if self.metric is not None else 0,
            "pending": len(self.pending),
            "plotlines": len(self.plotlines),
            "foreshadow_actions": len(self.foreshadow_actions),
        }

    def index(self) -> dict[str, Any]:
        """用于渲染本 agent 产出的紧凑索引（日志与离线对照用）"""
        return {
            "role": self.role,
            "finished": self.finished,
            "counts": self.counts(),
            "entities": [item.to_dict() for item in self.entities],
            "relations": [item.to_dict() for item in self.relations],
            "events": [item.to_dict() for item in self.events],
            "dialogues": [item.to_dict() for item in self.dialogues],
            "labels": [item.to_dict() for item in self.labels],
            "metric": self.metric.to_dict() if self.metric is not None else None,
            "pending": [item.to_dict() for item in self.pending],
            "plotlines": list(self.plotlines),
            "foreshadow_actions": list(self.foreshadow_actions),
        }
