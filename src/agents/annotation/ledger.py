"""
章节标注语义写入系统账本：单章领域写入与系统绑定状态
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from src.agents.annotation.ir_contract import ROLE_NAMESPACE_SEP
from src.event_trees.models import (
    BoundEvent,
    ParticipantArg,
)
from src.event_trees.vocabulary import (
    EventChildType,
)
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import (
    ChapterMetricsInput,
    ChapterParagraphInfo,
    DialogueCandidate,
    DialogueInput,
    EntityDirectoryInput,
    EntityInput,
    RelationInput,
)
from src.fact_graph.outputs import BoundCharacterObservation
from src.fact_graph.schema import EL_PATH_SEP, RESERVED_ROOT_KEY
from src.fact_graph.vocabulary import Confidence, DialogueVerdict, EntityType, RelationType, Tone

from .candidates import extract_dialogue_candidates
from .errors import (
    AnnotationInputError,
    AnnotationInvariantError,
    AnnotationProtocolError,
    AnnotationStageRejection,
)
from .state_dialogue import DialogueEvidenceState
from .state_entities import EntityRelationState
from .state_events import EventBindingState
from .state_metrics import ChapterMetricsState

# 2026-09-07 监督标签冻结软下限（每章 2-3 段定稿）：低于 2 留痕覆盖告警，不阻断冻结

# 引用被拒时回执里列几个本章已登记实体（"el=名字"对照）；超出部分只报总数，
# 拒绝回执要能一眼读完（全章几十个实体时不铺开）
_ENTITY_REF_HINT_LIMIT = 12


@dataclass(slots=True)
class AnnotationToolLedger:
    """2026-08-07 用于保存单章领域写入和系统绑定状态

    2026-09-13 实时写入：模型面的每个小调用即时落到目标结构（written_*），
    全部写完后由唯一 finish 收尾冻结，没有暂存区也没有逐域结束声明。
    2026-09-19 章即块：原 章级字段退役，账本只认章（current_chapter_id/text）。
    """

    run_scope: str
    current_chapter_id: int
    current_chapter_text: str
    allow_future_context: bool
    entities: EntityRelationState = field(default_factory=EntityRelationState, init=False)
    events: EventBindingState = field(default_factory=EventBindingState, init=False)
    dialogue: DialogueEvidenceState = field(default_factory=DialogueEvidenceState, init=False)
    metrics: ChapterMetricsState = field(default_factory=ChapterMetricsState, init=False)
    phase: str = "chapter_open"
    write_records: list[dict[str, Any]] = field(default_factory=list)
    # 2026-08-30：search_text 返回正文时登记真实 SQL 命中段落
    shared_entity_ids: set[str] = field(default_factory=set)
    # 2026-09-05 冻结时系统确定性覆盖告警（仅留痕不阻断），随章持久化
    coverage_warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    search_log: list[dict[str, Any]] = field(default_factory=list)
    graph: FactGraph | None = None
    # 2026-08-18 事件森林/DAG：本章 的段落坐标映射，用于事件锚点校验和证据派生
    paragraph_info: ChapterParagraphInfo | None = None
    # 只登记本章已写出的事件节点
    # 2026-08-19 当前章节序号（写章指标与上下文摘要展示用）
    current_chapter_order: int | None = None
    # 本章事件树状态，跨章引用只授权精确原文
    # 2026-09-13 实时写入（取消暂存）：每次小调用即时落到目标结构，回执即当前真相。
    # 全部进 snapshot/restore——单次调用失败只回滚该调用，之前写入的记录必须保留
    # 有序对 → 关系记录（同一对端点换类型即整体替换，保持"本章关系=完整集合"语义）
    # 人物动态状态按记录键持有（重写同一参与者即更新，键给回执定位用）
    # tree_key → tree_id：章内局部键是模型侧寻址面，真实 uuid 不外露
    # 2026-10-04 树键校验下沉：tree_key → 暂挂子事件（先于根到达时缓存，建根按到达序
    # 冲账；finish 时仍有暂挂即拒，防止静默丢数据）
    # 2026-09-14 实体局部键索引：el → 归一化登记名（模型自定、写入即绑定、同轮可用）
    # 2026-09-18 本章已经写出来的记录键集合（程序面每次调用成功即登记）：
    # push_case 的 record_id 按它校验，模型只能指向真实产出
    written_record_keys: set[str] = field(default_factory=set)
    # 2026-09-13 收尾声明：唯一 finish 置位后由系统冻结当前章
    chapter_finished: bool = False

    work_id: str = ""
    invocation_id: str = ""
    role: str = "solo"
    invoke_tool: Any = None
    finish_work: Any = None

    @property
    def written_entities(self) -> dict[str, EntityInput]:
        return self.entities.written_entities

    @written_entities.setter
    def written_entities(self, value: dict[str, EntityInput]) -> None:
        self.entities.written_entities = value

    @property
    def written_relations(self) -> dict[tuple[str, str], RelationInput]:
        return self.entities.written_relations

    @written_relations.setter
    def written_relations(self, value: dict[tuple[str, str], RelationInput]) -> None:
        self.entities.written_relations = value

    @property
    def entity_el_index(self) -> dict[str, str]:
        return self.entities.entity_el_index

    @entity_el_index.setter
    def entity_el_index(self, value: dict[str, str]) -> None:
        self.entities.entity_el_index = value

    @property
    def authorized_event_ids(self) -> set[str]:
        return self.events.authorized_event_ids

    @authorized_event_ids.setter
    def authorized_event_ids(self, value: set[str]) -> None:
        self.events.authorized_event_ids = value

    @property
    def event_trees(self) -> dict[str, dict[str, Any]]:
        return self.events.event_trees

    @event_trees.setter
    def event_trees(self, value: dict[str, dict[str, Any]]) -> None:
        self.events.event_trees = value

    @property
    def tree_key_index(self) -> dict[str, str]:
        return self.events.tree_key_index

    @tree_key_index.setter
    def tree_key_index(self, value: dict[str, str]) -> None:
        self.events.tree_key_index = value

    @property
    def pending_child_events(self) -> dict[str, list[dict[str, Any]]]:
        return self.events.pending_child_events

    @pending_child_events.setter
    def pending_child_events(self, value: dict[str, list[dict[str, Any]]]) -> None:
        self.events.pending_child_events = value

    @property
    def observation_by_record(self) -> dict[str, BoundCharacterObservation]:
        return self.events.observation_by_record

    @observation_by_record.setter
    def observation_by_record(self, value: dict[str, BoundCharacterObservation]) -> None:
        self.events.observation_by_record = value

    @property
    def dialogue_candidates(self) -> list[DialogueCandidate]:
        return self.dialogue.dialogue_candidates

    @dialogue_candidates.setter
    def dialogue_candidates(self, value: list[DialogueCandidate]) -> None:
        self.dialogue.dialogue_candidates = value

    @property
    def written_dialogues(self) -> dict[int, DialogueInput]:
        return self.dialogue.written_dialogues

    @written_dialogues.setter
    def written_dialogues(self, value: dict[int, DialogueInput]) -> None:
        self.dialogue.written_dialogues = value

    @property
    def authorized_text_paragraph_ids(self) -> set[int]:
        return self.dialogue.authorized_text_paragraph_ids

    @authorized_text_paragraph_ids.setter
    def authorized_text_paragraph_ids(self, value: set[int]) -> None:
        self.dialogue.authorized_text_paragraph_ids = value

    @property
    def text_references(self) -> dict[str, Any]:
        return self.dialogue.text_references

    @text_references.setter
    def text_references(self, value: dict[str, Any]) -> None:
        self.dialogue.text_references = value

    @property
    def source_anchors(self) -> dict[str, list[Any]]:
        return self.dialogue.source_anchors

    @source_anchors.setter
    def source_anchors(self, value: dict[str, list[Any]]) -> None:
        self.dialogue.source_anchors = value

    @property
    def metrics_payload(self) -> ChapterMetricsInput | None:
        return self.metrics.metrics_payload

    @metrics_payload.setter
    def metrics_payload(self, value: ChapterMetricsInput | None) -> None:
        self.metrics.metrics_payload = value

    @property
    def domain_payloads(self) -> dict[str, Any]:
        """只装配四个工作状态的当前输出；业务状态由各状态对象持有"""
        return {
            **self.entities.domain_payloads,
            **self.events.domain_payloads,
            **self.dialogue.domain_payloads,
            **self.metrics.domain_payloads,
        }

    @property
    def bound_payloads(self) -> dict[str, Any]:
        """只装配四个工作状态的当前输出；业务状态由各状态对象持有"""
        return {
            **self.entities.bound_payloads,
            **self.events.bound_payloads,
            **self.dialogue.bound_payloads,
            **self.metrics.bound_payloads,
        }

    def __post_init__(self) -> None:
        """2026-08-07 用于初始化唯一章的对话候选"""
        if not self.current_chapter_text.strip():
            raise AnnotationInputError("current_chapter_text 不能为空")
        self.dialogue_candidates = extract_dialogue_candidates(
            self.current_chapter_id,
            self.current_chapter_text,
        )

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于同步 LangGraph 和工具账本阶段"""
        self.phase = phase

    def snapshot(self) -> dict[str, Any]:
        """每次工具调用保存四状态的同一快照，失败只恢复本次调用"""
        return deepcopy(
            {
                "phase": self.phase,
                "chapter_finished": self.chapter_finished,
                "write_records": self.write_records,
                "search_log": self.search_log,
                "written_record_keys": self.written_record_keys,
                "entities": self.entities,
                "events": self.events,
                "dialogue": self.dialogue,
                "metrics": self.metrics,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-10 用于在单个工具调用失败时恢复该调用开始前的账本状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

    def resolve_entity_ref(self, ref: str, *, record: str, field: str) -> str:
        """2026-09-14 用于把模型面实体引用（run 级 uuid id / 自定 el）解析成登记名

        两种键空间同一条解析路径：字符串先查本章 的 el 索引，未命中再按
        uuid 反查图登记（uuid5 确定性 id）；未知的 id/el 结构化拒绝并列出已知键。
        """
        if self.graph is None:
            raise AnnotationInvariantError("实体引用解析需要常驻事实图，graph 缺失")
        key = self.entity_el_index.get(str(ref).strip())
        if key is not None:
            display_name = self.graph.entity_names.get(key)
            if display_name is None:
                raise AnnotationStageRejection(
                    f"el 指向的实体尚未入图: {ref}",
                    record=record,
                    field=field,
                    code="unregistered",
                    expected="先用 write_entity 登记该实体（el 在登记当场绑定）",
                )
            return display_name
        try:
            return self.graph.resolve_entity_id(str(ref).strip(), label=f"{record}.{field}")
        except ValueError as exc:
            raise AnnotationStageRejection(
                str(exc),
                record=record,
                field=field,
                code="unknown_entity_id",
                expected=(
                    "本章已登记实体的 run 级 id（write_entity 回执）或本章自定的 el 键；"
                    f"本章已登记：{self._registered_el_pairs()}"
                ),
            ) from None

    def _registered_el_pairs(self) -> str:
        """2026-09-20 用于把本章已登记的 el=名字 对渲染成一行（引用被拒时的就地自纠材料）

        run 54a72932：135 次把实体名称当引用填，而拒绝回执只给 uuid 示例——名称到 uuid
        要跨一层翻译，模型干脆照原样重试。这里给的是"名字 ↔ 可直接填的 el 键"的对照。
        """
        rows = self.entity_ledger()
        rendered = "、".join(f"{row['el']}={row['name']}" for row in rows[:_ENTITY_REF_HINT_LIMIT])
        if len(rows) > _ENTITY_REF_HINT_LIMIT:
            rendered += f" 等 {len(rows)} 个"
        return rendered or "（本章还没有登记实体）"

    def _tree_id(self, tree_key: str) -> str:
        return self.events._tree_id(self, tree_key)

    def _node_id(self, tree_key: str, node_key: str) -> str:
        return self.events._node_id(self, tree_key, node_key)

    # ------------------------------------------------------------------
    # 实时写入：每个小调用即时落到目标结构，回执即当前真相（2026-09-13 取消暂存区）
    # ------------------------------------------------------------------

    def _require_writable(self, record: str) -> None:
        """用于在每个写入入口统一校验阶段（章冻结后不再接受写入）"""
        if self.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许写入正式标注")

    def _bound_event(self, node_id: str) -> BoundEvent:
        return self.events._bound_event(node_id)

    # ------------------------------------------------------------------
    # 实体域：登记即入图并绑定 run 级 uuid id；el 局部键当场绑定，同轮可用

    def apply_entity(self, entity: EntityInput, *, el: str, present: set[str] | None = None) -> str:
        return self.entities.apply_entity(self, entity, el=el, present=present)

    # ------------------------------------------------------------------
    # 指标域：整域一次提交，重复提交按最后一次为准；段落级监督标签随本域提交

    def apply_metrics(self, payload: ChapterMetricsInput) -> None:
        return self.metrics.apply_metrics(self, payload)

    def _visible_global_pairs(self) -> list[tuple[int, int]]:
        return self.metrics._visible_global_pairs(self)

    # ------------------------------------------------------------------
    # 对话域：按候选序号即时落账三态判定

    def apply_dialogue(
        self, *, candidate_index: int, verdict: DialogueVerdict, speaker_ref: str | None, tone: Tone | None
    ) -> str:
        return self.dialogue.apply_dialogue(
            self, candidate_index=candidate_index, verdict=verdict, speaker_ref=speaker_ref, tone=tone
        )

    # ------------------------------------------------------------------
    # 关系域：即时入图，同一对端点重写即整体替换

    def apply_relation(
        self, *, from_ref: str, to_ref: str, relation_type: RelationType
    ) -> tuple[str, str, dict[str, Any]]:
        return self.entities.apply_relation(self, from_ref=from_ref, to_ref=to_ref, relation_type=relation_type)

    # ------------------------------------------------------------------
    # 事件域：建树/加子事件/挂参与者一个调用写完（真实 id 服务端内部持有）

    def apply_event(
        self,
        *,
        el: str,
        isroot: bool,
        description: str,
        evidence: int | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        node_type: EventChildType | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        return self.events.apply_event(
            self,
            el=el,
            isroot=isroot,
            description=description,
            evidence=evidence,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
            node_type=node_type,
            characters=characters,
        )

    def _event_record(self, el: str, *, isroot: bool) -> str:
        return self.events._event_record(el, isroot=isroot)

    _IR_RECORD_RE = re.compile(r"([a-z_]+)/(entity|dialogue|relation|event)/(.+)")

    def production_record_key(self, key: str) -> str:
        """用于把模型面 IR 记录键规范成生产记录键（已是生产键的原样返回）

        2026-09-20 起 subagent 路径的 written_record_keys 混装两种键：构造器 plan 的
        IR 键（structure/entity/a1、event/t1、evidence/dialogue/3）与生产写入面的
        生产键（entity/{name}、event:t1/root、dialogue/3）。push_case/anchor_record 按
        written 集合校验后原样存进 target_ref/source_anchors，而正式提交的
        bind_record_target 只认生产键——IR 键落库必炸"原文锚点不是本章正式产出"。
        这里在工具入口统一翻译成生产键，两类消费点共用这一份规范。
        """
        # 2026-10-04 裸树键补全：模型按自然形态拿树键当记录键（run 4cb054dc 18 次
        # anchor 被拒），树键在索引里时唯一指到它的根记录，统一补 /root
        if key in self.tree_key_index:
            return f"{key}/{RESERVED_ROOT_KEY}"
        match = self._IR_RECORD_RE.fullmatch(key)
        if match is not None:
            role, domain, body = match.groups()
            if domain == "entity":
                name = self.resolve_entity_ref(f"{role}:{body}", record=key, field="record_id")
                return f"entity/{name}"
            if domain == "dialogue":
                return f"dialogue/{body}"
            if domain == "event":
                # 2026-10-03 非事件角色写树时的 IR 键（structure/event/t1）：树键按
                # 角色命名空间化落库（namespace_event_el → structure:t1）
                namespaced = f"{role}{ROLE_NAMESPACE_SEP}{body}"
                return namespaced if EL_PATH_SEP in body else f"{namespaced}/{RESERVED_ROOT_KEY}"
            if domain == "relation":
                return self._production_relation_key(key, role, body)
            return key
        if key.startswith("event/"):
            # 2026-10-03 修正事件键翻译：子代理事件树落库时树键按角色命名空间化
            # （namespace_event_el：t1 → event:t1），节点 id 以命名空间树键参与
            # stable_uuid——IR 前缀 "event/" 恰是事件角色自己的前缀（_record_of 去重），
            # 翻译必须保留命名空间。此前翻成 t1/root、t1/e12，提交期 bind_record_target
            # 按无命名空间树键算 node_id 永不匹配，案例指向事件的章必炸"原文锚点的
            # 事件不是本章正式产出"（run 4a6c268c ch21 三连炸实证）。written 集合里的
            # "event/..." 只来自子代理构造器日志（solo 面 write_event 回执本就是生产键
            # event:t1/root 或 t1/root 原样登记），无条件翻译不影响 solo 路径。
            el = key.removeprefix("event/")
            namespaced = f"event{ROLE_NAMESPACE_SEP}{el}"
            return namespaced if EL_PATH_SEP in el else f"{namespaced}/{RESERVED_ROOT_KEY}"
        return key

    def _production_relation_key(self, key: str, role: str, body: str) -> str:
        """用于把 IR 关系键翻译成生产键；消解不了当场拒绝（毒键入库必炸提交期 bind）

        2026-10-03 角色命名空间修复：IR 关系键的端点 el 是 subagent 局部键，落库时按
        角色命名空间化（namespace_el → structure:qianjin），解析必须带角色前缀——此前用
        裸 el 查索引永不命中，翻译原样返回 "structure/relation/a-b"，提交期
        bind_record_target 前缀不匹配 entity/relation/dialogue，落进事件分支按
        tree_key="structure" 算 node_id 永不匹配，整章炸"原文锚点的事件不是本章正式产出"
        （run 4a6c268c ch21 attempt 14/15 实证）。原样返回等价于埋毒键，改为当场拒绝：
        模型拿结构化回执换一条可消解的记录或省略 record_id，不再连烧 3 个 attempt。
        """
        from_el, sep, to_el = body.rpartition("-")
        if not sep:
            raise AnnotationStageRejection(
                f"{key} 不是可消解的关系记录键（缺少 from-to 端点形态）",
                record=key,
                field="record_id",
                code="unknown_record",
                expected="关系 IR 键形如 structure/relation/from_el-to_el（端点 el 是你登记实体时的 id）",
            )
        if self.graph is None:
            raise AnnotationInvariantError("关系键消解需要常驻事实图，graph 缺失")
        names: list[str] = []
        for el in (from_el, to_el):
            names.append(self.resolve_entity_ref(f"{role}{ROLE_NAMESPACE_SEP}{el}", record=key, field="record_id"))
        types = {
            str(op["relation_type"])
            for op in self.graph.relation_assert_ops
            if op["from_entity"] == names[0] and op["to_entity"] == names[1]
        }
        if len(types) != 1:
            raise AnnotationStageRejection(
                f"{key} 无法唯一消解成一条已写出的关系边（两端间存在 {len(types)} 种关系类型）",
                record=key,
                field="record_id",
                code="unknown_record",
                expected="两端之间恰好写出过一条关系边时才能作为案例目标；请换可消解的记录或省略 record_id",
            )
        return f"relation/{names[0]}-{names[1]}/{types.pop()}"

    def _reconcile_pending_children(self) -> None:
        return self.events._reconcile_pending_children()

    def is_pending_child(self, record: str) -> bool:
        return self.events.is_pending_child(record)

    # ------------------------------------------------------------------
    # 2026-09-14 回执返回写入内容（所有 write 回执回显写入内容）；2026-09-19 id 纪律：
    # content=本次写入的生效终值（服务端归一/端点解析已完成），带 run 级 uuid id

    def entity_content(self, entity: EntityInput) -> dict[str, Any]:
        return self.entities.entity_content(self, entity)

    def metrics_content(self) -> dict[str, Any]:
        return self.metrics.metrics_content()

    def dialogue_content(self, candidate_index: int) -> dict[str, Any]:
        return self.dialogue.dialogue_content(candidate_index)

    def event_content(self, *, el: str, isroot: bool) -> dict[str, Any]:
        return self.events.event_content(el=el, isroot=isroot)

    # ------------------------------------------------------------------
    # 2026-09-14 进度账本数据源（每回合注入最新进展，不走回执 rollup）：
    # 服务端不把思考重放给模型，"已写到哪、还欠哪些"由系统逐回合直给——四个
    # *_ledger() 供 graph 侧渲染写者面【进度账本】注入块（局部键面，不露 uuid）。

    def entity_ledger(self) -> list[dict[str, Any]]:
        return self.entities.entity_ledger(self)

    def dialogue_ledger(self) -> dict[str, Any]:
        return self.dialogue.dialogue_ledger()

    # ------------------------------------------------------------------
    # 收尾声明：唯一 finish，系统据此校验并冻结当前章（冻结单位=整章）

    def _ensure_domain_payloads(self) -> None:
        """finish 协调合法空状态，四状态分别拥有自己的输出"""
        self.entities.domain_payloads.setdefault(
            "entities", EntityDirectoryInput(entities=list(self.written_entities.values()))
        )
        self.entities.domain_payloads.setdefault("relations", list(self.written_relations.values()))
        self.dialogue.domain_payloads.setdefault("dialogues", list(self.written_dialogues.values()))
        self.events.domain_payloads.setdefault("events", list(self.events.bound_payloads.get("events") or []))
        self.events.domain_payloads.setdefault("character_observations", list(self.observation_by_record.values()))
        self.events.bound_payloads.setdefault("events", list(self.events.domain_payloads["events"]))
        self.events.bound_payloads.setdefault(
            "character_observations", list(self.events.domain_payloads["character_observations"])
        )
        self.dialogue.bound_payloads.setdefault("dialogues", [])
        self.metrics.bound_payloads.setdefault("paragraph_labels", [])

    def _chapter_write_records(self) -> list[dict[str, Any]]:
        """用于收尾时把本章 的写入汇总成领域级审计记录（形状与此前一致）"""
        records: list[dict[str, Any]] = [
            {
                "chapter_id": self.current_chapter_id,
                "domain": "entities",
                "payload": EntityDirectoryInput(entities=list(self.written_entities.values())).model_dump(mode="json"),
            }
        ]
        if self.metrics_payload is not None:
            records.append(
                {
                    "chapter_id": self.current_chapter_id,
                    "domain": "metrics",
                    "payload": self.metrics_payload.model_dump(mode="json"),
                }
            )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
                "domain": "events",
                "payload": {
                    "tool": "write_event",
                    "trees": self._event_tree_records(),
                    "character_observation_count": len(self.observation_by_record),
                    "finalized": True,
                },
            }
        )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
                "domain": "relations",
                "payload": [item.model_dump(mode="json") for item in self.written_relations.values()],
            }
        )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
                "domain": "dialogues",
                "payload": [item.model_dump(mode="json") for item in (self.domain_payloads.get("dialogues") or [])],
            }
        )
        return records

    def _event_tree_records(self) -> list[dict[str, Any]]:
        return self.events._event_tree_records()

    def _written_counts(self) -> dict[str, int]:
        """用于收尾回执给出各域写入条数（模型面只需知道写了多少）"""
        return {
            "entities": len(self.written_entities),
            "metrics": 1 if self.metrics_payload is not None else 0,
            "events": len(self.bound_payloads.get("events") or []),
            "relations": len(self.written_relations),
            "dialogues": len(self.written_dialogues),
            "character_observations": len(self.observation_by_record),
            "paragraph_labels": len(self.bound_payloads.get("paragraph_labels") or []),
        }

    def _entity_catalog(self, directory: EntityDirectoryInput) -> tuple[dict[str, EntityType], dict[str, str]]:
        return self.entities._entity_catalog(directory)

    # ------------------------------------------------------------------
    # 事件锚点与证据派生（2026-08-18 事件森林/DAG）
    # ------------------------------------------------------------------
    # 2026-08-22 重构：证据升为章级单份，由持久化层统一盖章，
    # 账本侧不再持有任何锚点/哈希派生逻辑

    def _validate_domain_duplicates(self, payloads: dict[str, Any]) -> None:
        """2026-08-07 用于拒绝当前章 各领域的重复语义事实

        2026-10-04 回执点名违规记录：拒绝消息列出相撞各条的生产记录键与字段值，不再只报
        下标+域名——run 4cb054dc ch12 自愈回合烧 60%+ 思考逆向解读拒绝合同，直接诱因就是
        "[3, 7] character_observations 重复语义项"这种无法定位的形态。
        """
        # 2026-10-04 三态放开后判重只在写入点做（_reject_duplicate_observation，动作非空才查）：
        # 同一人物在多个事件上无动作出场是合法形态，(人物, None) 相撞不是重复语义
        errors: list[str] = []
        for domain, entries in self._duplicate_entries(payloads).items():
            seen: dict[tuple[Any, ...], list[str]] = {}
            for key, label in entries:
                seen.setdefault(key, []).append(label)
            for labels in seen.values():
                if len(labels) > 1:
                    errors.append(f"{domain} 重复语义项: {' 与 '.join(labels)}")
        if errors:
            raise ValueError("；".join(errors))

    def _duplicate_entries(self, payloads: dict[str, Any]) -> dict[str, list[tuple[tuple[Any, ...], str]]]:
        """用于为判重载荷生成 (语义键, 记录点名标签) 对（标签与键同源同序）

        character_observations 的载荷顺序与 observation_by_record 一致（同一 dict 的
        values/keys），逐条能反查回生产记录键；events 用树内节点反查模型面局部键
        （不露 uuid）。键/序失配时退回下标标签，点名失败不改变判重语义。
        """
        node_labels = {
            str(node_id): f"{tree_key}/{node_key}"
            for tree_key, tree_id in self.tree_key_index.items()
            for node_key, node_id in (self.event_trees.get(tree_id) or {}).get("nodes", {}).items()
        }
        observation_keys = list(self.observation_by_record)
        return {
            "character_observations": [
                (
                    (item.character, item.action),
                    f"{observation_keys[index] if index < len(observation_keys) else index}"
                    f"(character={item.character}, action={item.action})",
                )
                for index, item in enumerate(payloads["character_observations"])
                if item.action is not None
            ],
            "events": [
                ((str(item.node_id),), node_labels.get(str(item.node_id), str(item.node_id)))
                for item in payloads.get("events") or []
            ],
            "relations": [
                (
                    (item.from_entity, item.to_entity, str(item.relation_type)),
                    f"relation/{item.from_entity}-{item.to_entity}/{item.relation_type}",
                )
                for item in payloads["relations"]
            ],
        }

    # ------------------------------------------------------------------
    # ready_chapter 构造与冻结
    # ------------------------------------------------------------------

    def validate_work_endpoints(self) -> None:
        return self.entities.validate_work_endpoints(self, self.domain_payloads, self.observation_by_record)

    def _paragraph_label_coverage_warnings(self) -> list[str]:
        return self.metrics._paragraph_label_coverage_warnings()

    # ------------------------------------------------------------------
    # 确定性上下文摘要与搜索压缩

    def _domain_fact_views(self) -> dict[str, Any]:
        return self.entities._domain_fact_views(self)

    def context_summary(self) -> dict[str, Any]:
        """2026-08-10 用于从账本确定性生成当前模型请求的上下文摘要"""
        return {
            "phase": self.phase,
            "chapter_id": self.current_chapter_id,
            "chapter_finished": self.chapter_finished,
            # 2026-09-13 实时写入进度（仅供审计：模型看到的只有各小调用的回执）
            "written": self._written_counts(),
            "missing_content": self.missing_content_domains(),
            "entities": {
                "declared": [
                    {
                        "id": (self.graph.entity_id(entity.name) if self.graph is not None else None),
                        "name": entity.name,
                        "entity_type": entity.entity_type,
                    }
                    for entity in self.domain_payloads.get("entities", EntityDirectoryInput()).entities
                ],
                "registered": (
                    [
                        {
                            "id": self.graph.entity_id(display_name),
                            "name": display_name,
                            "entity_type": self.graph.entity_types[key],
                        }
                        for key, display_name in sorted(self.graph.entity_names.items())
                    ]
                    if self.graph is not None
                    else []
                ),
            },
            "facts": self._domain_fact_views(),
            "errors": list(self.errors),
            "search_log": list(self.search_log[-8:]),
        }

    def append_search_log(self, entry: dict[str, Any]) -> None:
        """2026-08-10 用于登记搜索结果压缩条目（查询、命中编号与 digest）"""
        self.search_log.append(entry)

    def missing_content_domains(self) -> list[str]:
        """2026-09-13 用于列出当前章 尚无写入的领域（收尾提醒与审计共用）

        空域是合法终态（某些块确实没有关系/对话/事件），这里只作为提醒清单，
        不阻断收尾——模型看到清单后可自行判断"确实为空，直接收尾"。
        """
        missing: list[str] = []
        if not self.written_entities:
            missing.append("entities")
        if self.metrics_payload is None:
            missing.append("metrics")
        if not self.bound_payloads.get("events"):
            missing.append("events")
        if not self.written_relations:
            missing.append("relations")
        if not self.written_dialogues:
            missing.append("dialogues")
        return missing
