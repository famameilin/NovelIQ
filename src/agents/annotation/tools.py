"""
章节标注语义写入工具与系统运行账本

核心合同: 写入面为五个领域工具（write_entity / write_metrics / write_event /
write_relation / write_dialogue），实体与事件节点用模型自定的 el 局部键寻址、
写入即生效并返回真实回执（{status: written, record}）；领域没有结束声明，
全部写完后用唯一 finish_chapter 收尾，系统据此刻校验并冻结当前 chunk。
完整参数和完整结果只进入审计库，不回到模型上下文。

2026-09-14 写入面重构：根/子/两参与者五工具合并为 write_event（el 层级键挂树、
树内先后=调用顺序）；句标签收编进 write_metrics.labels（段落级监督）；实体
引用增加 el 键空间；伏笔属性收敛为 isforeshadowing+confidence。
2026-09-13 改造前是"一次大载荷 write 完成整个领域"（整树起草 + 整批返工）：
先拆成同轮多个有类型小调用，再按用户裁决取消暂存概念——没有暂存区，
没有逐域 finish，失败只指向一个语义单元，模型只重调那一条记录。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol, cast
from uuid import uuid4

from langchain_core.tools import tool
from pydantic import ConfigDict, Field, JsonValue, ValidationError, create_model

from .candidates import extract_dialogue_candidates
from .errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationInvariantError,
    AnnotationProtocolError,
    AnnotationStageRejection,
)
from .fact_graph import FactGraph
from .reader_report import ReaderReport, normalize_message_name, report_case_quotes, report_entity_name_keys
from .schema import (
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ENTITY_TAGS_RULE_TEXT,
    RELATION_CHANGE_KIND_LABELS,
    RELATION_DEFINITIONS,
    ActiveCaseDetails,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEvent,
    BoundParagraphLabel,
    CaseSearchResult,
    ChunkMetricsInput,
    ChunkParagraphInfo,
    Confidence,
    DialogueCandidate,
    DialogueInput,
    DialogueVerdict,
    EntityDirectoryInput,
    EntityInput,
    EntityRef,
    EntityType,
    EventCauseRole,
    EventChildType,
    EventParticipantInput,
    EventParticipantRole,
    EventTreeHistoryResult,
    NarrativeFunction,
    ParagraphLabelInput,
    ParticipantArg,
    PendingCase,
    RelationChangeKindArg,
    RelationInput,
    RelationType,
    ResolvedCase,
    SearchResult,
    TextSearchResult,
    Tone,
    relation_catalog_text,
    tone_catalog_text,
)

# 2026-08-22伏笔并入事件树（isforeshadowing），不再是独立领域
# 2026-09-14 写入面重构：句/段标签收编进 write_metrics.labels，事件五工具合并为
# write_event，收尾唯一 finish_chapter——五个领域写工具从首轮起全部开放。
_DOMAIN_NAMES = (
    "metrics",
    "entities",
    "character_observations",
    "dialogues",
    "events",
    "relations",
)
_DOMAIN_NAMES_SET = frozenset(_DOMAIN_NAMES)
# 2026-09-13 领域写入工具表：正式写入工具集合与失败归因共用同一份声明
_DOMAIN_WRITE_TOOLS: dict[str, tuple[str, ...]] = {
    "entities": ("write_entity",),
    "metrics": ("write_metrics",),
    "events": ("write_event",),
    "relations": ("write_relation",),
    "dialogues": ("write_dialogue",),
}
# 全部写入工具（schema 层失败翻译与正式工具集合使用）
# 2026-09-14 案例解决也进集合：tone 等参数回到家枚举后，解决路径的 schema 层失败
# 与写入路径同一条翻译路径（否则模型收到裸 pydantic 报错，没有 record/field 可自纠）。
_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    [tool_name for tool_names in _DOMAIN_WRITE_TOOLS.values() for tool_name in tool_names]
    + [
        "resolve_dialogue_case",
        "resolve_fact_case",
        "resolve_foreshadowing_case",
        "close_case",
    ]
)
# 失败归因表：领域 → 写入工具（2026-09-14 写入面合并后无例外项）
_WRITE_TOOL_DOMAINS: dict[str, str] = {
    tool_name: domain
    for domain, tool_names in _DOMAIN_WRITE_TOOLS.items()
    for tool_name in tool_names
}
# 2026-09-13 五域固定遍历顺序：工具面排序、缺内容提醒与写入计数共用（无逐域结束声明）
_DOMAIN_ORDER = ("entities", "metrics", "events", "relations", "dialogues")
# 2026-09-07 监督标签冻结软下限（每章 2-3 段定稿）：低于 2 留痕覆盖告警，不阻断冻结
_PARAGRAPH_LABEL_MIN_PER_CHUNK = 2
_INTERNAL_GRAPH_KEYS = {
    "candidate_key",
    "chunk_id",
    "end",
    "fact_id",
    "relation_id",
    "representative_entity_id",
    "start",
}
# 2026-09-11 历史事件视图里的数据库实体主键与运行期编号空间不同，模型只见编号：
# 视图内嵌的 entity_id 一律剥掉，改配运行期编号 n
_INTERNAL_ENTITY_KEYS = frozenset({"entity_id"})
# 事件根节点在章内局部键空间里的固定名字（子事件键不得占用）
_ROOT_NODE_KEY = "root"
# 局部键路径分隔符：子事件 el = "<树键>/<节点键>"
_EL_PATH_SEP = "/"


def _norm_entity_key(name: str) -> str:
    """2026-09-13 用于生成实体记录键（与 FactGraph 名称归一化同源）"""
    return unicodedata.normalize("NFC", name).strip().casefold()


# 2026-09-14 写入面重构：局部键由模型自行指定、写入即生效——同一轮里先建的键，
# 后面的调用直接可用，不存在"等回执"或"跨轮才能引用"的约束，参数说明即按此声明。
EntityLocalKey = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "本实体的章内局部键（el），由你指定（如 a1）；write_entity 写入即生效，"
            "同轮 write_event/write_relation/write_dialogue 的实体引用直接用它，不必等回执"
        ),
    ),
]
EventLocalKey = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "本节点的层级局部键，由你指定：根事件 el=树键（如 t1），"
            "子事件 el=树键/节点键（如 t1/e2，节点键不得占用 root）；"
            "写入即生效，同轮后面的调用（子事件、参与者、resolve_* 引用）直接可用"
        ),
    ),
]

# 2026-09-13 案例编号单源：四个案例工具共用同一句参数说明
# （run c80105cc 实测：编号来源不写在模型可见面上，模型只能靠被拒反推）
CASE_NUMBER_RULE = "案例编号：search_pool 或 push_case 回执给出的数（案例不在正文注入，检索即授权）"
CaseNumber = Annotated[int, Field(description=CASE_NUMBER_RULE)]


def tool_record_key(tool_name: str, args: dict[str, Any]) -> str | None:
    """2026-09-13 用于按工具名与原始参数生成稳定记录键（成功回执与拒绝回执共用）

    参数可能是未过 schema 的原始值，此处只做展示级拼接、不做校验；
    键在 chunk 收尾前保持稳定，重写同键即更新同一条记录。
    """
    if tool_name == "write_entity":
        return f"entity/{args.get('name')}"
    if tool_name == "write_metrics":
        return "metrics"
    if tool_name == "write_dialogue":
        return f"dialogue/{args.get('candidate_index')}"
    if tool_name == "write_relation":
        return f"relation/{args.get('from_entity')}-{args.get('to_entity')}/{args.get('relation_type')}"
    if tool_name == "write_event":
        el = str(args.get("el") or "")
        if _EL_PATH_SEP not in el and not bool(args.get("isroot")):
            # 子事件键写错形态时仍按原样回显，回执定位到被拒的那次调用
            return el or "event"
        if _EL_PATH_SEP in el:
            return el
        return f"{el}/{_ROOT_NODE_KEY}" if el else "event"
    return None


def _event_view_participants(participants: list[dict[str, Any]], *, graph: FactGraph | None) -> list[dict[str, Any]]:
    """2026-09-11 用于把历史事件参与者视图里的数据库 entity_id 换成运行期编号"""
    views: list[dict[str, Any]] = []
    for participant in participants:
        descriptor = participant.get("entity")
        cleaned = {key: value for key, value in participant.items() if key != "entity"}
        if isinstance(descriptor, dict):
            descriptor = {key: value for key, value in descriptor.items() if key not in _INTERNAL_ENTITY_KEYS}
            name = descriptor.get("name")
            number = graph.entity_number(str(name)) if graph is not None and name else None
            if number is not None:
                descriptor["n"] = number
            cleaned["entity"] = descriptor
        else:
            cleaned["entity"] = descriptor
        views.append(cleaned)
    return views


class AnnotationQueryService(Protocol):
    """2026-08-07 用于隔离 Agent 查询工具和数据库实现"""

    def search_pool(
        self,
        query: str | None,
        *,
        hidden_case_ids: set[str],
        case_type: str | None = None,
        limit: int = 50,
        pending_cases: Sequence[CaseSearchResult] = (),
    ) -> SearchResult:
        """2026-09-11 用于检索活动案例与伏笔线程（案例的唯一发现通道）

        2026-09-13 登记即进池：pending_cases 是本 chunk 内 push_case 登记的待建案例，
        实现方按与池内案例一致的匹配/枚举语义一并返回。
        """

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> list[TextSearchResult]:
        """2026-08-30 用于按配置范围返回有限正文命中"""

    def search_event_history(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> list[EventTreeHistoryResult]:
        """2026-08-30 用于检索当前章之前已完成章节的事件树根视图"""

    def fetch_active_case_details(self, case_id: str) -> ActiveCaseDetails | None:
        """2026-08-07 用于读取活动案例内部稳定目标"""


@dataclass(slots=True)
class AnnotationToolLedger:
    """2026-08-07 用于保存单 chunk 领域写入和系统绑定状态

    2026-09-13 实时写入：模型面的每个小调用即时落到目标结构（written_*），
    全部写完后由唯一 finish_chapter 收尾冻结，没有暂存区也没有逐域结束声明。
    """

    run_scope: str
    current_chapter_id: int
    current_chunk_id: int
    current_chunk_text: str
    allow_future_context: bool
    phase: str = "chunk_open"
    dialogue_candidates: list[DialogueCandidate] = field(default_factory=list)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)
    write_records: list[dict[str, Any]] = field(default_factory=list)
    completed_chunks: list[BoundChunkAnnotation] = field(default_factory=list)
    ready_chunk: BoundChunkAnnotation | None = None
    # 2026-09-11 案例改检索制：正文不再注入案例表，案例只经 search_pool 展示登记
    case_number_registry: dict[int, str] = field(default_factory=dict)
    case_number_by_id: dict[str, int] = field(default_factory=dict)
    next_case_number: int = 1
    resolved_cases: list[ResolvedCase] = field(default_factory=list)
    pushed_cases: list[PendingCase] = field(default_factory=list)
    # 2026-08-14 M6：案例展示/解决授权章（案例源是章级定位，§12.3）
    authorized_chapter_ids: set[int] = field(default_factory=set)
    # 2026-08-30：search_text 返回正文时登记真实 SQL 命中段落
    authorized_text_paragraph_ids: set[int] = field(default_factory=set)
    # 2026-08-12 收尾时未提交判定的对话候选序号（系统按 not_dialogue 默认处理）
    dialogue_missing_indexes: list[int] = field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（仅留痕不阻断），随 chunk 持久化
    coverage_warnings: list[str] = field(default_factory=list)
    annotation: BoundChapterAnnotation | None = None
    errors: list[str] = field(default_factory=list)
    search_log: list[dict[str, Any]] = field(default_factory=list)
    graph_queried: bool = False
    # 2026-09-13 实体准入闸门：小调用改造后 write_entity 一条一个实体，
    # 闸门只对本章第一次登记生效（否则一轮登记多个实体会被自己的登记挡在门外）。
    # 单调放行、刻意不进 snapshot：闸门讲的是"模型已被告知先查图"，不是账本事实
    entity_gate_passed: bool = False
    graph: FactGraph | None = None
    # 2026-08-18 事件森林/DAG：当前 chunk 的段落坐标映射，用于事件锚点校验和证据派生
    paragraph_info: ChunkParagraphInfo | None = None
    # 2026-08-22已写事件节点 id（含历史树根），供伏笔 setup/payoff 授权
    authorized_event_ids: set[str] = field(default_factory=set)
    # 2026-09-04事件树 id 集合：setup/payoff 误传 tree_id 时给出针对性纠错提示
    authorized_tree_ids: set[str] = field(default_factory=set)
    # 2026-08-19 当前章节序号（写章指标与上下文摘要展示用）
    current_chapter_order: int | None = None
    # 2026-08-22本章事件树状态（单章闭环）；历史树视图缓存供伏笔树根判定引用
    event_trees: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_tree_views: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 2026-09-12 章内并行两段式（§7）：写者的读者一次性报告，用于写入取值域准入。
    # 报告是观察不是写入，刻意不进 snapshot/restore；单块章与读者为 None，行为不变
    reader_reports: list[ReaderReport] | None = None
    # 2026-09-13 实时写入（取消暂存）：每次小调用即时落到目标结构，回执即当前真相。
    # 全部进 snapshot/restore——单次调用失败只回滚该调用，之前写入的记录必须保留
    written_entities: dict[str, EntityInput] = field(default_factory=dict)
    metrics_payload: ChunkMetricsInput | None = None
    written_dialogues: dict[int, DialogueInput] = field(default_factory=dict)
    # 有序对 → 关系记录（同一对端点换类型即整体替换，保持"本章关系=完整集合"语义）
    written_relations: dict[tuple[str, str], RelationInput] = field(default_factory=dict)
    # 人物动态状态按记录键持有（重写同一参与者即更新，键给回执定位用）
    observation_by_record: dict[str, BoundCharacterObservation] = field(default_factory=dict)
    # tree_key → tree_id：章内局部键是模型侧寻址面，真实 uuid 不外露
    tree_key_index: dict[str, str] = field(default_factory=dict)
    # 2026-09-14 实体局部键索引：el → 归一化登记名（模型自定、写入即绑定、同轮可用）
    entity_el_index: dict[str, str] = field(default_factory=dict)
    # 2026-09-13 收尾声明：唯一 finish_chapter 置位后由系统冻结当前 chunk
    chapter_finished: bool = False

    def __post_init__(self) -> None:
        """2026-08-07 用于初始化唯一 chunk 的对话候选"""
        if not self.current_chunk_text.strip():
            raise AnnotationInputError("current_chunk_text 不能为空")
        self.dialogue_candidates = extract_dialogue_candidates(
            self.current_chunk_id,
            self.current_chunk_text,
        )

    @property
    def resolved_case_ids(self) -> set[str]:
        """2026-08-07 用于返回本轮已经解决的真实案例 ID

        2026-09-04 单一写面：fact 动作不再进 resolved_cases，改由 FactGraph 的
        relation_change_ops 承载，此处合并两路案例 id（search_pool 隐藏与重复
        解决校验依赖本集合）。
        """
        ids = {item.case_id for item in self.resolved_cases}
        if self.graph is not None:
            ids |= {op["case_id"] for op in self.graph.relation_change_ops}
        return ids

    def pending_case_by_id(self, case_id: str) -> PendingCase | None:
        """2026-09-13 用于按 target_key 查找本 chunk 内 push_case 登记的待建案例

        登记即进池：编号在 push_case 当场分配，检索面（search_pool）与解决面
        （_resolve_case_details）都按同一 target_key 认这条案例，直到本章收尾
        它才作为案例池行落库（那时池行 id 就是本 target_key，链路无需重映射）。
        """
        return next((case for case in self.pushed_cases if case.target_key == case_id), None)

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于同步 LangGraph 和工具账本阶段"""
        self.phase = phase

    def snapshot(self) -> dict[str, Any]:
        """2026-08-10 用于在单个工具调用执行前保存可回滚账本状态

        2026-09-13 实时写入结构同进快照：单条小调用失败只回滚该调用，
        之前已写入的记录必须原样保留（失败不丢已写入记录）。
        """
        return deepcopy(
            {
                "phase": self.phase,
                "domain_payloads": self.domain_payloads,
                "bound_payloads": self.bound_payloads,
                "chapter_finished": self.chapter_finished,
                "write_records": self.write_records,
                "completed_chunks": self.completed_chunks,
                "ready_chunk": self.ready_chunk,
                "case_number_registry": self.case_number_registry,
                "case_number_by_id": self.case_number_by_id,
                "next_case_number": self.next_case_number,
                "resolved_cases": self.resolved_cases,
                "pushed_cases": self.pushed_cases,
                "authorized_chapter_ids": self.authorized_chapter_ids,
                "authorized_text_paragraph_ids": self.authorized_text_paragraph_ids,
                "authorized_event_ids": self.authorized_event_ids,
                "authorized_tree_ids": self.authorized_tree_ids,
                "event_trees": self.event_trees,
                "history_tree_views": self.history_tree_views,
                "dialogue_missing_indexes": self.dialogue_missing_indexes,
                "annotation": self.annotation,
                "search_log": self.search_log,
                "written_entities": self.written_entities,
                "metrics_payload": self.metrics_payload,
                "written_dialogues": self.written_dialogues,
                "written_relations": self.written_relations,
                "observation_by_record": self.observation_by_record,
                "tree_key_index": self.tree_key_index,
                "entity_el_index": self.entity_el_index,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-10 用于在单个工具调用失败时恢复该调用开始前的账本状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

    def resolve_event_reference(self, reference: str) -> str | None:
        """2026-09-13 用于把模型面的章内局部键（t1/e1、t1 指根）翻成真实节点 id

        事件写入即生效，因此映射随时可得；键不存在时返回 None，
        由调用方按"未授权"处理并给出针对性提示。
        """
        if reference in self.authorized_event_ids:
            return reference
        tree_key, _, node_key = reference.partition("/")
        tree = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if tree is None:
            return None
        node_id = tree["nodes"].get(node_key or _ROOT_NODE_KEY)
        return str(node_id) if node_id else None

    def resolve_entity_ref(self, ref: int | str, *, record: str, field: str) -> str:
        """2026-09-14 用于把模型面实体引用（编号 n / 自定 el）解析成登记名

        两种键空间同一条解析路径：整数（含纯数字字符串）走 FactGraph 编号，
        字符串先查本 chunk 的 el 索引；未知 el 结构化拒绝并列出已知键。
        """
        if self.graph is None:
            raise AnnotationInvariantError("实体引用解析需要常驻事实图，graph 缺失")
        if isinstance(ref, str) and not ref.strip().isdigit():
            key = self.entity_el_index.get(ref.strip())
            if key is None:
                known = ", ".join(sorted(self.entity_el_index)) or "（本 chunk 还没有实体用 el 登记）"
                raise AnnotationStageRejection(
                    f"el 键未由本 chunk 任何 write_entity 登记: {ref}",
                    record=record,
                    field=field,
                    code="unknown_el",
                    expected=f"已知 el 键: {known}；引用历史/其他章实体请改用编号 n（search_graph 回执）",
                )
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
            return self.graph.resolve_number(int(ref), label=f"{record}.{field}")
        except (ValueError, TypeError) as exc:
            raise AnnotationStageRejection(
                str(exc),
                record=record,
                field=field,
                code="unregistered_number",
                expected="已登记实体的运行期编号 n（write_entity / search_graph 回执）或本 chunk 自定的 el 键",
            ) from None

    def register_case_number(self, case_id: str) -> int:
        """2026-08-07 用于为真实案例 ID 分配稳定运行内编号"""
        existing = self.case_number_by_id.get(case_id)
        if existing is not None:
            return existing
        number = self.next_case_number
        self.next_case_number += 1
        self.case_number_registry[number] = case_id
        self.case_number_by_id[case_id] = number
        return number

    def _tree_id(self) -> str:
        """2026-08-22服务端一次生成树 id（uuid4，永不重排、跨子块不冲突）"""
        return str(uuid4())

    def _node_id(self) -> str:
        """2026-08-22服务端一次生成节点 id（=最终落库 event_id）"""
        return str(uuid4())

    # ------------------------------------------------------------------
    # 实时写入：每个小调用即时落到目标结构，回执即当前真相（2026-09-13 取消暂存区）
    # ------------------------------------------------------------------

    def _require_writable(self, record: str) -> None:
        """用于在每个写入入口统一校验阶段（chunk 冻结后不再接受写入）"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许写入正式标注")

    def _tree_by_key(self, tree_key: str, record: str) -> dict[str, Any]:
        """用于按章内局部键读取已落账的事件树，未建树时给出可自纠报错"""
        tree = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if tree is None:
            raise AnnotationStageRejection(
                f"树键未建: {tree_key}",
                record=record,
                field="el",
                code="unknown_tree",
                expected="先用 write_event(isroot=true, el=\"t1\") 建树，子事件再用 t1/节点键（同轮先根后子即可）",
            )
        return tree

    def _bound_event(self, node_id: str) -> BoundEvent:
        """用于在已落账事件里按节点 id 取节点对象（参与者挂在它上面）"""
        for event in self.bound_payloads.get("events") or []:
            if event.node_id == node_id:
                return event
        raise AnnotationInvariantError(f"事件节点未落账: {node_id}")

    # ------------------------------------------------------------------
    # 实体域：登记即入图并分配运行期编号；el 局部键当场绑定，同轮可用

    def apply_entity(self, entity: EntityInput, *, el: str, present: set[str] | None = None) -> int:
        """用于登记或更新一个实体、绑定 el 局部键并即时返回运行期编号（同键同内容重放幂等）

        present（本次实际提交的字段集合）给定时按部分更新合并：未提交字段保留现值，
        兑现 write_entity 合同"只提交本次变化的字段"；不传=整条记录语义（直连调用）。
        """
        record = f"entity/{entity.name}"
        self._require_writable(record)
        normalized_el = unicodedata.normalize("NFC", el).strip()
        bound_key = self.entity_el_index.get(normalized_el)
        if bound_key is not None and bound_key != _norm_entity_key(entity.name):
            raise AnnotationStageRejection(
                f"el 键已被另一实体占用: {normalized_el}",
                record=record,
                field="el",
                code="duplicate_el",
                expected="换一个 el 键（el 在 chunk 内一对一绑定实体）",
            )
        key = _norm_entity_key(entity.name)
        existing = self.written_entities.get(key)
        if existing is not None and present is not None:
            # 部分更新：先合并成生效记录，再进准入与落图（闸门看到的永远是完整记录）
            entity = self._merge_partial_entity(existing, entity, present)
            record = f"entity/{entity.name}"
        self.admit_entity_directory([entity])
        if self.graph is None:
            raise AnnotationInvariantError("write_entity 需要常驻事实图，graph 缺失")
        registered = self.graph.entity_types.get(key)
        if registered is not None and registered != entity.entity_type:
            raise AnnotationStageRejection(
                f"已登记实体不允许变更大类: {entity.name}",
                record=record,
                field="entity_type",
                code="type_conflict",
                expected=f"{registered}（同一词条的不同身份请用区分性名称）",
            )
        if existing is None or existing != entity:
            # 同键不同内容=更新语义；同键同内容直接跳过，避免重复操作日志
            self.graph.register_entities([entity])
            self.graph.record_entity_ops([entity], chapter_id=self.current_chunk_id)
            self.written_entities[key] = entity
            self._rebuild_entity_payload()
        self.entity_el_index[normalized_el] = key
        number = self.graph.entity_number(entity.name)
        if number is None:
            raise AnnotationInvariantError(f"实体编号分配失败: {entity.name}")
        return number

    @staticmethod
    def _merge_partial_entity(existing: EntityInput, incoming: EntityInput, present: set[str]) -> EntityInput:
        """用于已登记实体的部分更新合并（2026-09-14 兑现"只提交本次变化的字段"合同）

        未提交字段保留现值；tags 提交空列表=清空、省略=保留；
        attributes 提交即 JSON Merge Patch（值覆盖、null 删键、省略=整域保留）。
        """
        updates: dict[str, Any] = {}
        if "tags" in present:
            updates["tags"] = incoming.tags
        if "description" in present:
            updates["description"] = incoming.description
        merged = existing.model_copy(update=updates)
        if "attributes" in present:
            patched = dict(existing.attributes or {})
            for attr_key, attr_value in (incoming.attributes or {}).items():
                if attr_value is None:
                    patched.pop(attr_key, None)
                else:
                    patched[attr_key] = attr_value
            merged.attributes = patched
        return merged

    def _rebuild_entity_payload(self) -> None:
        """用于按写入顺序重建当前 chunk 的实体目录载荷"""
        self.domain_payloads["entities"] = EntityDirectoryInput(
            entities=list(self.written_entities.values())
        )

    # ------------------------------------------------------------------
    # 指标域：整域一次提交，重复提交按最后一次为准；段落级监督标签随本域提交

    def apply_metrics(self, payload: ChunkMetricsInput) -> None:
        """用于写入当前 chunk 摘要、叙事指标与段落情绪标签（重复提交整域覆盖）

        labels 的 paragraph_id 必须属于本 chunk（正文 ¶ 号 / 报告证据段号同一
        号码空间）；越界段号整次提交拒绝并指明是哪一条标签。
        """
        self._require_writable("metrics")
        if payload.labels:
            known_ids = list(self.paragraph_info.paragraph_ids) if self.paragraph_info is not None else []
            known = set(known_ids)
            for label in payload.labels:
                if label.paragraph_id not in known:
                    preview = ", ".join(str(pid) for pid in known_ids[:12])
                    raise AnnotationStageRejection(
                        f"paragraph_id 不属于本 chunk: {label.paragraph_id}",
                        record="metrics",
                        field="paragraph_id",
                        code="out_of_range",
                        expected=f"本 chunk 可标注的段号（¶ 后的数字）: {preview}{'…' if len(known_ids) > 12 else ''}",
                    )
            self.bound_payloads["paragraph_labels"] = [
                BoundParagraphLabel(paragraph_id=label.paragraph_id, emotion=label.emotion)
                for label in payload.labels
            ]
        else:
            self.bound_payloads["paragraph_labels"] = []
        self.metrics_payload = payload
        self.domain_payloads["metrics"] = payload

    # ------------------------------------------------------------------
    # 对话域：按候选序号即时落账三态判定

    def apply_dialogue(
        self,
        *,
        candidate_index: int,
        verdict: DialogueVerdict,
        speaker_ref: int | str | None,
        tone: Tone | None,
    ) -> str:
        """用于按候选序号写入一条对话三态判断（同序号重写按更新语义）"""
        record = f"dialogue/{candidate_index}"
        self._require_writable(record)
        candidate_by_index = dict(enumerate(self.dialogue_candidates, start=1))
        if candidate_index not in candidate_by_index:
            raise AnnotationStageRejection(
                f"candidate_index 超出系统候选范围: {candidate_index}",
                record=record,
                field="candidate_index",
                code="out_of_range",
                expected=f"1..{len(self.dialogue_candidates)}（见正文后的 DialogueCandidates 表）",
            )
        speaker_name: str | None = None
        if speaker_ref is not None:
            speaker_name = self.resolve_entity_ref(speaker_ref, record=record, field="speaker")
            if self.graph is not None and self.graph.entity_type(speaker_name) != "character":
                raise AnnotationStageRejection(
                    f"说话人必须是 character: {speaker_name}",
                    record=record,
                    field="speaker",
                    code="not_character",
                    expected="character 类型的实体（编号 n 或 el 键）",
                )
        try:
            item = DialogueInput(
                candidate_index=candidate_index,
                verdict=verdict,
                speaker=speaker_name,
                tone=tone,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_dialogue") from None
        self.written_dialogues[candidate_index] = item
        self._rebuild_dialogue_payload()
        return record

    def _rebuild_dialogue_payload(self) -> None:
        """用于按候选序重建对话载荷（判定表 + 仅含真对话/独白的落账视图）"""
        candidate_by_index = dict(enumerate(self.dialogue_candidates, start=1))
        items = [self.written_dialogues[index] for index in sorted(self.written_dialogues)]
        bound: list[BoundDialogue] = []
        for item in items:
            if item.verdict == DialogueVerdict.NOT_DIALOGUE:
                continue
            candidate = candidate_by_index[item.candidate_index]
            bound.append(
                BoundDialogue(
                    candidate_index=item.candidate_index,
                    candidate_key=candidate.candidate_key,
                    content=candidate.content,
                    start=candidate.start,
                    end=candidate.end,
                    speaker=item.speaker,
                    tone=item.tone,
                    is_inner_monologue=item.verdict == DialogueVerdict.INNER_MONOLOGUE,
                )
            )
        self.domain_payloads["dialogues"] = items
        self.bound_payloads["dialogues"] = bound

    # ------------------------------------------------------------------
    # 关系域：即时入图，同一对端点重写即整体替换

    def apply_relation(
        self,
        *,
        from_ref: int | str,
        to_ref: int | str,
        relation_type: RelationType,
    ) -> tuple[str, str, dict[str, Any]]:
        """用于写入一条本章确认存在的闭合关系边（同一对端点换类型即整体替换）

        返回 (记录键, 本条边的入图结果, 本次写入内容)：assert=新边入图 /
        skipped_existing=已在图上 /
        skipped_self_loop=两端解析到同一实体且非"同一人物"语义（不入图）。
        """
        provisional = f"relation/{from_ref}-{to_ref}/{relation_type}"
        self._require_writable(provisional)
        if self.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        from_name = self.resolve_entity_ref(from_ref, record=provisional, field="from_entity")
        to_name = self.resolve_entity_ref(to_ref, record=provisional, field="to_entity")
        record = f"relation/{from_name}-{to_name}/{relation_type}"
        definition = RELATION_DEFINITIONS[str(relation_type)]
        entity_types = self._fact_entity_catalog()
        for field_name, name, expected_types in (
            ("from_entity", from_name, definition["from_types"]),
            ("to_entity", to_name, definition["to_types"]),
        ):
            try:
                self._require_entity(
                    name,
                    entity_types=entity_types,
                    expected_types=expected_types,
                    label=f"write_relation.{field_name}",
                )
            except ValueError as exc:
                raise AnnotationStageRejection(
                    str(exc),
                    record=record,
                    field=field_name,
                    code="endpoint_invalid",
                    expected=f"端点类型必须属于 {list(expected_types)}",
                ) from None
        try:
            item = RelationInput(
                from_entity=from_name,
                to_entity=to_name,
                relation_type=relation_type,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_relation") from None
        self.written_relations[(item.from_entity, item.to_entity)] = item
        outcomes = self._flush_relations()
        resolution = (self.graph.resolve_name(item.from_entity), self.graph.resolve_name(item.to_entity))
        outcome = next(
            (
                entry["outcome"]
                for entry in outcomes
                if (entry["from"], entry["to"]) == resolution
                and entry["relation_type"] == str(item.relation_type)
            ),
            "assert",
        )
        return record, outcome, item.model_dump(mode="json")

    def _flush_relations(self) -> list[dict[str, Any]]:
        """用于把本章关系完整集合重放到事实图（先清空本章 assert 再按序重放）

        与旧的"领域结算整体替换"语义一致：同一对端点重写换类型即为替换，
        重放保证图终态与本章关系集合同源。
        """
        if self.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        self.graph.reset_chapter_relations()
        outcomes: list[dict[str, Any]] = []
        resolved_items: list[RelationInput] = []
        for item in self.written_relations.values():
            resolved_from = self.graph.resolve_name(item.from_entity)
            resolved_to = self.graph.resolve_name(item.to_entity)
            if _norm_graph_name(resolved_from) == _norm_graph_name(resolved_to):
                # 两端沿同一人物分量解析到同一实体：
                # "同一人物"边（含同批双向重申、跨章重申、传递归并）= 归并已
                # 成立，按合同接受为 skipped_existing；普通关系类型塌成自环
                # 才是退化输入，标 skipped_self_loop。两者照常入图都会在持久化
                # 插入 from_entity_id=to_entity_id 的自环行，违反
                # graph_relations 端点互异约束炸掉完成事务（run a83fae3d
                # 第9章实锤），一律跳过不入图不入操作日志
                is_same_character = (
                    RELATION_DEFINITIONS[str(item.relation_type)]["semantics"] == "same_character"
                )
                outcomes.append(
                    {
                        "from": resolved_from,
                        "to": resolved_to,
                        "relation_type": str(item.relation_type),
                        "outcome": "skipped_existing" if is_same_character else "skipped_self_loop",
                    }
                )
                continue
            dumped = item.model_dump(mode="python")
            dumped["from_entity"] = resolved_from
            dumped["to_entity"] = resolved_to
            resolved_item = RelationInput(**dumped)
            resolved_items.append(resolved_item)
            added = self.graph.apply_relation(resolved_item)
            outcomes.append(
                {
                    "from": resolved_from,
                    "to": resolved_to,
                    "relation_type": str(item.relation_type),
                    "outcome": "assert" if added else "skipped_existing",
                }
            )
        self.graph.record_relation_asserts(resolved_items, chapter_id=self.current_chunk_id)
        self.domain_payloads["relations"] = list(self.written_relations.values())
        return outcomes

    # ------------------------------------------------------------------
    # 事件域：建树/加子事件/挂参与者一个调用写完（真实 id 服务端内部持有）

    def apply_event(
        self,
        *,
        el: str,
        isroot: bool,
        description: str,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        node_type: EventChildType | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """用于写入一个事件节点：isroot 建根（el=树键），子事件 el=树键/节点键

        根节点键固定 root；子节点父=当时主链尾，main 推进链尾；树内先后=调用顺序。
        伏笔属性（isforeshadowing/confidence）只属于根，isforeshadowing=true 时
        confidence 必填；characters=None 保留该节点已有参与者，给出列表即整体替换。
        """
        record = self._event_record(el, isroot=isroot)
        self._require_writable(record)
        tree_key, _, node_key = el.partition(_EL_PATH_SEP)
        tree_key = tree_key.strip()
        node_key = node_key.strip()
        if isroot:
            if not tree_key or node_key:
                raise AnnotationStageRejection(
                    f"根事件的 el 必须是树键（不带路径）: {el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected="根事件 el=树键（如 t1）；子事件才是 树键/节点键（如 t1/e2）",
                )
            if node_type is not None:
                raise AnnotationStageRejection(
                    "type 只属于子事件（根事件由 isroot=true 表达）",
                    record=record,
                    field="type",
                    code="not_on_root",
                    expected="根事件不填 type",
                )
            if isforeshadowing and confidence is None:
                raise AnnotationStageRejection(
                    "isforeshadowing=true 时必须提供 confidence",
                    record=record,
                    field="confidence",
                    code="missing",
                    expected="confidence=high / medium / low（伏笔回收可能性三档）",
                )
            node_id = self._apply_event_root(
                record=record,
                tree_key=tree_key,
                description=description,
                isforeshadowing=isforeshadowing,
                confidence=confidence,
            )
        else:
            if not tree_key or not node_key:
                raise AnnotationStageRejection(
                    f"子事件的 el 必须是 树键/节点键: {el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected='形如 t1/e2（节点键不得占用 root）；建树请用 write_event(isroot=true, el="t1")',
                )
            if node_key == _ROOT_NODE_KEY:
                raise AnnotationStageRejection(
                    f"子事件不得占用节点键 {_ROOT_NODE_KEY}",
                    record=record,
                    field="el",
                    code="reserved",
                    expected="换一个节点键（root 固定指根事件）",
                )
            if isforeshadowing or confidence is not None:
                raise AnnotationStageRejection(
                    "伏笔属性（isforeshadowing/confidence）只属于根事件",
                    record=record,
                    field="isforeshadowing",
                    code="not_on_child",
                    expected="子事件只填 el/type/description/characters",
                )
            if node_type is None:
                raise AnnotationStageRejection(
                    "子事件必须提供 type",
                    record=record,
                    field="type",
                    code="missing",
                    expected='type="main"（顺延主因链）或 "secondary"（挂在当时主链尾）',
                )
            node_id = self._apply_event_child(
                record=record,
                tree_key=tree_key,
                node_key=node_key,
                node_type=node_type,
                description=description,
            )
        if characters is not None:
            self._apply_participants(
                node_record=record,
                node_id=node_id,
                characters=characters,
            )
        return record

    def _event_record(self, el: str, *, isroot: bool) -> str:
        """用于把模型面 el 归一成记录键（根记录 = 树键/root）"""
        cleaned = unicodedata.normalize("NFC", el).strip()
        if isroot or _EL_PATH_SEP not in cleaned:
            return f"{cleaned}/{_ROOT_NODE_KEY}"
        return cleaned

    def _apply_event_root(
        self,
        *,
        record: str,
        tree_key: str,
        description: str,
        isforeshadowing: bool,
        confidence: Confidence | None,
    ) -> str:
        """用于建树并即时落账根事件（同树键重写按更新语义），返回根节点 id"""
        existing = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if existing is not None:
            root_event = self._bound_event(existing["root_node_id"])
            root_event.description = description
            root_event.is_foreshadow_setup = isforeshadowing
            root_event.payoff_likelihood = confidence
            existing["isforeshadowing"] = isforeshadowing
            return str(existing["root_node_id"])
        tree_id = self._tree_id()
        root_node_id = self._node_id()
        root_event = BoundEvent(
            node_id=root_node_id,
            tree_id=tree_id,
            parent_node_id=None,
            cause_role="root",
            description=description,
            participants=[],
            is_foreshadow_setup=isforeshadowing,
            payoff_likelihood=confidence,
        )
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.append(root_event)
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["events"] = events_bound
        self.event_trees[tree_id] = {
            "tree_id": tree_id,
            "chapter_id": self.current_chapter_id,
            "chapter_order": self.current_chapter_order,
            "root_node_id": root_node_id,
            "trunk_tail": root_node_id,
            "isforeshadowing": isforeshadowing,
            # node_key → node_id：模型侧只用章内局部键寻址（根键固定 root）
            "nodes": {_ROOT_NODE_KEY: root_node_id},
        }
        self.tree_key_index[tree_key] = tree_id
        self.authorized_event_ids.add(root_node_id)
        self.authorized_tree_ids.add(tree_id)
        return root_node_id

    def _apply_event_child(
        self,
        *,
        record: str,
        tree_key: str,
        node_key: str,
        node_type: EventChildType,
        description: str,
    ) -> str:
        """用于在已建的树上追加/更新一个子事件，返回节点 id

        "main" 顺延主因链（成为新的链尾）/"secondary" 挂在当时主链尾；
        树内先后=调用顺序（order 参数已下线，无任何下游消费）。
        """
        tree = self._tree_by_key(tree_key, record)
        existing_node_id = tree["nodes"].get(node_key)
        if existing_node_id is not None:
            event = self._bound_event(str(existing_node_id))
            if str(event.cause_role) != str(node_type):
                raise AnnotationStageRejection(
                    f"节点已建，type 不允许改写: {tree_key}/{node_key}",
                    record=record,
                    field="type",
                    code="immutable",
                    expected="删除重写需换节点键（该节点 type=已定的 main/secondary）",
                )
            event.description = description
            return str(existing_node_id)
        parent_node_id = str(tree["trunk_tail"])
        node_id = self._node_id()
        event = BoundEvent(
            node_id=node_id,
            tree_id=str(tree["tree_id"]),
            parent_node_id=parent_node_id,
            cause_role=cast("EventCauseRole", str(node_type)),
            description=description,
            participants=[],
        )
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.append(event)
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["events"] = events_bound
        tree["nodes"][node_key] = node_id
        if str(node_type) == "main":
            tree["trunk_tail"] = node_id
        self.authorized_event_ids.add(node_id)
        return node_id

    def _apply_participants(
        self,
        *,
        node_record: str,
        node_id: str,
        characters: list[ParticipantArg],
    ) -> None:
        """用于把 characters 数组整体替换到指定节点的参与者列表

        按登记类型分流：character 三态必填并派生人物动态状态（人物榜/Greimas/
        实体状态注入的唯一数据源）；非 character 不接受三态；同一实体在数组内
        只允许出现一次；旧记录键下的动态状态先清后建（替换语义）。
        """
        if self.graph is None:
            raise AnnotationInvariantError("参与者解析需要常驻事实图，graph 缺失")
        event = self._bound_event(node_id)
        for stale in [key for key in self.observation_by_record if key.startswith(f"{node_record}/participant/")]:
            del self.observation_by_record[stale]
        seen: set[str] = set()
        participants: list[EventParticipantInput] = []
        for arg in characters:
            participant_record = f"{node_record}/participant/{arg.entityid}"
            entity_name = self.resolve_entity_ref(arg.entityid, record=participant_record, field="entityid")
            key = _norm_entity_key(entity_name)
            if key in seen:
                raise AnnotationStageRejection(
                    f"同一实体在 characters 数组内重复出现: {entity_name}",
                    record=participant_record,
                    field="entityid",
                    code="duplicate_participant",
                    expected="每个实体一次提交只出现一次（本数组即该节点参与者的完整集合）",
                )
            seen.add(key)
            actual_type = self.graph.entity_type(entity_name)
            if actual_type is None:
                raise AnnotationStageRejection(
                    f"参与者实体未登记: {entity_name}",
                    record=participant_record,
                    field="entityid",
                    code="unregistered",
                    expected="先用 write_entity 登记（或 search_graph 查已登记编号）",
                )
            if arg.role == EventParticipantRole.LOCATION and actual_type != EntityType.LOCATION.value:
                raise AnnotationStageRejection(
                    f"地点角色端点必须是 location: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="role",
                    code="role_type_mismatch",
                    expected="地点角色只用于 location 实体",
                )
            has_observation = any(
                value is not None for value in (arg.narrative_role, arg.action, arg.emotion)
            )
            if actual_type == EntityType.CHARACTER.value:
                if arg.narrative_role is None or arg.action is None or arg.emotion is None:
                    missing = [
                        name
                        for name, value in (
                            ("narrative_role", arg.narrative_role),
                            ("action", arg.action),
                            ("emotion", arg.emotion),
                        )
                        if value is None
                    ]
                    raise AnnotationStageRejection(
                        f"character 参与者必须同时提供 narrative_role/action/emotion，缺失: {', '.join(missing)}",
                        record=participant_record,
                        field=missing[0],
                        code="missing",
                        expected="三字段必填、不自动填默认值",
                    )
                self._reject_duplicate_observation(participant_record, entity_name, arg.action)
                self.observation_by_record[participant_record] = BoundCharacterObservation(
                    character=entity_name,
                    role_function=arg.narrative_role,
                    action=arg.action,
                    emotion=arg.emotion,
                )
            elif has_observation:
                raise AnnotationStageRejection(
                    f"narrative_role/action/emotion 只属于 character 参与者: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="narrative_role",
                    code="observation_on_noncharacter",
                    expected="非 character 条目只填 entityid/role",
                )
            try:
                participants.append(
                    EventParticipantInput(
                        entity=entity_name,
                        role=arg.role,
                        narrative_role=arg.narrative_role,
                        action=arg.action,
                        emotion=arg.emotion,
                    )
                )
            except ValidationError as exc:
                raise _translate_record_validation(participant_record, exc, tool_name="write_event") from None
        event.participants = participants
        self._rebuild_observation_payload()

    def _rebuild_observation_payload(self) -> None:
        """用于按写入顺序重建人物动态状态载荷"""
        observations = list(self.observation_by_record.values())
        self.domain_payloads["character_observations"] = observations
        self.bound_payloads["character_observations"] = observations

    def _reject_duplicate_observation(
        self,
        record: str,
        entity_name: str,
        action: str,
    ) -> None:
        """用于挡住同一人物的重复动态状态（人物,动作 在本 chunk 内唯一）

        写入点校验：触发时只拒绝这一条，已写入的记录与其他节点不受影响。
        """
        for other_record, observation in self.observation_by_record.items():
            if other_record == record:
                continue
            if (observation.character, observation.action) != (entity_name, action):
                continue
            raise AnnotationStageRejection(
                f"人物动态状态重复：{entity_name} 的动作 {action} 已记在 {other_record}",
                record=record,
                field="action",
                code="duplicate_observation",
                expected="同一人物在本 chunk 内的动作不得重复（改写动作或更新已记的那条）",
            )

    # ------------------------------------------------------------------
    # 2026-09-14 回执返回写入内容（用户裁决：所有 write 回执回显写入内容）：
    # content=本次写入的生效终值（服务端归一/端点解析已完成），不含 uuid

    def entity_content(self, entity: EntityInput) -> dict[str, Any]:
        """用于回显 write_entity 登记/更新后该实体生效记录（含服务端编号 n）"""
        stored = self.written_entities.get(_norm_entity_key(entity.name), entity)
        content = stored.model_dump(mode="json")
        content["n"] = self.graph.entity_number(stored.name) if self.graph is not None else None
        return content

    def metrics_content(self) -> dict[str, Any]:
        """用于回显 write_metrics 提交后的整域生效指标（整域覆盖，以最新回执为准）"""
        if self.metrics_payload is None:
            raise AnnotationInvariantError("write_metrics 回显需要 metrics_payload 已落账")
        return self.metrics_payload.model_dump(mode="json")

    def dialogue_content(self, candidate_index: int) -> dict[str, Any]:
        """用于回显 write_dialogue 后该候选的生效判定（speaker 已解析为登记名，带 candidate_key）"""
        content = self.written_dialogues[candidate_index].model_dump(mode="json")
        content["candidate_key"] = self.dialogue_candidates[candidate_index - 1].candidate_key
        return content

    def event_content(self, *, el: str, isroot: bool) -> dict[str, Any]:
        """用于回显 write_event 后该节点的服务端终值（id/描述/伏笔属性/参与者三态）

        el 与 isroot 是模型侧提交别名、树上不存储，因此不进 content；寻址面唯一在 record。
        """
        cleaned = unicodedata.normalize("NFC", el).strip()
        tree_key, _, node_key = cleaned.partition(_EL_PATH_SEP)
        tree = self.event_trees.get(self.tree_key_index.get(tree_key.strip(), ""))
        if tree is None:
            raise AnnotationInvariantError(f"write_event 回显需要账本内事件树: {tree_key}")
        if isroot or not node_key.strip():
            event = self._bound_event(str(tree["root_node_id"]))
        else:
            event = self._bound_event(str(tree["nodes"][node_key.strip()]))
        content: dict[str, Any] = {
            "node_id": str(event.node_id),
            "tree_id": str(event.tree_id),
            "description": event.description,
        }
        if isroot:
            content["isforeshadowing"] = bool(tree["isforeshadowing"])
            confidence = event.payoff_likelihood
            content["confidence"] = str(confidence) if confidence is not None else None
        else:
            content["type"] = str(event.cause_role)
        content["characters"] = [p.model_dump(mode="json") for p in event.participants]
        return content

    # ------------------------------------------------------------------
    # 收尾声明：唯一 finish_chapter，系统据此校验并冻结当前 chunk（冻结单位=整章）

    def finish_chapter(self) -> dict[str, Any]:
        """用于声明本章的语义写入已写完：补默认判定、校验并构造 ready_chunk

        写入是实时的，收尾只管一件件"把这个 chunk 组装出来"该管的事：指标缺提交则
        拒绝（没载荷装不出 chunk）。逐条记录写入是否成功不在收尾判定里——失败的调用
        在调用点就被单独拒绝并已回执，那条记录本来就没进图/进载荷，收尾按已写入内容
        完成即可；把收尾绑到无关记录的成功上，只会让"末轮出现一次失败"连带作废整章
        （run 1b388eb3 第 2 章实锤：末轮两条关系边被拒 + 收尾被拒 = 135 次调用全废）。
        构造失败整体回滚，已写入记录原样保留。
        """
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish_chapter")
        if self.metrics_payload is None:
            raise AnnotationStageRejection(
                "本章指标尚未提交，不予收尾",
                record="finish_chapter",
                field="metrics",
                code="missing_record",
                expected="先 write_metrics 提交摘要与叙事指标",
            )
        snapshot = self.snapshot()
        try:
            self._default_undecided_dialogues()
            self._ensure_domain_payloads()
            self.ready_chunk = self._build_ready_chunk()
        except Exception as exc:
            self.restore(snapshot)
            if isinstance(exc, AnnotationStageRejection):
                raise
            raise AnnotationStageRejection(
                f"章节收尾校验失败: {exc}",
                record="finish_chapter",
                code="assembly_failed",
                expected="按报错核对已写入的记录后重新 finish_chapter",
            ) from None
        self.write_records.extend(self._chunk_write_records())
        self.chapter_finished = True
        return {
            "status": "completed",
            "chunk_id": self.current_chunk_id,
            "records": self._written_counts(),
            "dialogue_defaulted": list(self.dialogue_missing_indexes),
        }

    def _default_undecided_dialogues(self) -> None:
        """用于收尾时把未提交判定的候选一次性按 not_dialogue 默认处理并留痕"""
        pending = sorted(set(range(1, len(self.dialogue_candidates) + 1)) - set(self.written_dialogues))
        self.dialogue_missing_indexes = pending
        if not pending:
            return
        for index in pending:
            self.written_dialogues[index] = DialogueInput(
                candidate_index=index,
                verdict=DialogueVerdict.NOT_DIALOGUE,
                speaker=None,
                tone=None,
            )
        self._rebuild_dialogue_payload()

    def _ensure_domain_payloads(self) -> None:
        """用于收尾时补齐空域载荷（零实体/零关系/零事件都是合法终态）"""
        self.domain_payloads.setdefault(
            "entities",
            EntityDirectoryInput(entities=list(self.written_entities.values())),
        )
        self.domain_payloads.setdefault("relations", list(self.written_relations.values()))
        self.domain_payloads.setdefault("dialogues", list(self.written_dialogues.values()))
        self.domain_payloads.setdefault("events", list(self.bound_payloads.get("events") or []))
        self.domain_payloads.setdefault(
            "character_observations",
            list(self.observation_by_record.values()),
        )
        self.bound_payloads.setdefault("events", list(self.domain_payloads["events"]))
        self.bound_payloads.setdefault(
            "character_observations",
            list(self.domain_payloads["character_observations"]),
        )
        self.bound_payloads.setdefault("dialogues", [])
        self.bound_payloads.setdefault("paragraph_labels", [])

    def _chunk_write_records(self) -> list[dict[str, Any]]:
        """用于收尾时把本次 chunk 的写入汇总成领域级审计记录（形状与此前一致）"""
        records: list[dict[str, Any]] = [
            {
                "chunk_id": self.current_chunk_id,
                "domain": "entities",
                "payload": EntityDirectoryInput(
                    entities=list(self.written_entities.values())
                ).model_dump(mode="json"),
            }
        ]
        if self.metrics_payload is not None:
            records.append(
                {
                    "chunk_id": self.current_chunk_id,
                    "domain": "metrics",
                    "payload": self.metrics_payload.model_dump(mode="json"),
                }
            )
        records.append(
            {
                "chunk_id": self.current_chunk_id,
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
                "chunk_id": self.current_chunk_id,
                "domain": "relations",
                "payload": [
                    item.model_dump(mode="json") for item in self.written_relations.values()
                ],
            }
        )
        records.append(
            {
                "chunk_id": self.current_chunk_id,
                "domain": "dialogues",
                "payload": [
                    item.model_dump(mode="json")
                    for item in (self.domain_payloads.get("dialogues") or [])
                ],
            }
        )
        return records

    def _event_tree_records(self) -> list[dict[str, Any]]:
        """用于按建树顺序汇总每棵树的结构（节点键与父子关系，不含真实 id）"""
        trees: list[dict[str, Any]] = []
        for tree_key, tree_id in self.tree_key_index.items():
            tree = self.event_trees.get(tree_id) or {}
            children: list[dict[str, Any]] = []
            for node_key, node_id in tree.get("nodes", {}).items():
                if node_key == _ROOT_NODE_KEY:
                    continue
                event = self._bound_event(str(node_id))
                children.append(
                    {
                        "node_key": node_key,
                        "type": str(event.cause_role),
                        "parent_node_key": self._node_key_of(tree, str(event.parent_node_id or "")),
                    }
                )
            root_event = self._bound_event(str(tree.get("root_node_id") or ""))
            trees.append(
                {
                    "tree_key": tree_key,
                    "description": root_event.description,
                    "isforeshadowing": bool(tree.get("isforeshadowing")),
                    "children": children,
                }
            )
        return trees

    def _node_key_of(self, tree: dict[str, Any], node_id: str) -> str | None:
        """用于按节点 id 反查章内节点键（审计记录不暴露真实 id）"""
        for node_key, candidate in tree.get("nodes", {}).items():
            if str(candidate) == node_id:
                return str(node_key)
        return None

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

    def _entity_catalog(
        self,
        directory: EntityDirectoryInput,
    ) -> tuple[dict[str, EntityType], dict[str, str]]:
        """2026-08-08 用于建立当前 chunk 唯一实体名称和类型目录"""
        types: dict[str, EntityType] = {}
        names: dict[str, str] = {}
        for entity in directory.entities:
            normalized = unicodedata.normalize("NFC", entity.name).strip()
            key = normalized.casefold()
            if key in types:
                raise ValueError(f"当前 chunk 实体名称重复: {normalized}")
            types[key] = entity.entity_type
            names[key] = normalized
        return types, names

    def _fact_entity_catalog(self) -> dict[str, EntityType]:
        """2026-08-10 用于合并内存图已登记实体与当前 chunk 已声明实体作为事实端点目录"""
        catalog = dict(self.graph.entity_types) if self.graph is not None else {}
        entities_payload = self.domain_payloads.get("entities")
        if entities_payload is not None:
            types, _names = self._entity_catalog(entities_payload)
            catalog.update(types)
        return catalog

    def _require_entity(
        self,
        name: str,
        *,
        entity_types: dict[str, EntityType],
        expected_types: tuple[EntityType, ...] | None = None,
        label: str,
    ) -> str:
        """2026-08-11 用于校验事实端点已由当前 chunk 实体目录或已登记实体声明（别名解析后）"""
        key = unicodedata.normalize("NFC", name).strip().casefold()
        resolved_key = key
        if self.graph is not None:
            resolved_key = _norm_graph_name(self.graph.resolve_name(name))
        actual_type = entity_types.get(resolved_key) or entity_types.get(key)
        if actual_type is None:
            raise ValueError(
                f"{label} 未在当前 chunk 登记: {name}（"
                "请先用 write_entity 登记该实体，或改用已登记实体名）"
            )
        if expected_types is not None and actual_type not in expected_types:
            raise ValueError(
                f"{label} 端点类型必须属于 {[str(t) for t in expected_types]}，实际为 {actual_type}"
                f"（该名称在图上的登记类型是 {actual_type}，"
                "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
            )
        return key

    # ------------------------------------------------------------------
    # 事件锚点与证据派生（2026-08-18 事件森林/DAG）
    # ------------------------------------------------------------------
    # 2026-08-22 重构：证据升为章级单份，由持久化层统一盖章，
    # 账本侧不再持有任何锚点/哈希派生逻辑

    def _validate_domain_duplicates(self, payloads: dict[str, Any]) -> None:
        """2026-08-07 用于拒绝当前 chunk 各领域的重复语义事实"""
        keys_by_domain: dict[str, list[tuple[Any, ...]]] = {
            "character_observations": [(item.character, item.action) for item in payloads["character_observations"]],
            "events": [(item.node_id,) for item in payloads.get("events") or []],
            "relations": [
                (
                    item.from_entity,
                    item.to_entity,
                    str(item.relation_type),
                )
                for item in payloads["relations"]
            ],
        }
        errors: list[str] = []
        for domain, keys in keys_by_domain.items():
            seen: dict[tuple[Any, ...], list[int]] = {}
            for index, key in enumerate(keys):
                seen.setdefault(key, []).append(index)
            for _key, indexes in seen.items():
                if len(indexes) > 1:
                    errors.append(f"[{', '.join(str(i) for i in indexes)}] {domain} 重复语义项")
        if errors:
            raise ValueError("；".join(errors))

    # ------------------------------------------------------------------
    # ready_chunk 构造与冻结
    # ------------------------------------------------------------------

    def _build_ready_chunk(self) -> BoundChunkAnnotation:
        """2026-08-20 用于从全部已接受领域校验并构造完整 BoundChunkAnnotation（优化：内联验证逻辑）"""
        payloads = self.domain_payloads
        entity_types, _entity_names = self._entity_catalog(payloads["entities"])
        resolved_entity_types = {
            **(self.graph.entity_types if self.graph is not None else {}),
            **entity_types,
        }

        # 2026-08-20 内联全量端点校验，合并 _validate_fact_endpoints 和 _validate_domain_endpoints
        errors: list[str] = []

        def check_entity(name: str, expected_types: tuple[EntityType, ...] | None, label: str, index: int) -> None:
            key = unicodedata.normalize("NFC", name).strip().casefold()
            resolved_key = key
            if self.graph is not None:
                resolved_key = _norm_graph_name(self.graph.resolve_name(name))
            actual_type = resolved_entity_types.get(resolved_key) or resolved_entity_types.get(key)
            if actual_type is None:
                errors.append(
                    f"[{index}] {label} 未在当前 chunk 登记: {name}"
                    "（请先用 write_entity 登记该实体，或改用已登记实体名）"
                )
                return
            if expected_types is not None and actual_type not in expected_types:
                errors.append(
                    f"[{index}] {label} 端点类型必须属于 {[str(t) for t in expected_types]}，"
                    f"实际为 {actual_type}（该名称在图上的登记类型是 {actual_type}，"
                    "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
                )

        # character_observations 端点校验
        for index, item in enumerate(payloads["character_observations"]):
            check_entity(item.character, (EntityType.CHARACTER,), "character_observation.character", index)

        # dialogues 端点校验
        for index, item in enumerate(payloads["dialogues"]):
            if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                check_entity(item.speaker, (EntityType.CHARACTER,), "dialogue.speaker", index)

        # 2026-08-22 事件契约：write_event 已在写入时内联校验参与者端点，此处不再重查

        # relations 端点校验
        for index, item in enumerate(payloads["relations"]):
            definition = RELATION_DEFINITIONS[str(item.relation_type)]
            check_entity(item.from_entity, definition["from_types"], "relation.from_entity", index)
            check_entity(item.to_entity, definition["to_types"], "relation.to_entity", index)

        if errors:
            raise ValueError("端点校验失败: " + "；".join(errors))

        self._validate_domain_duplicates(payloads)
        bound_dialogues = list(self.bound_payloads["dialogues"])
        # 2026-09-04 单一写面：entities/relations 不进 ready_chunk，
        # 图域真相源是 FactGraph 操作日志，持久化从其派生
        return BoundChunkAnnotation(
            chunk_id=self.current_chunk_id,
            metrics=payloads["metrics"],
            character_observations=list(self.bound_payloads["character_observations"]),
            dialogues=bound_dialogues,
            events=list(self.bound_payloads["events"]),
            paragraph_labels=list(self.bound_payloads.get("paragraph_labels") or []),
        )

    def _dialogue_coverage_warnings(self) -> list[str]:
        """2026-09-05 用于在冻结前确定性登记对话候选覆盖缺口（仅告警不阻断冻结）

        未提交判定的候选在收尾时统一按 not_dialogue 默认处理，这里把默认处理的
        缺口随 chunk 留痕，供报告附录 B 展示。
        """
        candidates = len(self.dialogue_candidates)
        if candidates == 0 or not self.dialogue_missing_indexes:
            return []
        return [
            f"对话覆盖: {len(self.dialogue_missing_indexes)} 条候选未提交判定"
            f"（序号 {self.dialogue_missing_indexes}），按 not_dialogue 默认处理"
        ]

    def _paragraph_label_coverage_warnings(self) -> list[str]:
        """2026-09-07 用于在冻结前确定性登记段落级监督覆盖缺口（仅告警不阻断冻结）

        每章 2-3 段为定稿密度（2026-09-14 由句级改段级）；低于 2 段（含空载荷）
        随 chunk 留痕，供 linguistic 阶段边界拟合的样本量判断与报告附录展示。
        """
        labels = self.bound_payloads.get("paragraph_labels") or []
        if len(labels) >= _PARAGRAPH_LABEL_MIN_PER_CHUNK:
            return []
        return [f"情绪标签覆盖: 仅标注 {len(labels)} 段（每章应自选 2-3 段）"]

    def complete_active_chunk(self) -> BoundChunkAnnotation:
        """用于在收尾声明后冻结当前 chunk（覆盖率告警随 chunk 留痕）"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 complete_chunk")
        if not self.chapter_finished:
            raise ValueError("当前 chunk 尚未收尾：先调用 finish_chapter")
        if self.ready_chunk is None:
            raise AnnotationInvariantError("已收尾但 ready_chunk 缺失，系统不变量被破坏")
        warnings = [*self._dialogue_coverage_warnings(), *self._paragraph_label_coverage_warnings()]
        chunk = self.ready_chunk.model_copy(update={"coverage_warnings": warnings}) if warnings else self.ready_chunk
        self.completed_chunks.append(chunk)
        # 2026-08-14 M6：当前章隐式授权（_resolve_case_details 按 current_chapter_id
        # 相等校验），不再登记文本授权集合
        # 2026-08-14 D1：不再有 continuity_open 阶段，冻结 chunk 后直接进入终态
        self.phase = "completed"
        return chunk

    def finish(self) -> BoundChapterAnnotation:
        """2026-08-11 用于在 chunk 冻结后由系统用各 chunk summary 生成章节摘要并冻结章节"""
        if self.phase != "completed":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish_chapter")
        annotation = BoundChapterAnnotation(
            chapter_summary="\n".join(chunk.metrics.summary for chunk in self.completed_chunks),
            chunks=list(self.completed_chunks),
        )
        self.annotation = annotation
        self.phase = "completed"
        return annotation

    # ------------------------------------------------------------------
    # 确定性上下文摘要与搜索压缩

    def _domain_fact_views(self) -> dict[str, Any]:
        """2026-08-10 用于生成当前候选各领域的事实语义键视图"""
        payloads = self.domain_payloads
        views: dict[str, Any] = {}
        if "metrics" in payloads:
            views["metrics"] = {
                "summary": payloads["metrics"].summary,
                "emotional_valence": str(payloads["metrics"].emotional_valence),
                "narrative_function": str(payloads["metrics"].narrative_function),
            }
        if "entities" in payloads:
            views["entities"] = {
                "items": len(payloads["entities"].entities),
                "names": [entity.name for entity in payloads["entities"].entities],
            }
        if "character_observations" in payloads:
            views["character_observations"] = [
                {
                    "character": item.character,
                    "action": item.action,
                }
                for item in payloads["character_observations"]
            ]
        if "dialogues" in payloads:
            views["dialogues"] = [
                {
                    "candidate_index": item.candidate_index,
                    "verdict": str(item.verdict),
                    "speaker": item.speaker,
                }
                for item in payloads["dialogues"]
            ]
        if "events" in payloads:
            views["events"] = [
                {
                    "node_id": item.node_id,
                    "tree_id": item.tree_id,
                    "parent_node_id": item.parent_node_id,
                    "cause_role": item.cause_role,
                    "description": item.description,
                    "participants": [
                        {
                            "n": (
                                self.graph.entity_number(participant.entity)
                                if self.graph is not None
                                else None
                            ),
                            "entity": participant.entity,
                            "role": str(participant.role),
                        }
                        for participant in item.participants
                    ],
                }
                for item in payloads["events"]
            ]
        if "relations" in payloads:
            views["relations"] = [
                {
                    "from": item.from_entity,
                    "to": item.to_entity,
                    "relation_type": str(item.relation_type),
                }
                for item in payloads["relations"]
            ]
        return views

    def context_summary(self) -> dict[str, Any]:
        """2026-08-10 用于从账本确定性生成当前模型请求的上下文摘要"""
        return {
            "phase": self.phase,
            "chunk_id": self.current_chunk_id,
            "chapter_finished": self.chapter_finished,
            # 2026-09-13 实时写入进度（仅供审计：模型看到的只有各小调用的回执）
            "written": self._written_counts(),
            "missing_content": self.missing_content_domains(),
            "entities": {
                "declared": [
                    {
                        "n": (
                            self.graph.entity_number(entity.name)
                            if self.graph is not None
                            else None
                        ),
                        "name": entity.name,
                        "entity_type": entity.entity_type,
                    }
                    for entity in self.domain_payloads.get("entities", EntityDirectoryInput()).entities
                ],
                "registered": (
                    [
                        {"n": self.graph.entity_number(display_name), "name": display_name,
                         "entity_type": self.graph.entity_types[key]}
                        for key, display_name in sorted(self.graph.entity_names.items())
                    ]
                    if self.graph is not None
                    else []
                ),
            },
            "facts": self._domain_fact_views(),
            "errors": list(self.errors),
            "cases": {
                "resolved": [
                    {
                        "case_id": item.case_id,
                        "type": item.type,
                        "action": item.action,
                    }
                    for item in self.resolved_cases
                ]
                + [
                    {
                        "case_id": op["case_id"],
                        "type": op["case_type"],
                        "action": "fact",
                    }
                    for op in (self.graph.relation_change_ops if self.graph is not None else [])
                ],
            },
            "search_log": list(self.search_log[-8:]),
        }

    def append_search_log(self, entry: dict[str, Any]) -> None:
        """2026-08-10 用于登记搜索结果压缩条目（查询、命中编号与 digest）"""
        self.search_log.append(entry)

    def missing_content_domains(self) -> list[str]:
        """2026-09-13 用于列出当前 chunk 尚无写入的领域（收尾提醒与审计共用）

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

    # ------------------------------------------------------------------
    # 章内并行两段式：写者取值域准入（设计文档 §7，防写者发明）

    def admit_entity_directory(self, entities: list[EntityInput]) -> None:
        """2026-09-12 用于校验 write_entity 实体名 ∈ 读者报告并集 ∪ 图中已登记名 ∪ 章正文逐字命中

        写者看不到正文，实体名的合法来源是读者报告（entities/event_trees/
        relations/dialogues/cases 各组）、历史已登记实体，或本章正文的逐字
        命中（09-12 放宽：报告并集是抽取面不是穷举面，实测 ch26 把写者从
        正文观察到的合法实体挡在门外且无法自纠）。报告、图与正文都不见的
        名字一律拒绝并给出可自纠报错。单块章（reader_reports=None）不受限。
        """
        if self.reader_reports is None:
            return
        report_keys = report_entity_name_keys(self.reader_reports)
        text_key = unicodedata.normalize("NFC", self.current_chunk_text).casefold()
        invented: list[str] = []
        for entity in entities:
            name_key = normalize_message_name(entity.name)
            if name_key in report_keys:
                continue
            if self.graph is not None and name_key in self.graph.entity_types:
                continue
            if name_key and name_key in text_key:
                continue
            invented.append(entity.name)
        if invented:
            raise ValueError(
                "write_entity 准入失败，以下实体名未出现在任何读者上报、图中登记或本章正文: "
                + "、".join(invented)
                + "（请原样使用读者报告中的实体名，或提交本章正文逐字出现的实体名；"
                "凭空拟造的名字不予接受）"
            )

    def admit_case_reason(self, reason: str, *, tool_name: str) -> None:
        """2026-09-12 用于校验案例裁决 reason 含至少一条案例报告引文片段（§7）

        reason 必须用读者报告引文拼装：包含任一已核验案例引文的原文或其
        ≥12 字连续片段即通过；unverified 引文不得支撑裁决（09-12 裁决，
        防幻觉硬门槛）。读者未上报任何案例观察时禁止一切裁决。单块章不受限。
        """
        if self.reader_reports is None:
            return
        quotes = report_case_quotes(self.reader_reports)
        normalized_reason = unicodedata.normalize("NFC", reason)
        min_fragment = 12
        for quote in quotes:
            if quote in normalized_reason:
                return
            for start in range(0, len(quote) - min_fragment + 1):
                if quote[start : start + min_fragment] in normalized_reason:
                    return
        if quotes:
            raise ValueError(
                f"{tool_name}.reason 准入失败：案例裁决理由必须包含读者案例观察的已核验引文片段"
                f"（原文或其 ≥{min_fragment} 字连续片段），不得自行转写。"
                "请从 <ReaderReports> 的 cases 观察 evidence 中摘录原文"
            )
        raise ValueError(
            f"{tool_name} 准入失败：读者未上报任何含已核验引文的案例观察，写者不得凭空裁决案例"
            "（引文未通过核验的观察不能支撑裁决）；"
            "若正文确有案例线索，请先用 ask_reader 向对应块读者追问"
        )


def _normalize_query(query: str, *, tool_name: str) -> str:
    """2026-08-07 用于统一校验查询工具输入长度与空白"""
    normalized = unicodedata.normalize("NFC", query).strip()
    if not normalized or len(normalized) > 2000:
        raise AnnotationInputError(f"{tool_name}.query 必须为 1 至 2000 个 Unicode 字符")
    return normalized


def _semantic_graph_value(value: Any) -> Any:
    """2026-08-07 用于递归移除图查询结果中的数据库定位字段"""
    if isinstance(value, dict):
        return {
            key: _semantic_graph_value(item)
            for key, item in value.items()
            if key not in _INTERNAL_GRAPH_KEYS and not key.endswith("_id")
        }
    if isinstance(value, list):
        return [_semantic_graph_value(item) for item in value]
    return value


def _norm_graph_name(name: str) -> str:
    """2026-08-11 用于生成与 FactGraph 一致的实体名称精确匹配键"""
    return unicodedata.normalize("NFC", name).strip().casefold()


def _short_pydantic_message(msg: str) -> str:
    """2026-09-12 用于剥离 pydantic 报错样板（Value error 前缀与文档链接尾注）"""
    cleaned = msg
    if cleaned.startswith("Value error, "):
        cleaned = cleaned[len("Value error, ") :]
    return re.sub(r"\s*\[type=[^\]]*\]$", "", cleaned)


# 2026-09-13 小调用改造：字段级取值域纠错文案（按 pydantic 失败族翻译成可自纠说明）
_EVENT_ROLE_VALUES_TEXT = "主体/客体/接收者/帮助者/反对者/见证者/地点"
_EVENT_NARRATIVE_ROLE_VALUES_TEXT = "主体/客体/发送者/接收者/帮助者/反对者/见证者"
_STAGE_FIELD_EXPECTATIONS: dict[str, str] = {
    "verdict": "dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选",
    "tone": tone_catalog_text(),
    "relation_type": "闭合关系类型（见 write_relation 参数说明）",
    "role": f"参与角色：{_EVENT_ROLE_VALUES_TEXT}",
    "narrative_role": f"人物叙事功能：{_EVENT_NARRATIVE_ROLE_VALUES_TEXT}",
    "entity_type": "character / location / item / organization",
    "narrative_function": "冲突 / 铺垫 / 转折",
    "confidence": "high / medium / low（伏笔回收可能性三档）",
    "payoff_likelihood": "high / medium / low",
    "type": '"main"（顺延主因链）或 "secondary"（挂在当时主链尾）',
    "emotion": "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    "emotional_valence": "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    "entityid": "实体引用：整数=运行期编号 n（write_entity / search_graph 回执），字符串=本 chunk 自定的 el 键",
    "speaker": "说话人实体引用：编号 n 或本 chunk 的 el 键",
    "candidate_index": "1 基候选序号（见 DialogueCandidates 表）",
    "el": "实体/事件节点的章内局部键（实体如 a1；事件根如 t1、子事件如 t1/e2），由你指定",
    "isroot": "true=建事件树根（el=树键），false=子事件（el=树键/节点键）",
    "characters": "参与者数组，每项 {entityid, role[, narrative_role, action, emotion]}（character 三态必填）",
    "labels": "段落情绪标签数组，每项 {paragraph_id, emotion}（paragraph_id 取正文 ¶ 号）",
    "paragraph_id": "本 chunk 内的段落号（正文 ¶ 后的数字）",
    "tags": f"字符串数组，{ENTITY_TAGS_RULE_TEXT}",
    "paragraph_ids": "全局段落 ID 列表",
    "summary": "本章摘要（非空文本）",
}
_STAGE_FIELD_CODES: dict[str, str] = {
    "missing": "missing",
    "enum": "invalid_value",
    "literal_error": "invalid_value",
    "int_parsing": "not_integer",
    "int_type": "not_integer",
    "int_from_float": "not_integer",
    "string_too_short": "too_short",
    "string_too_long": "too_long",
    "greater_than_equal": "out_of_range",
    "less_than_equal": "out_of_range",
    "greater_than": "out_of_range",
    "less_than": "out_of_range",
    "extra_forbidden": "unknown_field",
    # 记录级联合约束（三态字段组合、单表内一致性）由 model_validator 抛出
    "value_error": "invalid_combination",
}
# 2026-09-14 闭合枚举字段的拒绝文案：枚举类型只给出合法值本身，这里补上"没有贴合的用哪个"
_STAGE_ENUM_FALLBACKS: dict[str, str] = {
    "tone": "没有贴合的用「其他」",
}


def _translate_record_validation(
    record: str,
    exc: ValidationError,
    *,
    tool_name: str,
) -> AnnotationStageRejection:
    """2026-09-13 用于把单条记录的 pydantic 失败翻成结构化拒绝回执

    只报第一个失败字段：小调用的粒度就是一个字段一个语义单元，一次修一处。
    """
    errors = exc.errors()
    first = dict(errors[0]) if errors else {}
    raw_location = first.get("loc") or ()
    location = (
        [str(part) for part in raw_location if str(part) != "__root__"]
        if isinstance(raw_location, (list, tuple))
        else []
    )
    field = location[-1] if location else None
    kind = str(first.get("type") or "")
    code = _STAGE_FIELD_CODES.get(kind, kind or "invalid")
    expected = _STAGE_FIELD_EXPECTATIONS.get(field or "")
    detail = _short_pydantic_message(str(first.get("msg") or ""))
    message = f"{tool_name} 记录不符合合同: {field or '参数'} {detail}"
    if kind == "missing" and expected:
        message = f"{tool_name} 缺少必填字段 {field}：{expected}"
    if kind == "extra_forbidden":
        # 2026-09-13 未声明参数不再被静默丢弃：整条拒绝并指出多余字段名
        expected = "只提交本工具声明的参数（多余字段会被整条拒绝）"
        message = f"{tool_name} 不接受参数 {field}：该字段不属于本工具"
    if kind == "enum" and expected:
        # 2026-09-14 闭合枚举字段（tone 等）：pydantic 只说"输入必须是…"，把取值域与
        # 兜底指引写全，模型一次就能自纠（不回显整份合同）
        value = first.get("input")
        fallback = _STAGE_ENUM_FALLBACKS.get(field or "")
        suffix = f"（{fallback}）" if fallback else ""
        message = f"{tool_name} 记录不符合合同: {field} 只能是 {expected}{suffix}，收到 {value}"
    return AnnotationStageRejection(
        message,
        record=record,
        field=field,
        code=code,
        expected=expected or detail,
    )


def translate_write_validation_error(
    tool_name: str,
    args: dict[str, Any],
    exc: ValidationError,
) -> AnnotationStageRejection:
    """2026-09-13 用于把工具层 schema（langchain 参数绑定）失败翻成结构化拒绝回执

    schema 层的失败发生在工具函数体之前，记录键只能从原始参数拼装。
    """
    record = tool_record_key(tool_name, args) or tool_name
    return _translate_record_validation(record, exc, tool_name=tool_name)


def _is_foreshadowing_root(ledger: AnnotationToolLedger, root_event_id: str) -> bool:
    """2026-09-13 用于判定节点 id 是否为已知伏笔树根（历史树根视图 + 当前章 event_trees）"""
    for view in ledger.history_tree_views.values():
        if view.get("root_node_id") == root_event_id and view.get("is_foreshadow_setup"):
            return True
    for tree in ledger.event_trees.values():
        if tree.get("root_node_id") == root_event_id and tree.get("isforeshadowing"):
            return True
    return False


def _annotate_alias_links(
    response: dict[str, Any],
    *,
    ledger: AnnotationToolLedger,
    query_service: AnnotationQueryService,
) -> None:
    """2026-09-12 用于在 search_graph 回执上标注未决实体别名案例的关联节点

    同一对象的别名在案例确认前是图上两个独立节点，写者只更新其中一个时
    另一个保持旧值。命中节点旁标注同案例的其他键（编号取自图），更新任一即可
    （两端引用都解析到代表名）。展示即授权：被标注的案例按 search_pool 同款登记
    编号与源章。

    2026-09-13 文案纠偏：旧文案写"别名案例确认后系统会自动合并"，模型读成"什么都
    不用做"，于是案例永挂、每章被反复点名（run c80105cc 6 对到 run 死仍是 active）。
    改为直接给两条动作：是同一人物就写「同一人物」边，不是就 close_case 关闭。
    """
    pool_result = query_service.search_pool(
        None,
        hidden_case_ids=ledger.resolved_case_ids,
        case_type="entity_alias",
        limit=50,
    )
    alias_cases = [item for item in pool_result.results if isinstance(item, CaseSearchResult)]
    if not alias_cases:
        return
    views = [*response["matches"], *response["neighbors"]]
    annotated = False
    for view in views:
        name_key = normalize_message_name(str(view.get("name") or ""))
        if not name_key:
            continue
        links: list[dict[str, Any]] = []
        for case in alias_cases:
            if not any(normalize_message_name(key) == name_key for key in case.keys):
                continue
            others = [key for key in case.keys if normalize_message_name(key) != name_key]
            if not others:
                continue
            case_number = ledger.register_case_number(case.id)
            ledger.authorized_chapter_ids.add(case.chunk_id)
            linked = []
            for other in others:
                number = ledger.graph.entity_number(other) if ledger.graph is not None else None
                linked.append({"n": number, "name": other} if number is not None else {"name": other})
            links.append({"case_number": case_number, "linked": linked})
        if links:
            view["alias_linked"] = links
            annotated = True
    if annotated:
        response["alias_note"] = (
            "带 alias_linked 的节点存在未决的实体别名案例（编号见 case_number）："
            "确认是同一人物就用 write_relation 提交「同一人物」边，两端随即按一个节点归并；"
            "确认不是就用 close_case 关掉该编号。系统不会自行合并，未关闭的案例会一直留在案例池。"
        )


def _live_graph_response(
    graph: FactGraph,
    entities: list[str],
    *,
    relation_type: str | None,
    limit: int,
) -> dict[str, Any]:
    """2026-08-11 用于从常驻内存图回答节点邻域查询（运行时唯一图真相源）

    2026-09-11 每个实体视图携带运行期编号 n；events/relations/dialogues 的实体引用
    用该编号，不再用名称。
    """
    names_by_key = dict(graph.entity_names)
    tags_by_key = dict(graph.entity_tags)
    state_by_key = {
        key: {**dict(graph.entity_attributes.get(key) or {}), **dict(graph.entity_state.get(key) or {})}
        for key in names_by_key
    }
    matched_keys: set[str] = set()
    matches: list[dict[str, Any]] = []
    missing: list[str] = []
    for raw_name in entities:
        resolved_key = _norm_graph_name(graph.resolve_name(raw_name))
        display_name = names_by_key.get(resolved_key)
        if display_name is None:
            missing.append(raw_name)
            continue
        matched_keys.add(resolved_key)
        matches.append(
            {
                **graph.entity_view(resolved_key),
                "tags": list(tags_by_key.get(resolved_key) or []),
                "state": _semantic_graph_value(state_by_key[resolved_key]),
            }
        )

    relation_attributes = dict(graph.relation_attributes)
    relations: list[dict[str, Any]] = []
    neighbor_keys: set[str] = set()
    for from_key, to_key, rel_type in sorted(graph.active_relations):
        if relation_type is not None and rel_type != relation_type:
            continue
        if from_key not in matched_keys and to_key not in matched_keys:
            continue
        relations.append(
            {
                "from_name": names_by_key.get(from_key, from_key),
                "to_name": names_by_key.get(to_key, to_key),
                "relation_type": rel_type,
                "is_active": True,
                "attributes": _semantic_graph_value(dict(relation_attributes.get((from_key, to_key, rel_type)) or {})),
            }
        )
        if from_key not in matched_keys:
            neighbor_keys.add(from_key)
        if to_key not in matched_keys:
            neighbor_keys.add(to_key)
    relations = relations[:limit]

    neighbors = [{**graph.entity_view(neighbor_key), "state": _semantic_graph_value(state_by_key[neighbor_key])}
                 for neighbor_key in sorted(neighbor_keys)][:limit]

    return {
        "matches": matches[:limit],
        "missing": missing,
        "relations": relations,
        "neighbors": neighbors,
    }


class AskReaderDispatcher(Protocol):
    """2026-09-11 章内并行两段式：写者 ask_reader 的后端（工作流层实现，含轮数上限与读者续跑）"""

    async def ask(self, block: int, question: str) -> str:
        """2026-09-12 用于向指定子块（1 基）读者追问并同步取回其一次性补查报告"""


# 2026-09-13 只读检索工具不做参数收紧：多余参数没有副作用，忽略即可（拒绝只会白烧一个回合）
_ARGS_LENIENT_TOOL_NAMES = frozenset({"search_graph", "search_text", "search_event", "search_pool"})


def _forbid_undeclared_args(tool_candidate: Any) -> None:
    """2026-09-13 用于让写入类工具拒绝未声明参数

    langchain 由函数签名生成的参数模型默认 extra=ignore：模型多写的字段被静默丢弃，
    例如把 isforeshadowing 写到子事件上仍报 staged，语义丢失却看不出错。收紧为整条
    拒绝后，多余字段名随结构化回执回到模型，一次改一处。
    只读检索工具例外：多余参数没有副作用，忽略即可，拒绝只会白烧一个回合。
    """
    schema = tool_candidate.args_schema
    if schema is None or tool_candidate.name in _ARGS_LENIENT_TOOL_NAMES:
        return
    tool_candidate.args_schema = create_model(
        schema.__name__,
        __base__=schema,
        __config__=ConfigDict(extra="forbid"),
    )


def build_search_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
) -> list[Any]:
    """2026-09-11 用于构建读者与写者共用的四个只读检索工具（章内并行拆分面）"""

    @tool
    def search_graph(entities: list[str], relation_type: str | None = None) -> str:
        """2026-08-09 用于按实体名查询图节点及与其相连的一跳邻域（边和邻居节点）

        结果的 matches/neighbors 都带运行期编号 n；events/relations/dialogues 的
        实体引用一律填该编号。"""
        if ledger.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_graph")
        if not entities:
            raise AnnotationInputError("search_graph.entities 不能为空")
        normalized_entities = [_normalize_query(entity, tool_name="search_graph") for entity in entities]
        if ledger.graph is None:
            response: dict[str, Any] = {
                "matches": [],
                "missing": list(entities),
                "relations": [],
                "neighbors": [],
            }
        else:
            response = _live_graph_response(
                ledger.graph,
                normalized_entities,
                relation_type=relation_type,
                limit=50,
            )
            _annotate_alias_links(response, ledger=ledger, query_service=query_service)
        ledger.graph_queried = True
        ledger.append_search_log(
            {
                "tool": "search_graph",
                "query": list(normalized_entities),
                "hits": [item["name"] for item in response["matches"]],
                "digest": "",
            }
        )
        return json.dumps(response, ensure_ascii=False)

    @tool
    async def search_text(query: str) -> str:
        """2026-08-30 用于一次返回有限正文且不暴露内部段落标识

        查询支持多关键词（空格/标点分隔，任一命中即返回）与通配符
        （% 匹配任意长度、_ 匹配单个字符），如「伯安 偷%」或「赤羽_尾鸡」。"""
        normalized_query = _normalize_query(query, tool_name="search_text")
        if ledger.phase != "chunk_open":
            raise AnnotationAuthorizationError(f"阶段 {ledger.phase} 不允许 search_text")
        expected_range = "all" if ledger.allow_future_context else "previous"
        results = await query_service.search_text(
            normalized_query,
            range_name=expected_range,
            limit=8,
        )
        views: list[dict[str, Any]] = []
        for item in results[:8]:
            visible_content = item.content[:2000]
            ledger.authorized_text_paragraph_ids.update(item.paragraph_ids)
            views.append(
                {
                    "content": visible_content,
                    "truncated": len(item.content) > len(visible_content),
                    "keyword_score": item.keyword_score,
                    "semantic_score": item.semantic_score,
                }
            )
        ledger.append_search_log(
            {
                "tool": "search_text",
                "query": normalized_query,
                "hits": [f"result-{index}" for index in range(1, len(views) + 1)],
                "digest": "",
            }
        )
        return json.dumps(views, ensure_ascii=False)

    @tool
    def search_event(keyword: str) -> str:
        """2026-08-22 用于按关键词检索已完成章节的事件树并授权其 tree_id

        检索范围为树内任意节点的描述与参与者；查询支持多关键词
        （空格/标点分隔，任一命中即返回）与通配符
        （% 匹配任意长度、_ 匹配单个字符），如「伯安 偷%」。

        参与者的实体描述含运行期编号 n（图中已登记时）；因果前驱填 tree_id，
        resolve_foreshadowing_case 的树根/挂树事件填节点 id（树根视图带
        is_foreshadow_setup 与 foreshadowing_status，可据此发现活跃伏笔树）。"""
        normalized_query = _normalize_query(keyword, tool_name="search_event")
        if ledger.phase != "chunk_open":
            raise AnnotationAuthorizationError(f"阶段 {ledger.phase} 不允许 search_event")
        results = query_service.search_event_history(
            normalized_query,
            limit=20,
        )
        views: list[dict[str, Any]] = []
        for item in results:
            # root_node_id 供 resolve_foreshadowing_case 的树根/挂树事件引用
            ledger.authorized_event_ids.add(item.tree_id)
            ledger.authorized_event_ids.add(item.root_node_id)
            ledger.authorized_tree_ids.add(item.tree_id)
            ledger.history_tree_views[item.tree_id] = item.model_dump(mode="json")
            views.append(
                {
                    **item.model_dump(mode="json"),
                    "participants": _event_view_participants(item.participants, graph=ledger.graph),
                }
            )
        ledger.append_search_log(
            {
                "tool": "search_event",
                "query": normalized_query,
                "hits": [item["tree_id"] for item in views],
                "digest": "",
            }
        )
        return json.dumps({"trees": views}, ensure_ascii=False)

    @tool
    def search_pool(query: str | None = None, case_type: str | None = None) -> str:
        """2026-08-07 用于检索案例池并返回临时案例编号

        案例不在正文中注入，本工具是发现案例的唯一通道：
        - 只给 query：按关键词匹配案例 keys/description；
          查询支持多关键词（空格/标点分隔，任一命中即返回）与通配符
          （% 匹配任意长度、_ 匹配单个字符）。
        - 给 case_type（如 "entity_alias"/"伏笔疑点"，或 "all"）：按最新创建优先
          枚举该类型全部活动案例，不需要关键词；无命中提示时也可用它对案例重做全量枚举。
        回执 pool 汇报池内仍有检索价值的 active 案例总数与类型分布（resolved 不计）。
        本 chunk 内 push_case 登记的案例当章即可检索到（回执带 pending=true 标记）。"""
        if ledger.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_pool")
        normalized_query = (
            _normalize_query(query, tool_name="search_pool") if query is not None else None
        )
        normalized_type = (
            unicodedata.normalize("NFC", case_type).strip() if case_type is not None else None
        )
        if not normalized_query and not normalized_type:
            raise AnnotationInputError("search_pool.query 与 search_pool.case_type 至少提供一个")
        # 2026-09-13 登记即进池：本 chunk push_case 登记的案例也进检索面
        pending_ids = {case.target_key for case in ledger.pushed_cases}
        pending_views = [
            CaseSearchResult(
                id=case.target_key,
                type=case.type,
                chunk_id=ledger.current_chapter_id,
                created_chapter=ledger.current_chapter_id,
                keys=list(case.keys),
                description=case.description,
            )
            for case in ledger.pushed_cases
        ]
        result = query_service.search_pool(
            normalized_query,
            hidden_case_ids=ledger.resolved_case_ids,
            case_type=normalized_type,
            limit=50,
            pending_cases=pending_views,
        )
        views: list[dict[str, Any]] = []
        case_numbers: list[int] = []
        for item in result.results:
            if isinstance(item, CaseSearchResult):
                case_number = ledger.register_case_number(item.id)
                # 案例展示即授权其源章（§12.3 章级定位），解决时不再因原文未读取被拒
                ledger.authorized_chapter_ids.add(item.chunk_id)
                case_numbers.append(case_number)
                view = {
                    "result_kind": "case",
                    "case_number": case_number,
                    "type": item.type,
                    "created_chapter": item.created_chapter,
                    "description": item.description,
                    "keys": list(item.keys),
                }
                if item.id in pending_ids:
                    view["pending"] = True
                views.append(view)
        ledger.append_search_log(
            {
                "tool": "search_pool",
                "query": normalized_query,
                "case_type": normalized_type,
                "hits": case_numbers,
                "digest": "",
            }
        )
        response: dict[str, Any] = {
            "results": views,
            "pool": result.pool.model_dump(),
            "truncated": result.truncated,
        }
        if not views:
            if normalized_query:
                hint = f"关键词 {normalized_query} 无命中："
            elif normalized_type and normalized_type != "all":
                hint = f"case_type={normalized_type} 无匹配案例（类型名需与分析标签一致）："
            else:
                hint = "池内暂无可检索的活动案例："
            known_types = "、".join(sorted(result.pool.by_type)) or "（空）"
            response["hint"] = (
                f"{hint}当前池内类型分布 {known_types}；"
                '可用 case_type="all" 枚举全部未解决案例，或用关键词检索。'
            )
        return json.dumps(response, ensure_ascii=False)

    return [search_graph, search_text, search_event, search_pool]


def build_annotation_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
    *,
    ask_reader_dispatcher: AskReaderDispatcher | None = None,
) -> list[Any]:
    """2026-08-07 用于构建语义写入搜索解决和完成工具集

    2026-09-11 章内并行两段式：ask_reader_dispatcher 仅在写者面传入（§7 反问通道，
    用户裁决追问轮数进配置）；单块章不传，工具面与历史行为完全一致。"""

    @tool
    def write_metrics(
        summary: str,
        emotional_valence: int,
        narrative_function: NarrativeFunction,
        pivot_moment: bool = False,
        cliffhanger: bool = False,
        labels: list[ParagraphLabelInput] | None = None,
    ) -> str:
        """写入当前章节摘要、叙事指标与段落情绪标签（整域一次提交，写入即生效）

        emotional_valence 为情绪分值整数 -2..2（-2 强烈负面 / -1 轻微负面 / 0 中性 /
        1 轻微正面 / 2 强烈正面）；summary 为本章该 chunk 的摘要（章节摘要由系统拼接）。
        labels 为段落级情绪监督（每章自选 2-3 段）：paragraph_id 取正文 ¶ 后的数字
        （两段式取读者报告证据的 paragraph_id），emotion 同 emotional_valence；
        优先选情绪表达有代表性、或语气/标点有区分度的段落，也允许 0 分段。
        同一 chunk 重复提交整域按最后一次为准（labels 同理，按段号去重后覆盖）。
        回执 content 回显当前整域生效指标。
        """
        payload = ChunkMetricsInput(
            summary=summary,
            emotional_valence=emotional_valence,
            narrative_function=narrative_function,
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
            labels=list(labels or []),
        )
        ledger.apply_metrics(payload)
        return json.dumps(
            {"status": "written", "record": "metrics", "content": ledger.metrics_content()},
            ensure_ascii=False,
        )

    @tool
    def write_entity(
        name: str,
        entity_type: EntityType,
        el: EntityLocalKey,
        tags: Annotated[
            list[Annotated[str, Field(max_length=ENTITY_TAG_MAX_CHARS)]] | None,
            Field(
                max_length=ENTITY_TAG_MAX_COUNT,
                description=f"可空标签，{ENTITY_TAGS_RULE_TEXT}；省略=保留现有标签，提交空列表=清空",
            ),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="一句话简介；省略=保留现值"),
        ] = None,
        attributes: Annotated[
            dict[str, JsonValue | None] | None,
            Field(description="JSON Merge Patch：只写变化的键，值为 null 删除该键；省略=现有属性整体保留"),
        ] = None,
    ) -> str:
        """登记或更新一个实体（一次一个），el 是你自定的章内引用键、绑定即生效

        新实体用本章出现的名称；已登记实体用登记名，只提交本次变化的字段
        （description 一句话简介、tags 见参数说明、attributes 是 JSON Merge Patch）；
        未提交的字段保留现值。
        实体大类一经登记不可变更；同一词条的不同身份用区分性名称
        （如"圣城"是 location、"圣城朝堂"是 organization）。
        图中已有实体时，提交前必须先 search_graph 查询已登记实体。
        事件/关系/对话的实体引用用 el 键（同轮先登记后引用，不等回执）或
        回执/检索编号 n——write_event 的 characters[].entityid 等字段两者都收。
        回执 content 回显该实体合并后的生效记录（含服务端编号 n）。
        """
        if ledger.graph is not None and ledger.graph.entity_types and not ledger.graph_queried \
                and not ledger.entity_gate_passed:
            raise AnnotationAuthorizationError("提交 write_entity 前必须先调用 search_graph 查询已登记实体")
        entity = EntityInput(
            name=name,
            entity_type=entity_type,
            tags=tags or [],
            description=description,
            attributes=attributes,
        )
        present = {"name", "entity_type"}
        if tags is not None:
            present.add("tags")
        if description is not None:
            present.add("description")
        if attributes is not None:
            present.add("attributes")
        number = ledger.apply_entity(entity, el=el, present=present)
        ledger.entity_gate_passed = True
        bound_el = unicodedata.normalize("NFC", el).strip()
        return json.dumps(
            {
                "status": "written",
                "record": f"entity/{entity.name}",
                "el": bound_el,
                "n": number,
                "content": ledger.entity_content(entity),
            },
            ensure_ascii=False,
        )

    @tool
    def write_dialogue(
        candidate_index: int,
        verdict: DialogueVerdict,
        speaker: EntityRef | None = None,
        tone: Tone | None = None,
    ) -> str:
        """按候选编号写入一条对话候选的三态判断（一次一个候选，写入即生效）

        verdict: dialogue=真实对话 / inner_monologue=内心独白 /
        not_dialogue=误判候选（题字、描写被引号包裹等，此时只填 candidate_index 与 verdict）。
        speaker 是说话人的实体引用——本 chunk 自定的 el 键或回执编号 n，
        无法确认时留 null；tone 取参数说明里的闭合枚举，没有贴合的用「其他」。
        判定与写入不必一轮做完：每条判定彼此独立、写入即生效，重写同序号按更新语义处理。
        回执 content 回显该候选的生效判定（speaker 已解析为登记名，含候选账本标识 candidate_key）。
        """
        record = ledger.apply_dialogue(
            candidate_index=candidate_index,
            verdict=verdict,
            speaker_ref=speaker,
            tone=tone,
        )
        return json.dumps(
            {
                "status": "written",
                "record": record,
                "content": ledger.dialogue_content(candidate_index),
                "progress": {
                    "written": len(ledger.written_dialogues),
                    "total": len(ledger.dialogue_candidates),
                },
            },
            ensure_ascii=False,
        )

    @tool
    def write_relation(
        from_entity: EntityRef,
        to_entity: EntityRef,
        relation_type: Annotated[
            RelationType,
            Field(description="闭合关系类型，方向与两端实体类型约束如下：\n" + relation_catalog_text()),
        ],
    ) -> str:
        """写入一条本章确认存在的闭合关系边（一次一条，两端用 el 键或编号 n，写入即入图）

        关系类型是闭合词表：方向与两端实体类型约束见 relation_type 参数说明，端点类型
        不符会被拒（如 主从 只接受 character 起点、利益 两端都要 character/organization）；
        物品/地点做参与者时用 位于 等允许该类端点的关系，或改由人物之间的关系表达。
        本章正文确认的关系一律用本工具，不需要先 push_case 登记案例：resolve_fact_case
        只用于解决案例池里已登记的疑点，为一条本章确认的关系先登记再解决会白烧往返。
        新边建图 assert，重复提交同一条边自动去重；强化/削弱/解除一律走
        resolve_fact_case，不通过本工具表达变化。
        同一对端点重写（含换关系类型）按整体替换处理，写入顺序不影响终态。
        回执 content 回显该边当前生效内容（两端为登记名）。
        """
        record, outcome, content = ledger.apply_relation(
            from_ref=from_entity,
            to_ref=to_entity,
            relation_type=relation_type,
        )
        return json.dumps(
            {"status": "written", "record": record, "outcome": outcome, "content": content},
            ensure_ascii=False,
        )

    @tool
    def write_event(
        el: EventLocalKey,
        isroot: bool,
        description: str,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        type: EventChildType | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """写入一个事件节点：isroot=true 建事件树根（el=树键如 t1），false 加子事件（el=t1/e2）

        description 是一句话描述（根事件不超过 30 字）。整棵树可以在一轮里按顺序写完：
        先根后子逐个调用，el 由你指定、写入即生效，同轮后面的调用直接可用（不等回执）；
        树内先后=调用顺序，没有序号参数。子事件 type="main" 顺延主因链（成为新的
        链尾）/"secondary" 挂在当时主链尾；伏笔属性（isforeshadowing/confidence）只属于根：
        isforeshadowing=true 时 confidence 必填（high/medium/low），整棵树成为伏笔树、
        根即埋设事件。
        characters 是该节点的参与者数组（可省）：根节点也直接挂参与者。character 实体
        每条必须带 narrative_role/action/emotion 三态（action 不超过 15 字、emotion
        为 -2..2 整数；同一人物在本 chunk 内的动作不得重复），非 character（item/
        organization/location）条目只填 entityid/role，"地点"角色只用于 location。
        entityid 填本 chunk 的 el 键或回执/检索编号 n（编号引用历史实体）。
        同 el 重写按更新处理：根改描述/伏笔属性，子改描述（type 不可改写，要改换键）；
        characters 给出即整体替换该节点参与者列表，省略则保留。
        回执 content 回显该节点落账记录（node_id/tree_id/描述/参与者三态，根带伏笔属性现值、子带 type）。
        """
        record = ledger.apply_event(
            el=el,
            isroot=isroot,
            description=description,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
            node_type=type,
            characters=characters,
        )
        return json.dumps(
            {"status": "written", "record": record, "content": ledger.event_content(el=el, isroot=isroot)},
            ensure_ascii=False,
        )

    @tool
    def finish_chapter() -> str:
        """声明本章的语义写入已写完：本回合全部调用处理完后系统校验并冻结

        本章的全部内容（含整棵事件树）都可以在同一批调用里按顺序写完，末尾直接跟本工具，
        不必为了"先看回执"再拆一轮：局部键（实体 el、事件树键）由你指定、写入即生效，
        同批后面的调用直接可用。
        写入是实时生效的，本工具只做收尾：唯一会拒绝收尾的是指标（write_metrics）
        尚未提交——那时回执给出 missing_record，先补指标再收尾。
        本回合其他调用有没有失败与收尾无关：失败的那条只回滚它自己（回执已单独说明原因），
        没进图/没进载荷，收尾按已写入内容完成即可，不必为了收尾去重交失败记录。
        没有内容的领域不必造假数据，直接收尾即可（收尾回执给出各域写入条数）。
        收尾判定在本回合全部调用处理完后生效，通过后本章冻结、不再接受写入；
        不调用本工具，本章不会冻结。
        """
        return json.dumps({"status": "pending"}, ensure_ascii=False)

    if ask_reader_dispatcher is not None:

        @tool
        async def ask_reader(block: int, question: str) -> str:
            """2026-09-12 用于向指定子块读者追问并同步取回其补查报告（§7 反问通道）

            block 取 <ReaderReport> 标签的 block 编号（1 基）。追问会把对应读者
            带着完整原文上下文重新唤起，其补查的一次性报告随本回执直接返回；
            轮数上限由设置 writer_max_ask_rounds 控制（0 不限）。
            没有想清楚不要问，同一疑问不要重复问。"""
            normalized_question = unicodedata.normalize("NFC", question).strip()
            if not normalized_question:
                raise AnnotationInputError("ask_reader.question 不能为空")
            return await ask_reader_dispatcher.ask(block, normalized_question)

    def _resolve_case_details(
        *,
        ledger: AnnotationToolLedger,
        case_number: int,
        tool_name: str,
    ) -> ActiveCaseDetails:
        """2026-08-11 用于公共校验案例编号并回读活动案例稳定目标"""
        if ledger.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 {tool_name}")
        case_id = ledger.case_number_registry.get(case_number)
        if case_id is None:
            raise AnnotationAuthorizationError(
                f"case_number 未由 search_pool 检索或 push_case 登记返回: {case_number}："
                "案例不在正文中注入，请先 search_pool 检索（可用 case_type=\"all\" 枚举全部未解决案例）"
                "或用 push_case 登记新疑点，再用回执中的 case_number 解决"
            )
        if case_id in ledger.resolved_case_ids:
            raise AnnotationInputError(f"case_number 已经解决: {case_number}")
        # 2026-09-13 登记即进池：本 chunk 内 push_case 登记的案例当章即可解决——
        # 池行要到本章收尾才落库，此处用待建案例本体做稳定目标（id 即 target_key，
        # 与落库时的行 id 一致），源章就是当前章，无需再做展示授权校验。
        pending = ledger.pending_case_by_id(case_id)
        if pending is not None:
            return ActiveCaseDetails(
                id=pending.target_key,
                type=pending.type,
                chunk_id=ledger.current_chapter_id,
                created_chapter=ledger.current_chapter_id,
                keys=list(pending.keys),
                description=pending.description,
                target_key=pending.target_key,
                target_ref=dict(pending.target_ref),
            )
        details = query_service.fetch_active_case_details(case_id)
        if details is None:
            raise AnnotationInputError(f"案例不存在或已不再 active: {case_number}")
        # 2026-08-14 M6：案例源是章级定位——章被展示授权或为当前章即可解决
        allowed_chapter_ids = ledger.authorized_chapter_ids | {ledger.current_chapter_id}
        if details.chunk_id not in allowed_chapter_ids:
            raise AnnotationAuthorizationError(
                f"案例 {details.id} 原文所在章 {details.chunk_id} 未经本轮展示授权，"
                "请先 search_text 查询已授权前文后再解决"
            )
        return details

    def _require_dialogue_case(details: ActiveCaseDetails) -> None:
        """2026-09-08 用于校验案例确为带对话目标的对话类案例

        第16章死锁：模型把编号表里的 entity_alias/伏笔疑点案例误当对话疑点
        用 resolve_dialogue_case 解决，工具硬编码 action="dialogue" 入账，
        持久化按对话路径找不到对话记录直接崩溃。对话类案例的稳定判据是
        target_ref 含 dialogue_id（push_case(dialogue_id=...) 登记时写入），
        这里按结构拒绝，回执直接告诉模型正文候选的正确通道。
        """
        if details.target_ref.get("dialogue_id") or details.target_ref.get("candidate_key"):
            return
        raise AnnotationInputError(
            f"resolve_dialogue_case 只能解决含 dialogue_id 的对话类案例，案例 {details.id}"
            f"（{details.target_ref.get('kind') or '未知'}）没有对话目标："
            "正文对话候选的说话人/语气属于对话域，按 candidate_index 经对话域回执提交；"
            "疑点案例用 resolve_foreshadowing_case，关系事实用 resolve_fact_case，仅需关闭用 close_case"
        )

    def _require_suspicion_case(details: ActiveCaseDetails, tool_name: str) -> None:
        """2026-09-08 用于校验案例确为疑点类（伏笔线程确认只对疑点案例开放）

        关系事实/实体别名不是疑点：前者走 resolve_fact_case 建改删关系，
        后者确认后用 close_case 关闭；误走伏笔路径会凭空建立伏笔线程。
        """
        kind = details.target_ref.get("kind") or ""
        if kind.endswith("疑点"):
            return
        raise AnnotationInputError(
            f"{tool_name} 只能解决疑点类案例（伏笔疑点/连续性疑点等），"
            f"案例 {details.id} 的类型是 {kind or '未知'}："
            "关系事实用 resolve_fact_case，实体别名确认后用 close_case 关闭"
        )

    def _register_foreshadowing_case(
        ledger: AnnotationToolLedger,
        *,
        root_event_id: str,
        event_id: str,
        root_reference: str,
        event_reference: str,
    ) -> ActiveCaseDetails:
        """2026-09-13 用于为一次伏笔挂树自动登记「伏笔疑点」案例并回读其稳定目标

        run c80105cc 实测：case_number 曾为必填却在模型可见面上零说明，模型读完
        "章内局部键写入即生效"的 docstring 后判定"池里没有该伏笔案例、无法调用"，
        ch3/ch4 跨回合重推 4~8 次共约 3 万字符、只产出 1 次调用。挂树只认树根与
        挂树事件的键，案例只是池内记账：省略编号时由服务端补登记，编号随回执返回。
        """
        target_key = uuid4().hex
        ledger.pushed_cases.append(
            PendingCase(
                type="伏笔疑点",
                chunk_id=ledger.current_chunk_id,
                keys=[root_reference, event_reference],
                description=f"伏笔挂树：{root_reference} → {event_reference}"[:100],
                target_key=target_key,
                target_ref={
                    "kind": "伏笔疑点",
                    "chunk_id": ledger.current_chunk_id,
                    "root_event_id": root_event_id,
                    "event_id": event_id,
                },
            )
        )
        return _resolve_case_details(
            ledger=ledger,
            case_number=ledger.register_case_number(target_key),
            tool_name="resolve_foreshadowing_case",
        )

    def _append_resolved(
        ledger: AnnotationToolLedger,
        details: ActiveCaseDetails,
        resolved: ResolvedCase,
    ) -> str:
        """2026-08-11 用于登记解决结果并返回固定回执"""
        ledger.resolved_cases.append(resolved)
        case_number = ledger.case_number_by_id[details.id]
        return json.dumps(
            {"accepted": True, "case_number": case_number, "action": resolved.action},
            ensure_ascii=False,
        )

    def _require_action_entity(
        ledger: AnnotationToolLedger,
        name: str,
        *,
        expected_types: tuple[EntityType, ...],
        label: str,
    ) -> None:
        """2026-08-11 用于校验解决端点已由当前 chunk 或已登记实体声明"""
        entity_types = ledger._fact_entity_catalog()
        ledger._require_entity(
            name,
            entity_types=entity_types,
            expected_types=expected_types,
            label=label,
        )

    @tool
    def resolve_dialogue_case(
        case_number: CaseNumber,
        reason: str,
        speaker: EntityRef | None = None,
        tone: Tone | None = None,
        description: str | None = None,
        is_inner_monologue: bool | None = None,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为对话记录更新（至少提供一个更新字段）

        2026-09-10 编号判据：case_number 仅指 search_pool 展示的案例
        （含 push_case 登记的对话疑点）；正文 DialogueCandidates 无案例编号，
        说话人/语气按 candidate_index 经对话域回执提交，两类编号互不通用。

        2026-09-14 speaker 为实体引用（本 chunk 的 el 键或回执编号 n）；
        tone 取参数说明里的同一套闭合枚举。
        """
        ledger.admit_case_reason(reason, tool_name="resolve_dialogue_case")
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_dialogue_case",
        )
        _require_dialogue_case(details)
        resolved_speaker: str | None = None
        if speaker is not None:
            resolved_speaker = ledger.resolve_entity_ref(
                speaker,
                record=f"case/{case_number}",
                field="speaker",
            )
            _require_action_entity(
                ledger,
                resolved_speaker,
                expected_types=(EntityType.CHARACTER,),
                label="resolve_dialogue_case.speaker",
            )
        resolved = ResolvedCase(
            case_id=details.id,
            action="dialogue",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
            speaker=resolved_speaker,
            tone=tone,
            description=description,
            is_inner_monologue=is_inner_monologue,
        )
        return _append_resolved(ledger, details, resolved)

    @tool
    def resolve_fact_case(
        case_number: CaseNumber,
        reason: str,
        from_entity: EntityRef,
        to_entity: EntityRef,
        relation_type: Annotated[
            RelationType,
            Field(description="闭合关系类型，方向与两端实体类型约束如下：\n" + relation_catalog_text()),
        ],
        change_kind: RelationChangeKindArg,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为图关系建改删（change_kind 表达变化）

        2026-09-13 通道口径（run c80105cc 实测每章约 1.5K 字符在两条路之间权衡）：
        本工具只解决案例池里已登记的关系疑点（案例编号来自 search_pool 或 push_case
        回执）；本章正文确认的关系直接用写边工具提交，不要为它先 push_case 再解决。

        2026-09-14 端点 from_entity/to_entity 为实体引用（本 chunk 的 el 键或
        write_entity/search_graph 回执编号 n）；change_kind 取值：新增/强化/削弱/解除/修正/取代/撤回。
        relation_type 的闭合词表与两端实体类型约束同在建边工具（见本参数说明）；
        解除/修正/取代/撤回要求该边当前活动，对不存在的边操作会报错并回滚本回合。

        2026-09-04 单一写面：本工具只更新内存 FactGraph（终态即时生效 +
        操作日志登记），不再向 resolved_cases 追加 fact 动作；持久化层从
        操作日志派生关系事实。解除不存在的边会直接报错并回滚本回合，
        避免"accepted 但 search_graph 不变"的空转。"""
        ledger.admit_case_reason(reason, tool_name="resolve_fact_case")
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_fact_case",
        )
        definition = RELATION_DEFINITIONS.get(relation_type)
        if definition is None:
            raise AnnotationInputError(f"resolve_fact_case.relation_type 必须是闭合关系类型: {relation_type}")
        if ledger.graph is None:
            raise AnnotationInvariantError("resolve_fact_case 需要常驻事实图，graph 缺失")
        # 2026-09-11 模型面中文词 → 内部英文值域（持久化/API/前端契约零变化）
        internal_change_kind = RELATION_CHANGE_KIND_LABELS[str(change_kind)]
        from_name = ledger.resolve_entity_ref(from_entity, record=f"case/{case_number}", field="from_entity")
        to_name = ledger.resolve_entity_ref(to_entity, record=f"case/{case_number}", field="to_entity")
        _require_action_entity(
            ledger,
            from_name,
            expected_types=tuple(definition["from_types"]),
            label="resolve_fact_case.from_entity",
        )
        _require_action_entity(
            ledger,
            to_name,
            expected_types=tuple(definition["to_types"]),
            label="resolve_fact_case.to_entity",
        )
        ledger.graph.apply_relation_change(
            from_entity=from_name,
            to_entity=to_name,
            relation_type=relation_type,
            change_kind=internal_change_kind,
            reason=reason,
            case_id=details.id,
            case_type=details.type,
            target_key=details.target_key,
            target_ref=details.target_ref,
            chapter_id=ledger.current_chunk_id,
        )
        case_number = ledger.case_number_by_id[details.id]
        return json.dumps(
            {"accepted": True, "case_number": case_number, "action": "fact"},
            ensure_ascii=False,
        )

    @tool
    def resolve_foreshadowing_case(
        *,
        case_number: Annotated[
            int | None,
            Field(
                description=(
                    f"{CASE_NUMBER_RULE}；省略则由服务端就本次挂树自动登记一条"
                    "「伏笔疑点」案例并回执编号"
                )
            ),
        ] = None,
        reason: str,
        foreshadowing_action: str,
        root_event_id: str,
        event_id: str,
        payoff_likelihood: Confidence | None = None,
        strength: Confidence | None = None,
    ) -> str:
        """2026-08-11 用于把本章事件挂进伏笔树（续接或回收）

        2026-09-13 伏笔即事件树：root_event_id 是伏笔树的根（埋设事件），event_id 是
        本章要挂进树的事件。两者都填章内局部键（事件回执的 t1、t1/e1）或
        search_event 树根视图的 root_node_id；章内局部键写入即生效，随时可用。
        foreshadowing_action 只能是 "reinforce"（续接）
        或 "payoff"（回收，挂入后伏笔树收束为 likely_paid_off）。可选更新根属性
        payoff_likelihood/strength（high/medium/low）；判断并非伏笔则用
        close_case。活跃伏笔树的发现通道是 search_event（树根视图带
        foreshadowing_status）；新伏笔树用 write_event(isroot=true, isforeshadowing=true)
        建根。case_number 可以省略：挂树只认树根与挂树事件的键，案例仅是池内记账，
        省略时服务端自动登记一条「伏笔疑点」案例并随回执给出编号；池里已有
        对应疑点案例时把 search_pool 回执里的编号传进来即可。"""
        ledger.admit_case_reason(reason, tool_name="resolve_foreshadowing_case")
        details: ActiveCaseDetails | None = None
        if case_number is not None:
            details = _resolve_case_details(
                ledger=ledger,
                case_number=case_number,
                tool_name="resolve_foreshadowing_case",
            )
            _require_suspicion_case(details, "resolve_foreshadowing_case")
        if foreshadowing_action not in ("reinforce", "payoff"):
            raise AnnotationInputError(
                f"resolve_foreshadowing_case.foreshadowing_action 只能是 \"reinforce\"（续接）"
                f"或 \"payoff\"（回收）: {foreshadowing_action!r}"
            )
        # 收窄到 Literal 供 ResolvedCase 校验（上方成员检查保证二值）
        action: Literal["reinforce", "payoff"] = (
            "reinforce" if foreshadowing_action == "reinforce" else "payoff"
        )
        root_event_reference, event_reference = root_event_id, event_id
        for field_name, value in (("root_event_id", root_event_id), ("event_id", event_id)):
            resolved_id = ledger.resolve_event_reference(value)
            if resolved_id is None:
                # 2026-09-04 第6章教训：历史视图同时给出 tree_id 与 root_node_id，
                # 模型易把 tree_id 当节点 id 传 → 空转至回合上限，此处点名这层混淆。
                hint = (
                    "（这是事件树的 id 而非节点 id；本章事件用章内局部键 t1/e1，"
                    "历史事件用 search_event 树根视图的 root_node_id）"
                    if value in ledger.authorized_tree_ids
                    else "（本章事件用章内局部键，如 t1、t1/e1；历史事件用 search_event 的 root_node_id）"
                )
                raise AnnotationAuthorizationError(
                    f"{field_name} 未由事件回执或 search_event 授权: {value}{hint}"
                )
            if field_name == "root_event_id":
                root_event_id = resolved_id
            else:
                event_id = resolved_id
        if event_id == root_event_id:
            raise AnnotationInputError(
                "event_id 不得与 root_event_id 相同（埋设事件自身不挂边）: "
                f"{root_event_reference} / {event_reference}"
            )
        if not _is_foreshadowing_root(ledger, root_event_id):
            raise AnnotationInputError(
                f"root_event_id 不是伏笔树的根（埋设事件）: {root_event_id}；"
                "活跃伏笔树用 search_event 检索（树根视图 isforeshadow_setup=true），"
                "新伏笔树用 write_event(isroot=true, isforeshadowing=true) 建根"
            )
        # 全部挂树校验通过后才补登记案例：被拒的调用不得在池里留下孤儿活动案例
        if details is None:
            details = _register_foreshadowing_case(
                ledger,
                root_event_id=root_event_id,
                event_id=event_id,
                root_reference=root_event_reference,
                event_reference=event_reference,
            )
        resolved = ResolvedCase(
            case_id=details.id,
            action="foreshadowing",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
            foreshadowing_action=action,
            foreshadowing_root_event_id=root_event_id,
            foreshadowing_event_id=event_id,
            payoff_likelihood=payoff_likelihood,
            strength=strength,
        )
        return _append_resolved(ledger, details, resolved)

    @tool
    def close_case(case_number: CaseNumber, reason: str) -> str:
        """2026-08-11 用于通过临时编号关闭案例（不产生任何语义变化，仅标记已解决）"""
        ledger.admit_case_reason(reason, tool_name="close_case")
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="close_case",
        )
        resolved = ResolvedCase(
            case_id=details.id,
            action="close",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
        )
        return _append_resolved(ledger, details, resolved)

    @tool
    def push_case(
        description: str,
        keys: list[str],
        type: str,
        dialogue_id: str | None = None,
    ) -> str:
        """2026-08-11 用于把分析中发现的新连续性疑点创建为新案例登记进案例池
        （type 是任意描述字符串；description 只写人类可读说明且不超过 100 字，
        keys/type/dialogue_id 必须作为独立参数提交，示例：
        push_case(description="玉戒尺在第 5 章异常发光", keys=["玉戒尺"], type="伏笔疑点")）

        2026-09-13 登记即进池：回执直接给出案例编号，本案例本章内就能用
        search_pool 检索到、也能直接用该编号 resolve_*（本章收尾时它才作为案例池
        行落库，但检索与解决面当章即可用）。"""
        if ledger.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 push_case")
        normalized_type = unicodedata.normalize("NFC", type).strip()
        if not normalized_type:
            raise AnnotationInputError("push_case.type 不能为空")
        normalized_description = unicodedata.normalize("NFC", description).strip()
        if not normalized_description:
            raise AnnotationInputError("push_case.description 不能为空")
        if len(normalized_description) > 100:
            raise AnnotationInputError(
                "push_case.description 不能超过 100 字，请精简为人类可读要点"
                "（案例检索载荷有长度上限）"
            )
        json_marker_fields = ('"keys"', '"type"', '"dialogue_id"')
        if any(marker in normalized_description for marker in json_marker_fields):
            raise AnnotationInputError(
                "push_case.description 只接受人类可读说明；keys/type/dialogue_id"
                " 必须作为独立参数提交，不能写入 description 字符串"
            )
        normalized_keys = [unicodedata.normalize("NFC", key).strip() for key in keys]
        if not normalized_keys or any(not key for key in normalized_keys):
            raise AnnotationInputError("push_case.keys 不能为空")
        if len(set(normalized_keys)) != len(normalized_keys):
            raise AnnotationInputError("push_case.keys 不允许重复")
        target_ref: dict[str, Any] = {
            "kind": normalized_type,
            "chunk_id": ledger.current_chunk_id,
            "keys": normalized_keys,
        }
        if dialogue_id is not None:
            normalized_dialogue_id = unicodedata.normalize("NFC", dialogue_id).strip()
            candidate_keys = {candidate.candidate_key for candidate in ledger.dialogue_candidates}
            if normalized_dialogue_id not in candidate_keys:
                raise AnnotationInputError(
                    f"push_case.dialogue_id 不是当前 chunk 的对话候选 id: {normalized_dialogue_id}"
                )
            target_ref["dialogue_id"] = normalized_dialogue_id
        target_key = uuid4().hex
        pushed = PendingCase(
            type=normalized_type,
            chunk_id=ledger.current_chunk_id,
            keys=normalized_keys,
            description=normalized_description,
            target_key=target_key,
            target_ref=target_ref,
        )
        ledger.pushed_cases.append(pushed)
        # 2026-09-13 登记即进池：当场分配运行期案例编号，检索面与解决面当章可用
        case_number = ledger.register_case_number(target_key)
        response = {
            "accepted": True,
            "case_number": case_number,
            "target_key": target_key,
            "note": (
                "案例已登记进案例池：本章内即可用 search_pool 检索到，也可直接用本编号"
                "resolve_dialogue_case/resolve_fact_case/resolve_foreshadowing_case/close_case"
                "解决；本章收尾时它作为活动案例落库。"
            ),
        }
        return json.dumps(response, ensure_ascii=False)

    tools = [
        write_entity,
        write_metrics,
        write_event,
        write_relation,
        write_dialogue,
        finish_chapter,
        *build_search_tools(query_service, ledger),
        resolve_dialogue_case,
        resolve_fact_case,
        resolve_foreshadowing_case,
        close_case,
        push_case,
    ]
    if ask_reader_dispatcher is not None:
        tools.append(ask_reader)
    for tool_candidate in tools:
        _forbid_undeclared_args(tool_candidate)
    return tools


__all__ = [
    "AnnotationQueryService",
    "AnnotationToolLedger",
    "build_annotation_tools",
]
