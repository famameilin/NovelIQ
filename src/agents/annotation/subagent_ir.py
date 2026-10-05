"""章内三代理并发：单个 subagent 的局部标注（内存对象，零新表零迁移）

设计（《章内多代理重设计-三代理并发版》§3.1/§4）：

- 三个 subagent 各持整章正文、各管一类产出、**互不通信**：结构 subagent 交 entity/relation，
  事件 subagent 交 event/participants，证据 subagent 交 dialogue/label/metric/pending；
- 引用一律**按 id**：实体由模型分配本 subagent 引用键（如 a1/a2…，name 只作展示字段），
  relation/participants/dialogue/pending 都写该 id；事件用 el 层级路径（根 t1、子 t1/e2）
  表达树形与先后，对话用候选号，标签用段首可见号——id 是本 subagent 局部的引用键，
  构造器把它命名空间化成落库 el（见 namespace_el）后立即写入，不再按名字会合；
- 每条记录自带 evidence=段首可见号（正文每段开头的 `N：` 里的 N），构造当场只校验
  "号在本章且存在"（多号/越界结构化拒绝并列出合法号范围），不再逐字比对引文；
- 闭集词表一律从 schema.py / tools.py 单源引用，本模块不复制任何词表。

**本模块的数据类只承载"这个 subagent 已经写成了什么"**：构造器先经生产单条事务边界写入，
成功后才把记录落进这里（写入生效）。所以本模块的列表既是进度账本，也是后续引用的
唯一依据——引用一个没写成功的键，构造器当场结构化拒绝。
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入（大文件拆分聚合面）。

# 创建时间：2026-10-02　创建者：Trae
# 任务：subagent_ir.py 大文件拆分——校验 helpers 段（namespace_* / truncate_case_description /
# _reject / _require_*）迁出至 ir_validation.py；本模块保留闭集常量与 IR 数据类并对迁出
# 符号 re-export（既有导入方零改动）。
# 说明：纯结构搬移，不改任何运行逻辑与签名。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import (
    EL_PATH_SEP,
    RELATION_DEFINITIONS,
    RESERVED_ROOT_KEY,
    Confidence,
    DialogueVerdict,
    EntityType,
    EventChildType,
    EventParticipantRole,
    NarrativeFunction,
    RoleFunction,
    Tone,
)

# 章内 subagent 的角色名：多块章开三条职责 subagent 并发（单块章走 runner 的
# agent 路径，不再有 solo 形态；职责范围文案在 prompts.SUBAGENT_ROLE_SCOPES）
SUBAGENT_ROLES: tuple[str, ...] = ("structure", "event", "evidence")

# 待决项类型：subagent 判不了、要留给案例池/后续章节的事项（§3.1 的 pending）
PENDING_KINDS: dict[str, str] = {
    "unresolved_reference": "引用无法解析（正文里的人名/称号在本章找不到对应实体）",
    "event_continuation": "事件延续（本章事件像是既有事件树某节点的后继或同一事件的两段）",
    "case_clue": "案例线索（疑似伏笔/疑点，交案例池统一裁决）",
    "other": "其他需要统一裁决的事项",
}

# 闭集词表单源：全部从 schema/tools 的枚举与注册表派生，三个 subagent 的报错文案共用
ENTITY_TYPES: tuple[str, ...] = tuple(member.value for member in EntityType)
DIALOGUE_VERDICTS: tuple[str, ...] = tuple(member.value for member in DialogueVerdict)
TONE_VALUES: tuple[str, ...] = tuple(member.value for member in Tone)
PARTICIPANT_ROLES: tuple[str, ...] = tuple(member.value for member in EventParticipantRole)
RUNTIME_ROLES: tuple[str, ...] = tuple(member.value for member in RoleFunction)
NARRATIVE_FUNCTIONS: tuple[str, ...] = tuple(member.value for member in NarrativeFunction)
EVENT_CHILD_TYPES: tuple[str, ...] = tuple(member.value for member in EventChildType)
CONFIDENCE_VALUES: tuple[str, ...] = tuple(member.value for member in Confidence)
RELATION_TYPES: tuple[str, ...] = tuple(RELATION_DEFINITIONS)

# el 层级路径分隔符与根事件保留节点键：权威定义在 schema（与正式写入的事件账本同源：
# 根=树键、子=树键/节点键；本模块只用于核验落库形态）
# 角色命名空间分隔符：subagent 的引用键是各自局部的（三个 subagent 都可能用 a1/t1），
# 落库 el 一律按 `角色:局部键` 命名空间化，避免同名键互相占用（见 namespace_el）
ROLE_NAMESPACE_SEP = ":"

# 待决项种类 → 案例池 type（案例池的 type 是自由文本，这里是唯一的机械映射处；
# 构造器与连接层共用同一份，疑点入池与写法分歧入池口径只有一处）
PENDING_CASE_TYPES: dict[str, str] = {
    "unresolved_reference": "实体别名待核",
    "event_continuation": "事件延续待核",
    "case_clue": "伏笔疑点",
    "other": "其他疑点",
}

# 案例 description 上限（案例池列约束：人类可读说明 ≤100 字）
CASE_DESCRIPTION_MAX_CHARS = 100


@dataclass(frozen=True, slots=True)
class SubagentEvidence:
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
) -> tuple[SubagentEvidence, ...]:
    """用于把模型提交的证据归一成按 id 锚定的 SubagentEvidence（不合格即结构化拒绝）

    只按 id 锚定：evidence 是**单个段首可见号整数**，校验只要求"号在本章且存在"
    （服务端按号取段），不再逐字比对引文。给成数组（多号）或号越界时结构化拒绝，
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
    return (SubagentEvidence(paragraph_id=raw),)


def _evidence_view(evidence: tuple[SubagentEvidence, ...]) -> list[dict[str, Any]]:
    """用于渲染证据列表（回执与审计用）"""
    return [entry.to_dict() for entry in evidence]


@dataclass(slots=True)
class SubagentEntity:
    """结构 subagent 登记的一个实体（id=本 subagent 引用键，name 只作展示字段）"""

    id: str
    name: str
    entity_type: str
    tags: list[str] = field(default_factory=list)
    description: str | None = None
    attributes: dict[str, Any] | None = None
    evidence: tuple[SubagentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "tags": list(self.tags),
            "description": self.description,
            "attributes": self.attributes,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class SubagentRelation:
    """结构 subagent 写的一条闭合关系边（两端写本 subagent 已登记的实体 id）

    2026-10-02 对齐 0.2.0 写面：本章只确认局部关系（建边），不再携带 change_kind
    关系变化——跨章关系变化由 write_link 关联工具承担。
    """

    from_id: str
    to_id: str
    relation_type: str
    evidence: tuple[SubagentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "relation_type": self.relation_type,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class SubagentParticipant:
    """事件 subagent 挂到一个事件节点上的参与者（entity_id 写本 subagent 已登记的实体 id）

    2026-10-04 合同放开：role/narrative_role/action/emotion 均可缺省——role 未知词与
    缺省由生产面按实体登记大类给默认，叙事功能近义词归一、情绪分值钳制在构造层完成。
    """

    entity_id: str
    role: str | None = None
    narrative_role: str | None = None
    action: str | None = None
    emotion: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "entity_id": self.entity_id,
            "role": self.role,
            "narrative_role": self.narrative_role,
            "action": self.action,
            "emotion": self.emotion,
        }


@dataclass(slots=True)
class SubagentEvent:
    """事件 subagent 写的一个事件节点（el 层级路径表达树形，树内先后=调用顺序）"""

    el: str
    isroot: bool
    description: str
    isforeshadowing: bool = False
    confidence: str | None = None
    node_type: str | None = None
    participants: list[SubagentParticipant] = field(default_factory=list)
    evidence: tuple[SubagentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "el": self.el,
            "isroot": self.isroot,
            "description": self.description,
            "isforeshadowing": self.isforeshadowing,
            "confidence": self.confidence,
            "type": self.node_type,
            "participants": [item.to_dict() for item in self.participants],
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class SubagentDialogue:
    """证据 subagent 对一条对话候选的判定（说话人写本 subagent 已登记的实体 id）"""

    candidate_index: int
    verdict: str
    speaker_id: str | None = None
    tone: str | None = None
    evidence: tuple[SubagentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "candidate_index": self.candidate_index,
            "verdict": self.verdict,
            "speaker_id": self.speaker_id,
            "tone": self.tone,
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class SubagentLabel:
    """证据 subagent 给一个段落打的整段情绪标签（段落号本身就是锚点，无引文）"""

    paragraph_id: int
    emotion: int

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {"paragraph_id": self.paragraph_id, "emotion": self.emotion}


@dataclass(slots=True)
class SubagentMetric:
    """证据 subagent 一次性提交的章级指标（整域一次提交，无引文）"""

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
class SubagentPending:
    """一条判不了的疑点（keys 写本 subagent 已登记的实体 id，构造器当场解析成登记名入池）

    2026-10-02 对齐 0.2.0 案例面：search_pool 检索已随案例裁决机器退役，
    case_id 授权随之移除，疑点只登记不指向既有案例。
    """

    kind: str
    detail: str
    keys: list[str] = field(default_factory=list)
    evidence: tuple[SubagentEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """用于渲染记录明细"""
        return {
            "kind": self.kind,
            "detail": self.detail,
            "keys": list(self.keys),
            "evidence": _evidence_view(self.evidence),
        }


@dataclass(slots=True)
class SubagentAnnotation:
    """一个 subagent 的全部产出（构造器写入生效后落在它上面：本 subagent 已写成的记录）

    记录按"自然键"去重（实体=本 subagent id、事件=el、对话=候选号、标签=段首号、指标=整域），
    同键重写=更新语义，与正式写入同口径。
    """

    role: str
    chapter_label: str | None = None
    entities: list[SubagentEntity] = field(default_factory=list)
    relations: list[SubagentRelation] = field(default_factory=list)
    events: list[SubagentEvent] = field(default_factory=list)
    dialogues: list[SubagentDialogue] = field(default_factory=list)
    labels: list[SubagentLabel] = field(default_factory=list)
    metric: SubagentMetric | None = None
    pending: list[SubagentPending] = field(default_factory=list)
    coverage: tuple[int, ...] = ()
    finished: bool = False

    def event_keys(self) -> dict[str, SubagentEvent]:
        """用于取本 subagent 已构造的事件表（participants 引用校验用）"""
        return {item.el: item for item in self.events}

    def entity_ids(self) -> dict[str, SubagentEntity]:
        """用于取本 subagent 的实体引用表（relation/participants/dialogue/pending 引用校验用）"""
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
        }

    def index(self) -> dict[str, Any]:
        """用于渲染本 subagent 产出的紧凑索引（日志与离线对照用）"""
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
        }


# 校验 helpers 迁至 ir_validation（闭集常量与数据类保留在本模块，供其引用）：
# 置于文件末尾 re-export，两个方向的首次导入都安全（双方定义先于引用）。
from .ir_validation import (  # noqa: E402
    _reject as _reject,
)
from .ir_validation import (
    _require_enum as _require_enum,
)
from .ir_validation import (
    _require_local_key as _require_local_key,
)
from .ir_validation import (
    _require_name as _require_name,
)
from .ir_validation import (
    _require_paragraph_id as _require_paragraph_id,
)
from .ir_validation import (
    _require_score as _require_score,
)
from .ir_validation import (
    _require_text as _require_text,
)
from .ir_validation import (
    namespace_el as namespace_el,
)
from .ir_validation import (
    namespace_event_el as namespace_event_el,
)
from .ir_validation import (
    truncate_case_description as truncate_case_description,
)

__all__ = [
    "CASE_DESCRIPTION_MAX_CHARS",
    "CONFIDENCE_VALUES",
    "DIALOGUE_VERDICTS",
    "EL_PATH_SEP",
    "ENTITY_TYPES",
    "EVENT_CHILD_TYPES",
    "PENDING_CASE_TYPES",
    "RESERVED_ROOT_KEY",
    "ROLE_NAMESPACE_SEP",
    "SubagentAnnotation",
    "SubagentDialogue",
    "SubagentEntity",
    "SubagentEvent",
    "SubagentEvidence",
    "SubagentLabel",
    "SubagentMetric",
    "SubagentParticipant",
    "SubagentPending",
    "SubagentRelation",
    "NARRATIVE_FUNCTIONS",
    "PARTICIPANT_ROLES",
    "PENDING_KINDS",
    "RELATION_TYPES",
    "RESERVED_ROOT_KEY",
    "RUNTIME_ROLES",
    "SUBAGENT_ROLES",
    "TONE_VALUES",
    "_evidence_view",
    "_reject",
    "_require_enum",
    "_require_local_key",
    "_require_name",
    "_require_paragraph_id",
    "_require_score",
    "_require_text",
    "normalize_evidence",
]
