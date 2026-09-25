"""
章节标注语义写入工具与系统运行账本

核心合同: 写入面为五个领域工具（write_entity / write_metrics / write_event /
write_relation / write_dialogue），实体与事件节点用模型自定的 el 局部键寻址、
写入即生效并返回真实回执（{status: written, record}）；领域没有结束声明，
全部写完后用唯一 finish 收尾，系统据此刻校验并冻结当前章。
完整参数和完整结果只进入审计库，不回到模型上下文。

2026-09-19 id 纪律（模型面三条款）：所有 id 都是 run 级 uuid——实体 id 由服务端按
run+规范名确定性铸造（uuid5，回执与落库主键同值），事件节点 id 服务端生成（uuid4，
=落库 event_id），案例 id 就是案例池行的 uuid；别名只能是 el（模型自定的局部键，
写入当场绑定，仅供同轮引用）；一个事件或实体或操作只有一个 id——回执与检索
视图里对象只带 id，record 是本章 的写入地址、不是第二 id。
2026-09-14 写入面重构：根/子/两参与者五工具合并为 write_event（el 层级键挂树、
树内先后=调用顺序）；句标签收编进 write_metrics.labels（段落级监督）；实体
引用增加 el 键空间；伏笔属性收敛为 isforeshadowing+confidence。
2026-09-13 改造前是"一次大载荷 write 完成整个领域"（整树起草 + 整批返工）：
先拆成同轮多个有类型小调用，再取消暂存概念——没有暂存区，
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
from .schema import (
    CLIFFHANGER_DESCRIPTION,
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ENTITY_TAGS_RULE_TEXT,
    FORESHADOWING_ACTIONS,
    PIVOT_MOMENT_DESCRIPTION,
    RELATION_CHANGE_KIND_LABELS,
    RELATION_DEFINITIONS,
    ActiveCaseDetails,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundDialogue,
    BoundEvent,
    BoundParagraphLabel,
    CaseSearchResult,
    ChapterMetricsInput,
    ChapterParagraphInfo,
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
    EvidenceNumber,
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
# write_event，收尾唯一 finish——五个领域写工具从首轮起全部开放。
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
# 2026-09-18 案例面收成 push_case + promise_case + close_case：兑现只记产出记录键、关闭
# 无语义变化，两者都不是写入动作，但参数校验失败仍走同一条结构化翻译路径（进本集合）。
_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    [tool_name for tool_names in _DOMAIN_WRITE_TOOLS.values() for tool_name in tool_names]
    + ["promise_case", "close_case"]
)
# 失败归因表：领域 → 写入工具（2026-09-14 写入面合并后无例外项）
_WRITE_TOOL_DOMAINS: dict[str, str] = {
    tool_name: domain
    for domain, tool_names in _DOMAIN_WRITE_TOOLS.items()
    for tool_name in tool_names
}
# 2026-09-18 收尾工具名（单一来源）：写者面的绑定面与 subagent 面的绑定面同名，
# 但只有写者面的 finish 是"章级收尾"（冻结整章、结算推迟到本回合全部调用之后），
# subagent 面的 finish 只声明本 subagent 完毕。判章级收尾一律比这个名字，不看调用来源；
# 分面差异由 graph._execute_call 的 chapter_finish_name 参数表达（subagent 面传 None）。
FINISH_TOOL_NAME: str = "finish"
# 2026-09-13 五域固定遍历顺序：工具面排序、缺内容提醒与写入计数共用（无逐域结束声明）
_DOMAIN_ORDER = ("entities", "metrics", "events", "relations", "dialogues")
# 2026-09-07 监督标签冻结软下限（每章 2-3 段定稿）：低于 2 留痕覆盖告警，不阻断冻结
_PARAGRAPH_LABEL_MIN_PER_CHAPTER = 2
_INTERNAL_GRAPH_KEYS = {
    "candidate_key",
    "chapter_id",
    "end",
    "fact_id",
    "relation_id",
    "representative_entity_id",
    "start",
}
# 2026-09-19 历史事件视图里的内部定位字段不进模型面（id 纪律后运行面 id 就是这个 uuid，
# 由 _event_view_participants 换成 "id" 键给出）
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

# 2026-09-19 案例面 id 化：案例的稳定身份就是案例池行的 uuid（本章 待建案例=push_case
# 生成的 target_key），无运行期编号；四个案例工具共用同一句参数说明
CASE_ID_RULE = "案例 id：search_pool 或 push_case 回执给出的 id（案例不在正文注入，检索即授权）"
CaseId = Annotated[str, Field(min_length=1, description=CASE_ID_RULE)]


def tool_record_key(tool_name: str, args: dict[str, Any]) -> str | None:
    """2026-09-13 用于按工具名与原始参数生成稳定记录键（成功回执与拒绝回执共用）

    参数可能是未过 schema 的原始值，此处只做展示级拼接、不做校验；
    键在 章收尾前保持稳定，重写同键即更新同一条记录。
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
    """2026-09-11 用于把历史事件参与者视图换成模型面 id（2026-09-19 id 即 uuid）

    参与者描述里的内部字段（entity_id）剥掉；id 优先取运行图按名铸造的
    uuid5（与回执同值），图中未登记时兜底用历史视图带的落库 id（同一 uuid 口径）。
    """
    views: list[dict[str, Any]] = []
    for participant in participants:
        descriptor = participant.get("entity")
        cleaned = {key: value for key, value in participant.items() if key != "entity"}
        if isinstance(descriptor, dict):
            raw_entity_id = descriptor.get("entity_id")
            descriptor = {key: value for key, value in descriptor.items() if key not in _INTERNAL_ENTITY_KEYS}
            name = descriptor.get("name")
            runtime_id = graph.entity_id(str(name)) if graph is not None and name else None
            entity_id = runtime_id or (str(raw_entity_id) if raw_entity_id else None)
            if entity_id is not None:
                descriptor["id"] = entity_id
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

        2026-09-13 登记即进池：pending_cases 是本 章内 push_case 登记的待建案例，
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

    def has_dialogue_record(self, candidate_key: str) -> bool:
        """2026-09-18 用于判一条对话记录是否已在本 run 落库（订正既有对话记录的前置校验）"""


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
    phase: str = "chapter_open"
    dialogue_candidates: list[DialogueCandidate] = field(default_factory=list)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)
    write_records: list[dict[str, Any]] = field(default_factory=list)
    completed_chapters: list[BoundChapterAnnotation] = field(default_factory=list)
    ready_chapter: BoundChapterAnnotation | None = None
    # 2026-09-11 案例改检索制：正文不再注入案例表，案例只经 search_pool 展示登记
    # 2026-09-19 案例 id 纪律：无运行期编号，案例身份=池行 uuid（待建案例=push_case 的
    # target_key）；known_case_ids 是授权面——只有展示过或登记过的 id 可进入解决流程。
    known_case_ids: set[str] = field(default_factory=set)
    resolved_cases: list[ResolvedCase] = field(default_factory=list)
    pushed_cases: list[PendingCase] = field(default_factory=list)
    # 2026-08-14 M6：案例展示/解决授权章（案例源是章级定位，§12.3）
    authorized_chapter_ids: set[int] = field(default_factory=set)
    # 2026-08-30：search_text 返回正文时登记真实 SQL 命中段落
    authorized_text_paragraph_ids: set[int] = field(default_factory=set)
    # 2026-08-12 收尾时未提交判定的对话候选序号（系统按 not_dialogue 默认处理）
    dialogue_missing_indexes: list[int] = field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（仅留痕不阻断），随章持久化
    coverage_warnings: list[str] = field(default_factory=list)
    annotation: BoundChapterAnnotation | None = None
    errors: list[str] = field(default_factory=list)
    search_log: list[dict[str, Any]] = field(default_factory=list)
    graph: FactGraph | None = None
    # 2026-08-18 事件森林/DAG：本章 的段落坐标映射，用于事件锚点校验和证据派生
    paragraph_info: ChapterParagraphInfo | None = None
    # 2026-08-22已写事件节点 id（含历史树根），供伏笔 setup/payoff 授权
    authorized_event_ids: set[str] = field(default_factory=set)
    # 2026-09-04事件树 id 集合：setup/payoff 误传 tree_id 时给出针对性纠错提示
    authorized_tree_ids: set[str] = field(default_factory=set)
    # 2026-08-19 当前章节序号（写章指标与上下文摘要展示用）
    current_chapter_order: int | None = None
    # 2026-08-22本章事件树状态（单章闭环）；历史树视图缓存供伏笔树根判定引用
    event_trees: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_tree_views: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 2026-09-13 实时写入（取消暂存）：每次小调用即时落到目标结构，回执即当前真相。
    # 全部进 snapshot/restore——单次调用失败只回滚该调用，之前写入的记录必须保留
    written_entities: dict[str, EntityInput] = field(default_factory=dict)
    metrics_payload: ChapterMetricsInput | None = None
    written_dialogues: dict[int, DialogueInput] = field(default_factory=dict)
    # 有序对 → 关系记录（同一对端点换类型即整体替换，保持"本章关系=完整集合"语义）
    written_relations: dict[tuple[str, str], RelationInput] = field(default_factory=dict)
    # 人物动态状态按记录键持有（重写同一参与者即更新，键给回执定位用）
    observation_by_record: dict[str, BoundCharacterObservation] = field(default_factory=dict)
    # tree_key → tree_id：章内局部键是模型侧寻址面，真实 uuid 不外露
    tree_key_index: dict[str, str] = field(default_factory=dict)
    # 2026-09-14 实体局部键索引：el → 归一化登记名（模型自定、写入即绑定、同轮可用）
    entity_el_index: dict[str, str] = field(default_factory=dict)
    # 2026-09-18 本章已经写出来的记录键集合（程序面每次调用成功即登记）：
    # promise_case 的 result_id 与 push_case 的 record_id 按它校验，模型只能指向真实产出
    written_record_keys: set[str] = field(default_factory=set)
    # 2026-09-13 收尾声明：唯一 finish 置位后由系统冻结当前章
    chapter_finished: bool = False

    def __post_init__(self) -> None:
        """2026-08-07 用于初始化唯一章的对话候选"""
        if not self.current_chapter_text.strip():
            raise AnnotationInputError("current_chapter_text 不能为空")
        self.dialogue_candidates = extract_dialogue_candidates(
            self.current_chapter_id,
            self.current_chapter_text,
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
        """2026-09-13 用于按 target_key 查找本 章内 push_case 登记的待建案例

        登记即进池：案例 id 在 push_case 当场生成（=target_key），检索面（search_pool）
        与解决面（_resolve_case_details）都按同一 id 认这条案例，直到本章收尾
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
                "completed_chapters": self.completed_chapters,
                "ready_chapter": self.ready_chapter,
                "known_case_ids": self.known_case_ids,
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
                "written_record_keys": self.written_record_keys,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-10 用于在单个工具调用失败时恢复该调用开始前的账本状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

    def resolve_event_reference(self, reference: str) -> str | None:
        """2026-09-13 用于把模型面的事件引用翻成真实节点 id（2026-09-19 收两种形态）

        id 纪律下模型面只有两种引用：run 级 uuid id（=回执/检索视图里的节点 id，
        已在授权集合里的原样放行）与本章 的 el 别名（t1 指根、t1/e2 指子）。
        键不存在时返回 None，由调用方按"未授权"处理并给出针对性提示。
        """
        text = str(reference).strip()
        if text in self.authorized_event_ids:
            return text
        tree_key, _, node_key = text.partition("/")
        tree = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if tree is None:
            return None
        node_id = tree["nodes"].get(node_key or _ROOT_NODE_KEY)
        return str(node_id) if node_id else None

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
                    "已登记实体的 run 级 id（write_entity / search_graph 回执）或本章自定的 el 键；"
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
        """用于在每个写入入口统一校验阶段（章冻结后不再接受写入）"""
        if self.phase != "chapter_open":
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
    # 实体域：登记即入图并绑定 run 级 uuid id；el 局部键当场绑定，同轮可用

    def apply_entity(self, entity: EntityInput, *, el: str, present: set[str] | None = None) -> str:
        """用于登记或更新一个实体、绑定 el 局部键并即时返回 run 级 id（同键同内容重放幂等）

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
                expected="换一个 el 键（el 在 章内一对一绑定实体）",
            )
        key = _norm_entity_key(entity.name)
        existing = self.written_entities.get(key)
        if existing is not None and present is not None:
            # 部分更新：先合并成生效记录，再落图（闸门看到的永远是完整记录）
            entity = self._merge_partial_entity(existing, entity, present)
            record = f"entity/{entity.name}"
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
            self.graph.record_entity_ops([entity], chapter_id=self.current_chapter_id)
            self.written_entities[key] = entity
            self._rebuild_entity_payload()
        self.entity_el_index[normalized_el] = key
        entity_id = self.graph.entity_id(entity.name)
        if entity_id is None:
            raise AnnotationInvariantError(f"实体 id 登记失败: {entity.name}")
        return entity_id

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
        """用于按写入顺序重建当前章 的实体目录载荷"""
        self.domain_payloads["entities"] = EntityDirectoryInput(
            entities=list(self.written_entities.values())
        )

    # ------------------------------------------------------------------
    # 指标域：整域一次提交，重复提交按最后一次为准；段落级监督标签随本域提交

    def apply_metrics(self, payload: ChapterMetricsInput) -> None:
        """用于写入当前章 摘要、叙事指标与段落情绪标签（重复提交整域覆盖）

        labels 的 paragraph_id 是段首可见号（正文每段开头的 `N：`），必须属于本章；
        越界段号整次提交拒绝并指明是哪一条标签。落库前按段落坐标映射
        换回全局 paragraph_id（绑定载荷与持久化口径不变）。
        """
        self._require_writable("metrics")
        if payload.labels:
            visible_to_global = (
                dict(self._visible_global_pairs())
                if self.paragraph_info is not None
                else {}
            )
            for label in payload.labels:
                if label.paragraph_id not in visible_to_global:
                    preview = ", ".join(str(pid) for pid in sorted(visible_to_global)[:12]) or "（无）"
                    raise AnnotationStageRejection(
                        f"paragraph_id 不属于本章: {label.paragraph_id}",
                        record="metrics",
                        field="paragraph_id",
                        code="out_of_range",
                        expected=f"本章 可标注的段号（正文段首 `N：`）: {preview}"
                        f"{'…' if len(visible_to_global) > 12 else ''}",
                    )
            self.bound_payloads["paragraph_labels"] = [
                BoundParagraphLabel(
                    paragraph_id=visible_to_global[label.paragraph_id],
                    emotion=label.emotion,
                )
                for label in payload.labels
            ]
        else:
            self.bound_payloads["paragraph_labels"] = []
        self.metrics_payload = payload
        self.domain_payloads["metrics"] = payload

    def _visible_global_pairs(self) -> list[tuple[int, int]]:
        """用于把段首可见号与全局 paragraph_id 配成对（落库映射的单一来源）"""
        assert self.paragraph_info is not None
        return list(zip(self.paragraph_info.visible_ids(), self.paragraph_info.paragraph_ids, strict=True))

    # ------------------------------------------------------------------
    # 对话域：按候选序号即时落账三态判定

    def apply_dialogue(
        self,
        *,
        candidate_index: int,
        verdict: DialogueVerdict,
        speaker_ref: str | None,
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
                    expected="character 类型的实体（run 级 id 或 el 键）",
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
        from_ref: str,
        to_ref: str,
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

    def apply_relation_change(
        self,
        *,
        from_ref: str,
        to_ref: str,
        relation_type: RelationType,
        change_kind: str,
        evidence: int | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        """用于对一条既有关系边提交一次变化（强化/削弱/解除/修正/取代/撤回）

        2026-09-18 从案例裁决下沉到写入路径：变化不再经案例池，端点按 search_graph 回显的
        规范名提交、端点类型按 RELATION_DEFINITIONS 校验，变化记进图变更日志（落库从该日志
        派生）。解除/修正/取代/撤回要求该边当前活动，对不存在的边报错——静默接受而终态不变
        正是历史 run 里"撤销→复查→没变"空转的直接原因。
        """
        provisional = f"relation/{from_ref}-{to_ref}/{relation_type}"
        self._require_writable(provisional)
        if self.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        internal = RELATION_CHANGE_KIND_LABELS.get(str(change_kind))
        if internal is None:
            raise AnnotationStageRejection(
                f"change_kind 不是闭合取值: {change_kind}",
                record=provisional,
                field="change_kind",
                code="invalid_value",
                expected="新增/强化/削弱/解除/修正/取代/撤回",
            )
        from_name = self.resolve_entity_ref(from_ref, record=provisional, field="from_entity")
        to_name = self.resolve_entity_ref(to_ref, record=provisional, field="to_entity")
        record = f"relation/{from_name}-{to_name}/{relation_type}"
        # evidence 是模型面的段首可见号：落库前按当前章映射回全局 paragraph_id
        # （映射表就是标签域用的同一份 _visible_global_pairs，不另立口径）
        if evidence is not None and self.paragraph_info is not None:
            evidence = dict(self._visible_global_pairs()).get(int(evidence), evidence)
        definition = RELATION_DEFINITIONS[str(relation_type)]
        for field_name, name, expected_types in (
            ("from_entity", from_name, definition["from_types"]),
            ("to_entity", to_name, definition["to_types"]),
        ):
            try:
                self._require_entity(
                    name,
                    entity_types=self._fact_entity_catalog(),
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
            self.graph.apply_relation_change(
                from_entity=from_name,
                to_entity=to_name,
                relation_type=str(relation_type),
                change_kind=internal,
                reason=f"本章正文确认的关系变化：{change_kind}",
                evidence=evidence,
                case_id="",
                case_type="",
                target_key="",
                # 无案例的变更没有案例锚点：落库要一个稳定目标（关系事实行的 fact_id 由
                # 章 + 本条变更在本章变更日志里的序号派生，见 _persist_fact_resolution），
                # 序号即调用点当时的日志长度（本条append前）
                target_ref={
                    "chapter_id": self.current_chapter_id,
                    "change_index": len(self.graph.relation_change_ops),
                },
                chapter_id=self.current_chapter_id,
            )
        except ValueError as exc:
            raise AnnotationStageRejection(
                str(exc),
                record=record,
                field="change_kind",
                code="change_target_missing",
                expected=(
                    "该边当前活动；先 search_graph 确认这条边还在（端点写回显的规范名），"
                    "已解除的边不要重复解除"
                ),
            ) from None
        return record, internal, {
            "change_kind": str(change_kind),
            "from_entity": from_name,
            "to_entity": to_name,
            "relation_type": str(relation_type),
        }

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
        self.graph.record_relation_asserts(resolved_items, chapter_id=self.current_chapter_id)
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
                    expected="先用 write_entity 登记（或 search_graph 查已登记 id）",
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
        """用于挡住同一人物的重复动态状态（人物,动作 在本章 内唯一）

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
                expected="同一人物在本章 内的动作不得重复（改写动作或更新已记的那条）",
            )

    # ------------------------------------------------------------------
    # 2026-09-14 回执返回写入内容（所有 write 回执回显写入内容）；2026-09-19 id 纪律：
    # content=本次写入的生效终值（服务端归一/端点解析已完成），带 run 级 uuid id

    def entity_content(self, entity: EntityInput) -> dict[str, Any]:
        """用于回显 write_entity 登记/更新后该实体生效记录（含 run 级 id）"""
        stored = self.written_entities.get(_norm_entity_key(entity.name), entity)
        content = stored.model_dump(mode="json")
        content["id"] = self.graph.entity_id(stored.name) if self.graph is not None else None
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
        """用于回显 write_event 后该节点的服务端终值（节点 id/描述/伏笔属性/参与者三态）

        el 与 isroot 是模型侧提交别名、树上不存储，因此不进 content；id 纪律下
        content 带 run 级 uuid 节点 id（=落库 event_id），树级 uuid 不外露。
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
            "id": str(event.node_id),
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
    # 2026-09-14 进度账本数据源（每回合注入最新进展，不走回执 rollup）：
    # 服务端不把思考重放给模型，"已写到哪、还欠哪些"由系统逐回合直给——四个
    # *_ledger() 供 graph 侧渲染写者面【进度账本】注入块（局部键面，不露 uuid）。

    def entity_ledger(self) -> list[dict[str, Any]]:
        """用于列举本章已写入实体的账本（el 绑定序）：{el, name, id, entity_type}，带 tags 与同一人物别名

        别名列（alias）与标签列直接对抗"外号没接上登记名→重复注册实体"（run b7477080
        ch3 把猴子当新人物又建一套登记）。
        2026-09-20 entity_type：大类一经登记不可变更，账本行带上它，省得模型凭记忆重写
        时写错大类（run 54a72932：10 次"实体大类已登记为 X"的拒绝）。
        """
        rows: list[dict[str, Any]] = []
        for el, key in self.entity_el_index.items():
            stored = self.written_entities.get(key)
            if stored is None:
                continue
            row: dict[str, Any] = {
                "el": el,
                "name": stored.name,
                "id": self.graph.entity_id(stored.name) if self.graph is not None else None,
                "entity_type": str(stored.entity_type),
            }
            if stored.tags:
                row["tags"] = list(stored.tags)
            if self.graph is not None:
                aliases = self.graph.alias_group(stored.name)
                if aliases:
                    row["aliases"] = aliases
            rows.append(row)
        return rows

    def relation_ledger(self) -> list[str]:
        """用于列举本章当前生效关系边的账本："起-止/类型"（登记名）"""
        return [f"{item.from_entity}-{item.to_entity}/{item.relation_type}" for item in self.written_relations.values()]

    def event_ledger(self) -> dict[str, dict[str, Any]]:
        """用于本章事件树的快照账本：树键 → 根描述/伏笔标记（含置信现值）/子键与类型/主链尾

        键是模型侧的局部键（树键与子事件键），不露 uuid；trunk_tail=root 表示主链还没有子节点。
        """
        view: dict[str, dict[str, Any]] = {}
        for tree_key, tree_id in self.tree_key_index.items():
            tree = self.event_trees.get(tree_id) or {}
            nodes: dict[str, str] = dict(tree.get("nodes") or {})
            root_id = str(tree.get("root_node_id", ""))
            root_event = self._bound_event(root_id)
            children: dict[str, str] = {}
            for node_key, node_id in nodes.items():
                if node_key == _ROOT_NODE_KEY:
                    continue
                children[node_key] = str(self._bound_event(str(node_id)).cause_role)
            entry: dict[str, Any] = {
                "root": root_event.description,
                "foreshadowing": bool(tree.get("isforeshadowing")),
                "children": children,
                "trunk_tail": next(
                    (k for k, v in nodes.items() if str(v) == str(tree.get("trunk_tail"))), _ROOT_NODE_KEY
                ),
            }
            if entry["foreshadowing"] and root_event.payoff_likelihood is not None:
                entry["confidence"] = str(root_event.payoff_likelihood)
            view[tree_key] = entry
        return view

    def dialogue_ledger(self) -> dict[str, Any]:
        """用于对话域账本：候选总数/已判定写入数/未写入编号 + 已判条目的判定值

        judged 带值是对抗整册重推的关键：只报"已判 N/M"时模型把未判清单读成
        "一切从零重推"，写完的条目也要回文核对（run b7477080 ch1 全册过 6 遍）。
        """
        judged: dict[str, str] = {}
        for index, item in sorted(self.written_dialogues.items()):
            if str(item.verdict) != "dialogue":
                judged[str(index)] = str(item.verdict)
            else:
                judged[str(index)] = f"{item.speaker or 'null'}/{item.tone or 'null'}"
        pending = sorted(set(range(1, len(self.dialogue_candidates) + 1)) - set(self.written_dialogues))
        return {
            "total": len(self.dialogue_candidates),
            "written": len(self.written_dialogues),
            "pending": pending,
            "judged": judged,
        }

    # ------------------------------------------------------------------
    # 收尾声明：唯一 finish，系统据此校验并冻结当前章（冻结单位=整章）

    def finish_chapter(self) -> dict[str, Any]:
        """用于声明本章的语义写入已写完：补默认判定、校验并构造 ready_chapter

        写入是实时的，收尾只管一件件"把这一章组装出来"该管的事：指标缺提交则
        拒绝（没载荷装不出完整章标注）。逐条记录写入是否成功不在收尾判定里——失败的调用
        在调用点就被单独拒绝并已回执，那条记录本来就没进图/进载荷，收尾按已写入内容
        完成即可；把收尾绑到无关记录的成功上，只会让"末轮出现一次失败"连带作废整章
        （run 1b388eb3 第 2 章实锤：末轮两条关系边被拒 + 收尾被拒 = 135 次调用全废）。
        构造失败整体回滚，已写入记录原样保留。
        """
        if self.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish")
        if self.metrics_payload is None:
            raise AnnotationStageRejection(
                "本章指标尚未提交，不予收尾",
                record="finish",
                field="metrics",
                code="missing_record",
                expected="先 write_metrics 提交摘要与叙事指标",
            )
        snapshot = self.snapshot()
        try:
            self._default_undecided_dialogues()
            self._ensure_domain_payloads()
            self.ready_chapter = self._build_ready_chapter()
        except Exception as exc:
            self.restore(snapshot)
            if isinstance(exc, AnnotationStageRejection):
                raise
            raise AnnotationStageRejection(
                f"章节收尾校验失败: {exc}",
                record="finish",
                code="assembly_failed",
                expected="按报错核对已写入的记录后重新 finish",
            ) from None
        self.write_records.extend(self._chapter_write_records())
        self.chapter_finished = True
        return {
            "status": "completed",
            "chapter_id": self.current_chapter_id,
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

    def _chapter_write_records(self) -> list[dict[str, Any]]:
        """用于收尾时把本章 的写入汇总成领域级审计记录（形状与此前一致）"""
        records: list[dict[str, Any]] = [
            {
                "chapter_id": self.current_chapter_id,
                "domain": "entities",
                "payload": EntityDirectoryInput(
                    entities=list(self.written_entities.values())
                ).model_dump(mode="json"),
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
                "payload": [
                    item.model_dump(mode="json") for item in self.written_relations.values()
                ],
            }
        )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
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
        """2026-08-08 用于建立当前章 唯一实体名称和类型目录"""
        types: dict[str, EntityType] = {}
        names: dict[str, str] = {}
        for entity in directory.entities:
            normalized = unicodedata.normalize("NFC", entity.name).strip()
            key = normalized.casefold()
            if key in types:
                raise ValueError(f"本章 实体名称重复: {normalized}")
            types[key] = entity.entity_type
            names[key] = normalized
        return types, names

    def _fact_entity_catalog(self) -> dict[str, EntityType]:
        """2026-08-10 用于合并内存图已登记实体与当前章 已声明实体作为事实端点目录"""
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
        """2026-08-11 用于校验事实端点已由当前章 实体目录或已登记实体声明（别名解析后）"""
        key = unicodedata.normalize("NFC", name).strip().casefold()
        resolved_key = key
        if self.graph is not None:
            resolved_key = _norm_graph_name(self.graph.resolve_name(name))
        actual_type = entity_types.get(resolved_key) or entity_types.get(key)
        if actual_type is None:
            raise ValueError(
                f"{label} 未在当前章 登记: {name}（"
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
        """2026-08-07 用于拒绝当前章 各领域的重复语义事实"""
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
    # ready_chapter 构造与冻结
    # ------------------------------------------------------------------

    def _build_ready_chapter(self) -> BoundChapterAnnotation:
        """2026-08-20 用于从全部已接受领域校验并构造完整 BoundChapterAnnotation（优化：内联验证逻辑）"""
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
                    f"[{index}] {label} 未在当前章 登记: {name}"
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
        # 2026-09-04 单一写面：entities/relations 不进 ready_chapter，
        # 图域真相源是 FactGraph 操作日志，持久化从其派生
        return BoundChapterAnnotation(
            metrics=payloads["metrics"],
            character_observations=list(self.bound_payloads["character_observations"]),
            dialogues=bound_dialogues,
            events=list(self.bound_payloads["events"]),
            paragraph_labels=list(self.bound_payloads.get("paragraph_labels") or []),
        )

    def _dialogue_coverage_warnings(self) -> list[str]:
        """2026-09-05 用于在冻结前确定性登记对话候选覆盖缺口（仅告警不阻断冻结）

        未提交判定的候选在收尾时统一按 not_dialogue 默认处理，这里把默认处理的
        缺口随章留痕，供报告附录 B 展示。
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
        随章留痕，供 linguistic 阶段边界拟合的样本量判断与报告附录展示。
        """
        labels = self.bound_payloads.get("paragraph_labels") or []
        if len(labels) >= _PARAGRAPH_LABEL_MIN_PER_CHAPTER:
            return []
        return [f"情绪标签覆盖: 仅标注 {len(labels)} 段（每章应自选 2-3 段）"]

    def complete_active_chapter(self) -> BoundChapterAnnotation:
        """用于在收尾声明后冻结当前章（覆盖率告警随章留痕）"""
        if self.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 complete_chapter")
        if not self.chapter_finished:
            raise ValueError("本章 尚未收尾：先调用 finish")
        if self.ready_chapter is None:
            raise AnnotationInvariantError("已收尾但 ready_chapter 缺失，系统不变量被破坏")
        warnings = [*self._dialogue_coverage_warnings(), *self._paragraph_label_coverage_warnings()]
        chapter = (
            self.ready_chapter.model_copy(update={"coverage_warnings": warnings}) if warnings else self.ready_chapter
        )
        self.completed_chapters.append(chapter)
        # 2026-08-14 M6：当前章隐式授权（_resolve_case_details 按 current_chapter_id
        # 相等校验），不再登记文本授权集合
        # 2026-08-14 D1：不再有 continuity_open 阶段，冻结章 后直接进入终态
        self.phase = "completed"
        return chapter

    def finish(self) -> BoundChapterAnnotation:
        """2026-08-11 用于在章冻结后由系统产出章节正式标注

        2026-09-19 章即块拍平：章节标注就是冻结的那一份（原"各 chunk summary
        拼章节摘要"随两级结构退役，摘要在 metrics.summary）。
        """
        if self.phase != "completed":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish")
        if not self.completed_chapters:
            raise AnnotationInvariantError("已冻结但 completed_chapters 为空，系统不变量被破坏")
        annotation = self.completed_chapters[-1]
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
                            "id": (
                                self.graph.entity_id(participant.entity)
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
            "chapter_id": self.current_chapter_id,
            "chapter_finished": self.chapter_finished,
            # 2026-09-13 实时写入进度（仅供审计：模型看到的只有各小调用的回执）
            "written": self._written_counts(),
            "missing_content": self.missing_content_domains(),
            "entities": {
                "declared": [
                    {
                        "id": (
                            self.graph.entity_id(entity.name)
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
                        {"id": self.graph.entity_id(display_name), "name": display_name,
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


def normalize_message_name(name: str) -> str:
    """2026-09-11 用于生成与实体目录一致的名称匹配键（NFC + strip + casefold）"""
    return unicodedata.normalize("NFC", name).strip().casefold()


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

# 引用被拒时回执里列几个本章已登记实体（"el=名字"对照）；超出部分只报总数，
# 拒绝回执要能一眼读完（全章几十个实体时不铺开）
_ENTITY_REF_HINT_LIMIT = 12
_EVENT_NARRATIVE_ROLE_VALUES_TEXT = "主体/客体/发送者/接收者/帮助者/反对者/见证者"
_STAGE_FIELD_EXPECTATIONS: dict[str, str] = {
    "verdict": "dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选",
    "tone": tone_catalog_text(),
    "relation_type": "闭合关系类型（见 write_relation 参数说明）",
    # 2026-09-20 回执只报字段取值域，"这个字段是什么、怎么判"归提示词面——写在载荷模型的
    # 字段说明里（schema.ParticipantArg.role/narrative_role），本表不再替它复述。
    "role": _EVENT_ROLE_VALUES_TEXT,
    "narrative_role": _EVENT_NARRATIVE_ROLE_VALUES_TEXT,
    "entity_type": "character / location / item / organization",
    "narrative_function": "冲突 / 铺垫 / 转折",
    "confidence": "high / medium / low（伏笔回收可能性三档）",
    "payoff_likelihood": "high / medium / low",
    "type": '"main"（顺延主因链）或 "secondary"（挂在当时主链尾）',
    "emotion": "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    "emotional_valence": "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    "entityid": "实体引用：本章 自定的 el 键，或 write_entity / search_graph 回执里的 run 级 id",
    "speaker": "说话人实体引用：el 键或 run 级 id",
    "candidate_index": "1 基候选序号（见 DialogueCandidates 表）",
    "el": "实体/事件节点的章内局部键（实体如 a1；事件根如 t1、子事件如 t1/e2），由你指定",
    "isroot": "true=建事件树根（el=树键），false=子事件（el=树键/节点键）",
    "characters": "参与者数组，每项 {entityid, role[, narrative_role, action, emotion]}（character 三态必填）",
    "labels": "段落情绪标签数组，每项 {paragraph_id, emotion}（paragraph_id 取段首可见号，即正文每段开头的 `N：`）",
    "paragraph_id": "段首可见号（正文每段开头的 `N：`）",
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
            ledger.known_case_ids.add(case.id)
            ledger.authorized_chapter_ids.add(case.chapter_id)
            linked = []
            for other in others:
                entity_id = ledger.graph.entity_id(other) if ledger.graph is not None else None
                linked.append({"id": entity_id, "name": other} if entity_id is not None else {"name": other})
            links.append({"case_id": case.id, "linked": linked})
        if links:
            view["alias_linked"] = links
            annotated = True
    if annotated:
        response["alias_note"] = (
            "带 alias_linked 的节点存在未决的实体别名案例（案例 id 见 case_id）："
            "确认是同一人物就用 write_relation 提交「同一人物」边，两端随即按一个节点归并；"
            "确认不是就用 close_case 关掉该 id。系统不会自行合并，未关闭的案例会一直留在案例池。"
        )


def _live_graph_response(
    graph: FactGraph,
    entities: list[str],
    *,
    relation_type: str | None,
    limit: int,
) -> dict[str, Any]:
    """2026-08-11 用于从常驻内存图回答节点邻域查询（运行时唯一图真相源）

    2026-09-19 每个实体视图携带 run 级 uuid id（entity_view 出 id）；events/relations/
    dialogues 的实体引用用该 id 或本章 的 el 键。
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
        """按实体名查询图节点及其一跳邻域（相连的边与邻居节点）

        matches 是命中的实体，neighbors 是它们的邻居，relations 是两端都在结果里的边；
        matches/neighbors 都带 run 级 id，事件参与者、对话说话人与关系端点的实体引用
        一律填该 id（或本章 自定的 el 键）。
        """
        if ledger.phase != "chapter_open":
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
        """按关键词检索正文，每个命中是一段正文

        查询支持多关键词（空格/标点分隔，任一命中即返回）与通配符
        （% 匹配任意长度、_ 匹配单个字符），如「伯安 偷%」或「赤羽_尾鸡」；
        回执只给正文文本与是否截断，不带段落的内部标识。
        """
        normalized_query = _normalize_query(query, tool_name="search_text")
        if ledger.phase != "chapter_open":
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
        """按关键词检索已完成章节的事件树，树根直接按回执里的 id 引用

        检索范围为树内任意节点的描述与参与者；查询支持多关键词
        （空格/标点分隔，任一命中即返回）与通配符
        （% 匹配任意长度、_ 匹配单个字符），如「伯安 偷%」。

        每棵命中树给出根事件的 id、描述与伏笔状态（is_foreshadow_setup /
        foreshadowing_status / payoff_likelihood，可据此发现活跃伏笔树）；
        参与者实体带 run 级 id；write_event 伏笔挂树的 root_event_id 填这里的 id。
        """
        normalized_query = _normalize_query(keyword, tool_name="search_event")
        if ledger.phase != "chapter_open":
            raise AnnotationAuthorizationError(f"阶段 {ledger.phase} 不允许 search_event")
        results = query_service.search_event_history(
            normalized_query,
            limit=20,
        )
        views: list[dict[str, Any]] = []
        for item in results:
            # 2026-09-19 id 纪律：只授权根节点 id（挂树引用面）；tree_id 是树级内部 id，
            # 历史上误当事件 id 放行过（P0），本行不再授权 tree_id
            ledger.authorized_event_ids.add(item.root_node_id)
            ledger.authorized_tree_ids.add(item.tree_id)
            ledger.history_tree_views[item.tree_id] = item.model_dump(mode="json")
            views.append(
                {
                    "id": item.root_node_id,
                    "chapter_order": item.chapter_order,
                    "description": item.description,
                    "participants": _event_view_participants(item.participants, graph=ledger.graph),
                    "is_foreshadow_setup": item.is_foreshadow_setup,
                    "foreshadowing_status": item.foreshadowing_status,
                    "payoff_likelihood": item.payoff_likelihood,
                }
            )
        ledger.append_search_log(
            {
                "tool": "search_event",
                "query": normalized_query,
                "hits": [item["description"] for item in views],
                "digest": "",
            }
        )
        return json.dumps({"trees": views}, ensure_ascii=False)

    @tool
    def search_pool(query: str | None = None, case_type: str | None = None) -> str:
        """检索案例池，返回案例及其 id

        案例不会自动出现在正文里，本面是发现已登记案例的唯一通道：
        - 只给 query：按关键词匹配案例 keys/description；查询支持多关键词
          （空格/标点分隔，任一命中即返回）与通配符（% 匹配任意长度、_ 匹配单个字符）。
        - 给 case_type（如 "entity_alias"/"伏笔疑点"，或 "all"）：按最新创建优先
          枚举该类型全部活动案例，不需要关键词；无命中提示时也可用它对案例重做全量枚举。
        回执 pool 给出池内未解决案例的总数与类型分布（已解决的不计）。
        刚用 push_case 登记的案例马上就能检索到（回执带 pending=true 标记）。"""
        if ledger.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_pool")
        normalized_query = (
            _normalize_query(query, tool_name="search_pool") if query is not None else None
        )
        normalized_type = (
            unicodedata.normalize("NFC", case_type).strip() if case_type is not None else None
        )
        if not normalized_query and not normalized_type:
            raise AnnotationInputError("search_pool.query 与 search_pool.case_type 至少提供一个")
        # 2026-09-13 登记即进池：本章 push_case 登记的案例也进检索面
        pending_ids = {case.target_key for case in ledger.pushed_cases}
        pending_views = [
            CaseSearchResult(
                id=case.target_key,
                type=case.type,
                chapter_id=ledger.current_chapter_id,
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
        case_ids: list[str] = []
        for item in result.results:
            if isinstance(item, CaseSearchResult):
                # 案例展示即授权其 id 与源章（§12.3 章级定位），解决时不再因原文未读取被拒
                ledger.known_case_ids.add(item.id)
                ledger.authorized_chapter_ids.add(item.chapter_id)
                case_ids.append(item.id)
                view = {
                    "result_kind": "case",
                    "id": item.id,
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
                "hits": case_ids,
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
) -> list[Any]:
    """2026-08-07 用于构建语义写入搜索解决和完成工具集"""

    @tool
    def write_metrics(
        summary: str,
        emotional_valence: int,
        narrative_function: NarrativeFunction,
        pivot_moment: Annotated[bool, Field(description=PIVOT_MOMENT_DESCRIPTION)] = False,
        cliffhanger: Annotated[bool, Field(description=CLIFFHANGER_DESCRIPTION)] = False,
        labels: list[ParagraphLabelInput] | None = None,
    ) -> str:
        """写入当前章节摘要、叙事指标与段落情绪标签（整域一次提交，写入即生效）

        emotional_valence 为情绪分值整数 -2..2（-2 强烈负面 / -1 轻微负面 / 0 中性 /
        1 轻微正面 / 2 强烈正面）；summary 为本章摘要。
        labels 为段落情绪标签（每章自选 2-3 段）：paragraph_id 取段首可见号（正文每段
        开头的 `N：`），emotion 同 emotional_valence；优先选情绪表达有代表性、或语气/
        标点有区分度的段落，也允许 0 分段。
        同一章 重复提交整域按最后一次为准（labels 同理，按段号去重后覆盖）。
        回执 content 回显当前整域生效指标。
        """
        payload = ChapterMetricsInput(
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
        事件/关系/对话的实体引用用 el 键（同轮先登记后引用，不等回执）或
        回执/检索 id——write_event 的 characters[].entityid 等字段两者都收。
        回执 content 回显该实体合并后的生效记录（含 run 级 id）。
        """
        # 2026-09-14 删除"提交 write_entity 前必须先 search_graph"硬闸——
        # 首写被检索挡在门外会迫使判定跨回合等待回执；登记序由 el 键承接，闸门删净
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
        entity_id = ledger.apply_entity(entity, el=el, present=present)
        bound_el = unicodedata.normalize("NFC", el).strip()
        return json.dumps(
            {
                "status": "written",
                "record": f"entity/{entity.name}",
                "el": bound_el,
                "id": entity_id,
                "content": ledger.entity_content(entity),
            },
            ensure_ascii=False,
        )

    @tool
    def write_dialogue(
        candidate_index: int | None = None,
        verdict: DialogueVerdict | None = None,
        speaker: EntityRef | None = None,
        tone: Tone | None = None,
        candidate_key: Annotated[
            str | None,
            Field(
                description=(
                    "要订正的既有对话记录的键（候选表里那条候选的 candidate_key）；"
                    "给了它就按更新语义改这条记录，不必再给 candidate_index/verdict"
                )
            ),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="更新后的对话内容描述；不更新就省略"),
        ] = None,
        is_inner_monologue: Annotated[
            bool | None,
            Field(description="这条对话是否内心独白；不更新就省略"),
        ] = None,
    ) -> str:
        """按候选编号写入一条对话候选的三态判断，或更新一条既有对话记录（写入即生效）

        verdict: dialogue=真实对话 / inner_monologue=内心独白 /
        not_dialogue=误判候选（题字、描写被引号包裹等，此时只填 candidate_index 与 verdict）。
        speaker 是说话人的实体引用——本章 自定的 el 键或回执/检索 id，
        无法确认时留空；tone 取参数说明里的闭合枚举，没有贴合的用「其他」。
        归属判据：多人齐声或同一条引语混有多人发言时，二选一——定主喊者，或 speaker 留
        空承认归属不明；一次定案，后续回合不因再权衡"谁更合适"而改判。
        判定与写入不必一轮做完：每条判定彼此独立、写入即生效，重写同序号按更新语义处理。
        给 candidate_key 时按更新语义改既有记录（speaker/tone/description/is_inner_monologue
        至少给一个），用于订正既有对话判定。
        回执 content 回显该候选的生效判定（speaker 已解析为登记名，含候选账本标识 candidate_key）。
        """
        if candidate_key is not None:
            return _update_dialogue_record(
                ledger,
                candidate_key=candidate_key,
                speaker_ref=speaker,
                tone=tone,
                description=description,
                is_inner_monologue=is_inner_monologue,
            )
        if candidate_index is None or verdict is None:
            raise AnnotationStageRejection(
                "缺少 candidate_index 与 verdict",
                record="dialogue",
                field="candidate_index",
                code="invalid_call",
                expected=(
                    "判本章候选：给 candidate_index 与 verdict；"
                    "更新既有记录：给 candidate_key（可带 speaker/tone/description/is_inner_monologue）"
                ),
            )
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
        change_kind: Annotated[
            RelationChangeKindArg | None,
            Field(
                description=(
                    "本章对这条关系做了什么变化（省略=新增）："
                    "新增=确认这条关系存在；强化=关系更紧密；削弱=关系变疏远或分量下降；"
                    "解除=关系终止；修正=关系的性质或描述被更正；取代=被另一条关系替换；"
                    "撤回=此前登记有误、撤销该条。"
                    "解除/修正/取代/撤回要求该边当前活动（用 search_graph 确认端点写法）"
                )
            ),
        ] = None,
        evidence: Annotated[
            EvidenceNumber,
            Field(
                description=(
                    "只用于变更类 change_kind：该变化在正文里的段首可见号（整数，如 12）；"
                    "新增（建边）不用填，建边不消费它"
                )
            ),
        ] = None,
    ) -> str:
        """写入一条本章确认存在的闭合关系边，或对既有边提交一次变化（一次一条，写入即入图）

        两端写实体引用：run 级 id（write_entity / search_graph 回执里的 id）或本章自定的
        el 键，不是实体名称——名称一律按未登记引用拒绝。
        关系类型是闭合词表：方向与两端实体类型约束见 relation_type 参数说明，端点类型
        不符会被拒（如 主从 只接受 character 起点、利益 两端都要 character/organization）；
        物品/地点做参与者时用 位于 等允许该类端点的关系，或改由人物之间的关系表达。
        省略 change_kind（或填"新增"）= 建边 assert，重复提交同一条边自动去重，同一对
        端点重写（含换关系类型）按整体替换处理、写入顺序不影响终态。
        填其它 change_kind = 改一条既有边（端点写实体引用，回执 content 回显两端登记名），
        变化进图变更日志，该变化在正文里的位置用 evidence 给段首号；
        解除/修正/取代/撤回对不存在的边报错（不静默接受）。
        回执 content 回显该边当前生效内容（两端为登记名）。
        """
        if change_kind is None or str(change_kind) == RelationChangeKindArg.CREATE.value:
            # 建边路径不消费 evidence（关系事实行上没有这个字段）：给了也不作废整笔写入，
            # 参数说明里已写明"不用填"（run 54a72932 里这一族失败全出在类型上，不是语义）
            record, outcome, content = ledger.apply_relation(
                from_ref=from_entity,
                to_ref=to_entity,
                relation_type=relation_type,
            )
            return json.dumps(
                {"status": "written", "record": record, "outcome": outcome, "content": content},
                ensure_ascii=False,
            )
        record, outcome, content = ledger.apply_relation_change(
            from_ref=from_entity,
            to_ref=to_entity,
            relation_type=relation_type,
            change_kind=str(change_kind),
            evidence=evidence,
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
        foreshadowing_action: Annotated[
            str | None,
            Field(
                description=(
                    "把本节点挂进一棵已存在的伏笔树时填：reinforce=续接（该伏笔在本章继续发展）/ "
                    "payoff=回收（该伏笔在本章被交代，伏笔树随之收束为 likely_paid_off）；"
                    '取值只能是 "reinforce" 或 "payoff"，与 root_event_id 同时给'
                )
            ),
        ] = None,
        root_event_id: Annotated[
            str | None,
            Field(
                description=(
                    "伏笔树的根（埋设事件）的 run 级 id：用 search_event 树根视图里的 id；"
                    "本章刚写出的树也可填它的树键（el）。与 foreshadowing_action 同时给"
                )
            ),
        ] = None,
        payoff_likelihood: Annotated[
            Confidence | None,
            Field(
                description=(
                    "挂进既有伏笔树时更新树根的回收可能性（本章证据改变了预期才给）："
                    "high/medium/low；不给则根上的现值不动"
                )
            ),
        ] = None,
        strength: Annotated[
            Confidence | None,
            Field(description="挂进既有伏笔树时更新树根的强度（high/medium/low）；不给则不动"),
        ] = None,
    ) -> str:
        """写入一个事件节点：isroot=true 建事件树根（el=树键如 t1），false 加子事件（el=t1/e2）

        description 是一句话描述（根事件不超过 30 字）。整棵树可以在一轮里按顺序写完：
        先根后子逐个调用，el 由你指定、写入即生效，同轮后面的调用直接可用（不等回执）；
        树内先后=调用顺序，没有序号参数。子事件 type="main" 顺延主因链（成为新的
        链尾）/"secondary" 挂在当时主链尾；伏笔属性（isforeshadowing/confidence）只属于根：
        isforeshadowing=true 时 confidence 必填（high/medium/low），整棵树成为伏笔树、
        根即埋设事件。
        伏笔建模判据：埋设事件本身就是本章主链事件时，直接给主链根标 isforeshadowing=true，
        不再另立第二棵树重复同一时刻；仅当要埋的悬念不对应主链某个事件时才独立立伏笔树。
        同一悬念的建树选择一次定案，后续回合不再依同一证据复议。
        续接/回收已存在的伏笔树用 foreshadowing_action + root_event_id：本节点仍然按 el
        正常写入本章事件树，同时挂一条伏笔边进那棵树（root_event_id 用 search_event 树根
        视图的 id，它必须是一棵伏笔树的根；不能挂到根自己身上）；payoff_likelihood
        与 strength 只在挂边时有用，用来把树根上的回收可能性/强度更新成本章判断出的现值。
        characters 是该节点的参与者数组（可省）：根节点也直接挂参与者。character 实体
        每条必须带 narrative_role/action/emotion 三态（action 不超过 15 字、emotion
        为 -2..2 整数；同一人物在本章 内的动作不得重复），非 character（item/
        organization/location）条目只填 entityid/role，"地点"角色只用于 location。
        entityid 填本章 的 el 键或回执/检索 id（id 引用历史实体）。
        同 el 重写按更新处理：根改描述/伏笔属性，子改描述（type 不可改写，要改换键）；
        characters 给出即整体替换该节点参与者列表，省略则保留。
        回执 content 回显该节点落账记录（节点 id/描述/参与者三态，根带伏笔属性现值、子带 type）。
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
        attach = _attach_foreshadowing(
            ledger,
            el=el,
            record=record,
            foreshadowing_action=foreshadowing_action,
            root_event_id=root_event_id,
            payoff_likelihood=None if payoff_likelihood is None else str(payoff_likelihood),
            strength=None if strength is None else str(strength),
        )
        content = ledger.event_content(el=el, isroot=isroot)
        if attach is not None:
            content = {**content, "foreshadowing": attach}
        return json.dumps(
            {"status": "written", "record": record, "content": content},
            ensure_ascii=False,
        )

    @tool
    def finish() -> str:
        """声明本章的语义写入已写完：本回合全部调用处理完后系统校验并冻结

        本章的全部内容（含整棵事件树）都可以在同一批调用里按顺序写完，末尾直接跟本工具，
        不必为了"先看回执"再拆一轮：局部键（实体 el、事件树键）由你指定、写入即生效，
        同批后面的调用直接可用。
        本工具可以单独调用，也可以写在 execute_code 的程序末尾——写在程序末尾时在本程序
        全部语句执行完后结算，与单独调用同一条判定。
        写入是实时生效的，本工具只做收尾：唯一会拒绝收尾的是指标（write_metrics）
        尚未提交——那时回执给出 missing_record，先补指标再收尾。
        本回合其他调用有没有失败与收尾无关：失败的那条只回滚它自己（回执已单独说明原因），
        没进图/没进载荷，收尾按已写入内容完成即可，不必为了收尾去重交失败记录。
        没有内容的领域不必造假数据，直接收尾即可（收尾回执给出各域写入条数）。
        收尾判定在本回合全部调用处理完后生效，通过后本章冻结、不再接受写入；
        不调用本工具，本章不会冻结。
        """
        return json.dumps({"status": "pending"}, ensure_ascii=False)

    def _is_foreshadowing_root(ledger: AnnotationToolLedger, root_event_id: str) -> bool:
        """用于判定节点 id 是否为已知伏笔树根（历史树根视图 + 当前章 event_trees）"""
        for view in ledger.history_tree_views.values():
            if view.get("root_node_id") == root_event_id and view.get("is_foreshadow_setup"):
                return True
        for tree in ledger.event_trees.values():
            if tree.get("root_node_id") == root_event_id and tree.get("isforeshadowing"):
                return True
        return False

    def _attach_foreshadowing(
        ledger: AnnotationToolLedger,
        *,
        el: str,
        record: str,
        foreshadowing_action: str | None,
        root_event_id: str | None,
        payoff_likelihood: str | None = None,
        strength: str | None = None,
    ) -> dict[str, Any] | None:
        """用于把刚写入的事件节点挂进一棵已存在的伏笔树（续接/回收）

        2026-09-18 从案例裁决下沉到写入路径：本节点照常写进本章事件树，另记一条无案例的
        foreshadowing 解决项（落库据此建伏笔边，回收时把根状态收束为 likely_paid_off）。
        2026-09-19 payoff_likelihood/strength：挂边时顺带把树根的回收可能性与强度更新成
        本章判断出的现值（落库层早就支持，此前写入路径没接）；只在挂边时接受，单给即拒绝。
        """
        confidence_values = {confidence.value for confidence in Confidence}
        root_updates: dict[str, str] = {}
        for field_name, value in (("payoff_likelihood", payoff_likelihood), ("strength", strength)):
            if value is None:
                continue
            if value not in confidence_values:
                raise AnnotationStageRejection(
                    f"{field_name} 取值非法: {value}",
                    record=record,
                    field=field_name,
                    code="invalid_value",
                    expected=f"high / medium / low（{field_name} 三档）",
                )
            root_updates[field_name] = value
        if foreshadowing_action is None and root_event_id is None:
            if root_updates:
                raise AnnotationStageRejection(
                    "payoff_likelihood/strength 只用于挂进既有伏笔树",
                    record=record,
                    field=next(iter(root_updates)),
                    code="not_on_attach",
                    expected=(
                        "要更新树根属性就同时给 foreshadowing_action 与 root_event_id（挂边）；"
                        "本章新建伏笔树的回收可能性在 isroot=true 那次调用里用 confidence 给"
                    ),
                )
            return None
        if foreshadowing_action not in FORESHADOWING_ACTIONS or not root_event_id:
            raise AnnotationStageRejection(
                "foreshadowing_action 与 root_event_id 必须同时给",
                record=record,
                field="foreshadowing_action",
                code="invalid_call",
            expected=(
                '同时给 foreshadowing_action（"reinforce"=续接 / "payoff"=回收）'
                "与 root_event_id（search_event 树根视图里的 id）"
            ),
            )
        action: Literal["reinforce", "payoff"] = (
            "reinforce" if foreshadowing_action == "reinforce" else "payoff"
        )
        resolved_root = ledger.resolve_event_reference(str(root_event_id))
        if resolved_root is None:
            raise AnnotationStageRejection(
                f"root_event_id 未由事件回执或 search_event 授权: {root_event_id}",
                record=record,
                field="root_event_id",
                code="unknown_reference",
                expected="search_event 树根视图里的 id（本章新建的伏笔树也可用它的章内局部键）",
            )
        resolved_event = ledger.resolve_event_reference(el)
        if resolved_event is None:
            raise AnnotationInvariantError(f"刚写入的事件节点解析不到 id: {el}")
        if resolved_event == resolved_root:
            raise AnnotationStageRejection(
                "不能把事件挂到它自己身上",
                record=record,
                field="root_event_id",
                code="invalid_value",
                expected="挂进另一棵已存在的伏笔树（埋设事件的根自己不带挂边）",
            )
        if not _is_foreshadowing_root(ledger, resolved_root):
            raise AnnotationStageRejection(
                f"root_event_id 不是伏笔树的根（埋设事件）: {root_event_id}",
                record=record,
                field="root_event_id",
                code="not_foreshadowing_root",
                expected=(
                    "活跃伏笔树用 search_event 检索（树根视图 is_foreshadow_setup=true）；"
                    "新建伏笔树用 event(isforeshadowing=True)"
                ),
            )
        ledger.resolved_cases.append(
            ResolvedCase(
                action="foreshadowing",
                type="",
                reason=f"{action}：{el} 挂进伏笔树根",
                target_key="",
                target_ref={"chapter_id": ledger.current_chapter_id},
                foreshadowing_action=action,
                foreshadowing_root_event_id=resolved_root,
                foreshadowing_event_id=resolved_event,
                payoff_likelihood=root_updates.get("payoff_likelihood"),
                strength=root_updates.get("strength"),
            )
        )
        return {"action": action, "root_event_id": resolved_root, "event_id": resolved_event, **root_updates}

    def _chapter_candidate_by_key(
        ledger: AnnotationToolLedger,
        candidate_key: str,
    ) -> int | None:
        """用于把对话记录键翻成本章候选序号（不是本章候选即 None）"""
        for index, candidate in enumerate(ledger.dialogue_candidates, start=1):
            if unicodedata.normalize("NFC", str(candidate.candidate_key)).strip() == candidate_key:
                return index
        return None

    def _update_dialogue_record(
        ledger: AnnotationToolLedger,
        *,
        candidate_key: str,
        speaker_ref: str | None,
        tone: Tone | None,
        description: str | None,
        is_inner_monologue: bool | None,
    ) -> str:
        """用于更新一条既有对话记录（原案例裁决的对话更新下沉到写入路径）

        地址就是候选表里那条候选的键（= `DialogueRecord.candidate_key`，不是记录行的
        uuid 主键）；本工具不改候选账本，只记一条无案例的 dialogue 解决项供落库更新记录行。
        目标必须是一条真会存在的记录行，否则整章落库时才会炸（目标不存在），所以这里先判：
        本章候选按"判过且判成真对话/独白"判（记录行与判定同一事务落库），其余键问一次库
        （既有记录）。
        """
        if ledger.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 write_dialogue")
        normalized_id = unicodedata.normalize("NFC", str(candidate_key)).strip()
        record = f"dialogue/{normalized_id}"
        if not normalized_id:
            raise AnnotationStageRejection(
                "candidate_key 不能为空",
                record="dialogue",
                field="candidate_key",
                code="invalid_value",
                expected="候选表里那条候选的 candidate_key（判过的候选）",
            )
        chapter_candidate = _chapter_candidate_by_key(ledger, normalized_id)
        if chapter_candidate is not None:
            judged = ledger.written_dialogues.get(chapter_candidate)
            if judged is None:
                raise AnnotationStageRejection(
                    f"本章候选尚未判定，没有可更新的记录: {normalized_id}",
                    record=record,
                    field="candidate_key",
                    code="candidate_not_judged",
                    expected=(
                        f"先按 candidate_index={chapter_candidate} 判它（写入即生效），"
                        "再用 candidate_key 订正；本章候选的说话人/语气直接在同一次判定里给"
                    ),
                )
            if judged.verdict == DialogueVerdict.NOT_DIALOGUE:
                raise AnnotationStageRejection(
                    f"该候选判为误判，没有对话记录可更新: {normalized_id}",
                    record=record,
                    field="candidate_key",
                    code="not_dialogue",
                    expected="误判候选（题字、描写被引号包裹等）不建记录；要改判按 candidate_index 重判",
                )
        elif not query_service.has_dialogue_record(normalized_id):
            raise AnnotationStageRejection(
                f"对话记录不存在: {normalized_id}",
                record=record,
                field="candidate_key",
                code="unknown_record",
                expected=(
                    "本 run 里真存在的对话记录键（本章候选表里的 candidate_key；"
                    "本章候选请直接在 dialogue 的判定里给 speaker_id/tone）"
                ),
            )
        if all(value is None for value in (speaker_ref, tone, description, is_inner_monologue)):
            raise AnnotationStageRejection(
                "没有要更新的字段",
                record=record,
                field="candidate_key",
                code="no_update",
                expected="speaker/tone/description/is_inner_monologue 至少给一个",
            )
        speaker_name: str | None = None
        if speaker_ref is not None:
            speaker_name = ledger.resolve_entity_ref(speaker_ref, record=record, field="speaker")
            try:
                ledger._require_entity(
                    speaker_name,
                    entity_types=ledger._fact_entity_catalog(),
                    expected_types=(EntityType.CHARACTER,),
                    label="write_dialogue.speaker",
                )
            except ValueError as exc:
                raise AnnotationStageRejection(
                    str(exc),
                    record=record,
                    field="speaker",
                    code="endpoint_invalid",
                    expected="说话人必须是 character 实体",
                ) from None
        ledger.resolved_cases.append(
            ResolvedCase(
                action="dialogue",
                type="",
                reason=f"写入路径更新既有对话记录：{normalized_id}",
                target_key=normalized_id,
                target_ref={"chapter_id": ledger.current_chapter_id, "candidate_key": normalized_id},
                speaker=speaker_name,
                tone=tone,
                description=description,
                is_inner_monologue=is_inner_monologue,
            )
        )
        return json.dumps(
            {
                "status": "written",
                "record": record,
                "content": {
                    "candidate_key": normalized_id,
                    "speaker": speaker_name,
                    "tone": tone,
                    "description": description,
                    "is_inner_monologue": is_inner_monologue,
                },
            },
            ensure_ascii=False,
        )

    def _require_chapter_record(
        ledger: AnnotationToolLedger,
        value: str,
        *,
        record: str,
        field: str,
    ) -> str:
        """2026-09-18 用于校验记录键确实是本章已经写出来的记录（案例只指向真实产出）

        记录键就是写入回执里的 record（实体 entity/…、事件 t1 或 t1/e2、关系、对话各自的
        形态；两个面的键空间不同，所以这里给的是"回执里的 record"这条判据而不是样例）。
        可用集合由写入口在每次调用成功时登记（ledger.written_record_keys），这里读同一份。
        未命中按结构化拒绝回，并把本章已写出的键列在 expected 里（模型可当场自纠）。
        """
        normalized = unicodedata.normalize("NFC", str(value)).strip()
        expected = "写入回执里的 record（本章写出来的记录键）"
        if not normalized:
            raise AnnotationStageRejection(
                f"{field} 不能为空",
                record=record,
                field=field,
                code="invalid_value",
                expected=expected,
            )
        if normalized not in ledger.written_record_keys:
            known = "、".join(sorted(ledger.written_record_keys)[:8])
            raise AnnotationStageRejection(
                f"{field} 不是本章已经写出来的记录: {normalized}",
                record=record,
                field=field,
                code="unknown_record",
                expected=f"{expected}；本章已写出：{known or '（还没有任何记录）'}",
            )
        return normalized

    def _resolve_case_details(
        *,
        ledger: AnnotationToolLedger,
        case_id: str,
        tool_name: str,
    ) -> ActiveCaseDetails:
        """2026-08-11 用于公共校验案例 id 并回读活动案例稳定目标

        2026-09-19 案例 id 化：无运行期编号，授权面=known_case_ids（search_pool 展示过
        或 push_case 登记过的案例池行 uuid）。
        """
        if ledger.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 {tool_name}")
        if case_id not in ledger.known_case_ids:
            raise AnnotationAuthorizationError(
                f"case_id 未由 search_pool 检索或 push_case 登记返回: {case_id}："
                "案例不在正文中注入，请先 search_pool 检索（可用 case_type=\"all\" 枚举全部未解决案例）"
                "或用 push_case 登记新疑点，再用回执中的 id 解决"
            )
        if case_id in ledger.resolved_case_ids:
            raise AnnotationInputError(f"案例已经解决: {case_id}")
        # 2026-09-13 登记即进池：本章 内 push_case 登记的案例当章即可解决——
        # 池行要到本章收尾才落库，此处用待建案例本体做稳定目标（id 即 target_key，
        # 与落库时的行 id 一致），源章就是当前章，无需再做展示授权校验。
        pending = ledger.pending_case_by_id(case_id)
        if pending is not None:
            return ActiveCaseDetails(
                id=pending.target_key,
                type=pending.type,
                chapter_id=ledger.current_chapter_id,
                created_chapter=ledger.current_chapter_id,
                keys=list(pending.keys),
                description=pending.description,
                target_key=pending.target_key,
                target_ref=dict(pending.target_ref),
            )
        details = query_service.fetch_active_case_details(case_id)
        if details is None:
            raise AnnotationInputError(f"案例不存在或已不再 active: {case_id}")
        # 2026-08-14 M6：案例源是章级定位——章被展示授权或为当前章即可解决
        allowed_chapter_ids = ledger.authorized_chapter_ids | {ledger.current_chapter_id}
        if details.chapter_id not in allowed_chapter_ids:
            raise AnnotationAuthorizationError(
                f"案例 {details.id} 原文所在章 {details.chapter_id} 未经本轮展示授权，"
                "请先 search_text 查询已授权前文后再解决"
            )
        return details

    def _append_resolved(
        ledger: AnnotationToolLedger,
        details: ActiveCaseDetails,
        resolved: ResolvedCase,
    ) -> str:
        """2026-08-11 用于登记解决结果并返回固定回执（案例 id 即池行 uuid）"""
        ledger.resolved_cases.append(resolved)
        return json.dumps(
            {"accepted": True, "case_id": details.id, "action": resolved.action},
            ensure_ascii=False,
        )

    # 2026-09-18 误报出口：案例面收成 push_case + promise_case + close_case。判错、不该
    # 再留在池里的案例用本工具关闭（无语义变化）；有产出记录的用 promise_case 兑现
    @tool
    def close_case(case_id: CaseId, reason: str) -> str:
        """关闭案例：不产生任何语义变化，只把案例标记为已解决"""
        details = _resolve_case_details(
            ledger=ledger,
            case_id=case_id,
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

    # 2026-09-04 单一写面：本工具只更新内存 FactGraph（终态即时生效 + 操作日志登记），
    # 不再向 resolved_cases 追加 fact 动作，持久化层从操作日志派生关系事实。
    # 2026-09-13 通道口径（run c80105cc 实测每章约 1.5K 字符在两条路之间权衡）：
    # 正文确认的关系用写边工具，本工具只解决案例池里已登记的疑点。
    # 2026-09-13 伏笔即事件树：伏笔不再有自己的线程对象，埋设事件本身就是树根，
    # 续接/回收都表达为"把一个事件挂进某棵已存在的树"。
    # 2026-09-13 登记即进池：案例不再等本章收尾才可检索，检索与解决面当章即可用
    @tool
    def push_case(
        description: str,
        keys: list[str],
        type: str,
        record_id: str | None = None,
    ) -> str:
        """把分析中发现的新连续性疑点登记进案例池（回执给出案例 id）

        type 是任意描述字符串（如 "伏笔疑点"）；description 只写人类可读说明且不超过 100 字；
        keys/type/record_id 必须作为独立参数提交，示例：
        push_case(description="玉戒尺在第 5 章异常发光", keys=["玉戒尺"], type="伏笔疑点")。
        record_id 填这条疑点涉及的产出记录键（写入回执里的 record，实体/关系/事件/对话都行），
        没有明确记录就省略。
        登记的案例马上就能用 search_pool 检索到，也能直接用回执里的 id promise_case 兑现。
        """
        if ledger.phase != "chapter_open":
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
        json_marker_fields = ('"keys"', '"type"', '"record_id"')
        if any(marker in normalized_description for marker in json_marker_fields):
            raise AnnotationInputError(
                "push_case.description 只接受人类可读说明；keys/type/record_id"
                " 必须作为独立参数提交，不能写入 description 字符串"
            )
        normalized_keys = [unicodedata.normalize("NFC", key).strip() for key in keys]
        if not normalized_keys or any(not key for key in normalized_keys):
            raise AnnotationInputError("push_case.keys 不能为空")
        if len(set(normalized_keys)) != len(normalized_keys):
            raise AnnotationInputError("push_case.keys 不允许重复")
        target_ref: dict[str, Any] = {
            "kind": normalized_type,
            "chapter_id": ledger.current_chapter_id,
            "keys": normalized_keys,
        }
        # 2026-09-18 record_id 可为空：留空（省略或纯空白）即不指向记录，不写进 target_ref
        normalized_record_id = None if record_id is None else unicodedata.normalize("NFC", record_id).strip()
        if normalized_record_id:
            target_ref["record_id"] = _require_chapter_record(
                ledger,
                normalized_record_id,
                record=f"case/{normalized_type}",
                field="record_id",
            )
        target_key = uuid4().hex
        pushed = PendingCase(
            type=normalized_type,
            chapter_id=ledger.current_chapter_id,
            keys=normalized_keys,
            description=normalized_description,
            target_key=target_key,
            target_ref=target_ref,
        )
        ledger.pushed_cases.append(pushed)
        # 2026-09-13 登记即进池：检索面与解决面当章可用；案例 id 即本次生成的 target_key
        ledger.known_case_ids.add(target_key)
        response = {
            "accepted": True,
            "case_id": target_key,
            "note": (
                "案例已登记进案例池：本章内即可用 search_pool 检索到，也可直接用本 id"
                "promise_case 兑现到产出记录、或用 close_case 关闭；本章收尾时它作为"
                "活动案例落库。"
            ),
        }
        return json.dumps(response, ensure_ascii=False)

    @tool
    def promise_case(case_id: CaseId, result_id: str) -> str:
        """把案例兑现到一条产出记录（案例已由该记录交代，池内标记为已解决）

        result_id 填写入回执里的 record（实体/关系/事件/对话各自的记录键），必须是本章
        已经写出来的记录。本面不改图也不改记录：语义改动由那条记录自己承担，
        案例只是记账"这条疑点由哪条记录交代"。
        """
        details = _resolve_case_details(
            ledger=ledger,
            case_id=case_id,
            tool_name="promise_case",
        )
        normalized_result_id = _require_chapter_record(
            ledger,
            result_id,
            record=f"case/{details.type}",
            field="result_id",
        )
        resolved = ResolvedCase(
            case_id=details.id,
            action="promise",
            type=details.type,
            reason=f"由产出记录交代：{normalized_result_id}",
            target_key=details.target_key,
            target_ref=details.target_ref,
            result_id=normalized_result_id,
        )
        return _append_resolved(ledger, details, resolved)

    tools = [
        write_entity,
        write_metrics,
        write_event,
        write_relation,
        write_dialogue,
        finish,
        *build_search_tools(query_service, ledger),
        push_case,
        promise_case,
        close_case,
    ]
    for tool_candidate in tools:
        _forbid_undeclared_args(tool_candidate)
    return tools


__all__ = [
    "AnnotationQueryService",
    "AnnotationToolLedger",
    "build_annotation_tools",
]
