"""
章节标注语义写入工具与系统运行账本

核心合同: 每个写入工具完成对应领域的全部业务校验并写入当前候选，
返回固定压缩回执 {accepted, tool, domain, item_count}。
完整参数和完整结果只进入审计库，不回到模型上下文。
"""

from __future__ import annotations

import json
import unicodedata
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from langchain_core.tools import tool

from .candidates import extract_dialogue_candidates
from .errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationInvariantError,
    AnnotationProtocolError,
)
from .fact_graph import FactGraph
from .schema import (
    RELATION_CHANGE_KIND_LABELS,
    RELATION_DEFINITIONS,
    ActiveCaseDetails,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEvent,
    BoundForeshadowing,
    BoundSentenceLabel,
    CaseSearchResult,
    ChunkMetricsInput,
    ChunkParagraphInfo,
    Confidence,
    DialogueCandidate,
    DialogueInput,
    DialogueSubmissionItem,
    DialogueVerdict,
    EntityDirectoryInput,
    EntityInput,
    EntityNumber,
    EntityType,
    EventAppendItem,
    EventAppendItemArg,
    EventParticipantArg,
    EventParticipantInput,
    EventTreeHistoryResult,
    NarrativeFunction,
    PayoffLikelihood,
    PendingCase,
    RelationArg,
    RelationChangeKindArg,
    RelationInput,
    ResolvedCase,
    SearchResult,
    SentenceLabelInput,
    SetupStatus,
    TextSearchResult,
    Tone,
    WriteEventArg,
    WriteEventInput,
    WriteEventPatchArgs,
    normalize_semantic_text,
    tone_catalog_text,
)

# 2026-08-22伏笔并入事件树（isforeshadowing），不再是独立领域
# 2026-09-07 句级监督：句标签随既有 write_metrics 可选参数提交（不新增工具），
# 系统在 metrics 写入时按原文定位绑定，落在 bound_payloads["sentence_labels"]
_DOMAIN_NAMES = (
    "metrics",
    "entities",
    "character_observations",
    "dialogues",
    "events",
    "relations",
)
_DOMAIN_NAMES_SET = frozenset(_DOMAIN_NAMES)
_DIRECT_WRITE_DOMAIN_NAMES = frozenset({"metrics", "entities", "dialogues", "relations"})
# 2026-09-07 句标签冻结软下限（每章 2-3 句定稿）：低于 2 留痕覆盖告警，不阻断冻结
_SENTENCE_LABEL_MIN_PER_CHUNK = 2
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
    ) -> SearchResult:
        """2026-09-11 用于检索活动案例与伏笔线程（案例的唯一发现通道）"""

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

    def thread_exists(self, setup_id: str) -> bool:
        """2026-08-11 用于校验 push_case 携带的伏笔线程 id 属于当前 run 活跃线程"""


@dataclass(slots=True)
class AnnotationToolLedger:
    """2026-08-07 用于保存单 chunk 领域写入和系统绑定状态"""

    run_scope: str
    current_chapter_id: int
    current_chunk_id: int
    current_chunk_text: str
    allow_future_context: bool
    phase: str = "chunk_open"
    dialogue_candidates: list[DialogueCandidate] = field(default_factory=list)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)
    domain_receipts: set[str] = field(default_factory=set)
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
    # 2026-08-12 最近一次 write_dialogues 未提交候选序号（系统默认按 not_dialogue 处理）
    dialogue_missing_indexes: list[int] = field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（仅留痕不阻断），随 chunk 持久化
    coverage_warnings: list[str] = field(default_factory=list)
    annotation: BoundChapterAnnotation | None = None
    errors: list[str] = field(default_factory=list)
    search_log: list[dict[str, Any]] = field(default_factory=list)
    graph_queried: bool = False
    graph: FactGraph | None = None
    # 2026-08-18 事件森林/DAG：当前 chunk 的段落坐标映射，用于事件锚点校验和证据派生
    paragraph_info: ChunkParagraphInfo | None = None
    # 2026-08-22已写事件节点 id（含历史树根），供伏笔 setup/payoff 授权
    authorized_event_ids: set[str] = field(default_factory=set)
    # 2026-09-04事件树 id 集合：setup/payoff 误传 tree_id 时给出针对性纠错提示
    authorized_tree_ids: set[str] = field(default_factory=set)
    # 2026-08-19 当前章节序号（跨章因果校验用）
    current_chapter_order: int | None = None
    # 2026-08-22本章事件树状态（单章闭环）；历史树视图缓存供 cause_tree_id 引用
    event_trees: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_tree_views: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 2026-09-11 write_event 草稿补丁：校验失败的整份提交缓存于此供 patches 增量修正；
    # 刻意不进 snapshot/restore——补丁合并结果跨单次调用失败保留，随 chunk 生命周期消亡
    pending_event_draft: dict[str, Any] | None = None

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

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于同步 LangGraph 和工具账本阶段"""
        self.phase = phase

    def stash_event_draft(self, args: dict[str, Any]) -> None:
        """2026-09-11 用于缓存校验失败的 write_event 整份提交，供 patches 增量修正"""
        self.pending_event_draft = deepcopy(args)

    def merge_event_patches(self, patches: list[list[Any]]) -> dict[str, Any]:
        """2026-09-11 用于在失败草稿上应用 [字段路径, 新值] 补丁并返回合并后的完整参数

        路径为点分形式（如 children.0.participants.0.emotion），与校验报错中的路径
        一致；最后一段允许新建字段（未知键由 WriteEventInput 的 extra=forbid 把关）。
        合并结果回写草稿：补丁后仍校验失败时，下次补丁基于本次合并结果继续修正，
        模型永远不必重发草稿中已正确的部分。
        """
        if self.pending_event_draft is None:
            raise AnnotationInputError(
                "没有可修正的 write_event 草稿（上次提交未缓存或已被整体重交取代），请提交完整参数"
            )
        draft = deepcopy(self.pending_event_draft)
        for patch_index, patch in enumerate(patches):
            if not isinstance(patch, (list, tuple)) or len(patch) != 2:
                raise AnnotationInputError(f"patches[{patch_index}] 必须是 [字段路径, 新值] 二元数组")
            path = str(patch[0]).strip()
            if path.startswith("write_event."):
                path = path[len("write_event."):]
            segments = path.split(".")
            node: Any = draft
            for segment in segments[:-1]:
                if isinstance(node, list):
                    if not segment.isdigit() or int(segment) >= len(node):
                        raise AnnotationInputError(f"patches[{patch_index}] 路径不存在: {path}")
                    node = node[int(segment)]
                elif isinstance(node, dict):
                    if segment not in node:
                        raise AnnotationInputError(f"patches[{patch_index}] 路径不存在: {path}")
                    node = node[segment]
                else:
                    raise AnnotationInputError(f"patches[{patch_index}] 路径非法: {path}")
            leaf = segments[-1]
            if isinstance(node, list):
                if not leaf.isdigit() or int(leaf) >= len(node):
                    raise AnnotationInputError(f"patches[{patch_index}] 路径不存在: {path}")
                node[int(leaf)] = patch[1]
            elif isinstance(node, dict):
                node[leaf] = patch[1]
            else:
                raise AnnotationInputError(f"patches[{patch_index}] 路径非法: {path}")
        self.pending_event_draft = draft
        return draft

    def snapshot(self) -> dict[str, Any]:
        """2026-08-10 用于在单个工具调用执行前保存可回滚账本状态"""
        return deepcopy(
            {
                "phase": self.phase,
                "domain_payloads": self.domain_payloads,
                "bound_payloads": self.bound_payloads,
                "domain_receipts": self.domain_receipts,
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
                "event_trees": self.event_trees,
                "history_tree_views": self.history_tree_views,
                "dialogue_missing_indexes": self.dialogue_missing_indexes,
                "annotation": self.annotation,
                "search_log": self.search_log,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-10 用于在单个工具调用失败时恢复该调用开始前的账本状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

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
    # 事件树写入（write_event）
    # ------------------------------------------------------------------

    def _resolve_cause_tree(self, cause_tree_id: str | None) -> dict[str, Any] | None:
        """2026-08-22 用于解析因果前驱树（本章已建树或 search_event 授权的历史树）"""
        if cause_tree_id is None:
            return None
        cause = self.event_trees.get(cause_tree_id) or self.history_tree_views.get(cause_tree_id)
        if cause is None:
            raise ValueError(
                f"write_event.cause_tree_id 引用不存在的树: {cause_tree_id}"
                "（本章新树用 write_event 返回的 tree_id；前文剧情先 search_event 检索）"
            )
        return cause

    def _finalize_event_domain(self) -> None:
        """2026-08-30 用于在最后一棵事件树后完成事件及人物动态状态领域"""
        events_bound = list(self.bound_payloads.get("events") or [])
        observations_bound = list(self.bound_payloads.get("character_observations") or [])
        self.domain_payloads["events"] = events_bound
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["character_observations"] = observations_bound
        self.bound_payloads["character_observations"] = observations_bound
        self.domain_receipts.update({"events", "character_observations"})

    def write_event_tree(self, payload: WriteEventInput, *, tool_name: str = "write_event") -> dict[str, Any]:
        """2026-08-30 用于原子创建单棵事件树并按显式标记完成事件领域"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许创建事件")
        if "events" in self.domain_receipts:
            raise AnnotationProtocolError("事件领域已经完成，不允许继续 write_event")
        if payload.description is None:
            self._finalize_event_domain()
            self.pending_event_draft = None
            self.write_records.append(
                {
                    "chunk_id": self.current_chunk_id,
                    "domain": "events",
                    "payload": {
                        "tool": tool_name,
                        "tree_id": None,
                        "description": None,
                        "children": [],
                        "character_observation_count": 0,
                        "finalized": True,
                    },
                }
            )
            self._rebuild_ready_chunk_if_complete()
            return {
                "accepted": True,
                "tool": tool_name,
                "domain": "events",
                "item_count": 0,
                "finalized": True,
                "derived_domains": ["character_observations"],
                "character_observation_count": 0,
            }
        cause = self._resolve_cause_tree(payload.cause_tree_id)

        entity_types = self._fact_entity_catalog()
        errors: list[str] = []
        # 节点标签用点分路径（与草稿补丁的 patches 路径同一语法），报错即可直接作为补丁路径
        participant_groups = [("participants", payload.participants)]
        participant_groups.extend(
            (f"children.{child_index}", child.participants)
            for child_index, child in enumerate(payload.children)
        )
        for node_label, participants in participant_groups:
            for participant_index, participant in enumerate(participants):
                name = participant.entity
                key = unicodedata.normalize("NFC", name).strip().casefold()
                resolved_key = _norm_graph_name(self.graph.resolve_name(name)) if self.graph is not None else key
                actual_type = entity_types.get(resolved_key) or entity_types.get(key)
                label = f"write_event.{node_label}.{participant_index}"
                if actual_type is None:
                    errors.append(
                        f"{label} 未在 write_entities 中声明: {name}"
                        "（请先在 write_entities 声明该实体，或改用已登记实体名）"
                    )
                    continue
                if participant.role == "地点" and actual_type != "location":
                    errors.append(f"{label} 地点角色端点必须是 location: {name}（登记类型 {actual_type}）")
                observation_fields = (participant.narrative_role, participant.action, participant.emotion)
                if actual_type == "character" and not all(value is not None for value in observation_fields):
                    errors.append(f"{label} 是 character，必须同时提供 narrative_role/action/emotion: {name}")
                elif actual_type != "character" and any(value is not None for value in observation_fields):
                    errors.append(f"{label} 不是 character，不得提供 narrative_role/action/emotion: {name}")
        if errors:
            raise ValueError("write_event 校验失败: " + "；".join(errors))

        tree_id = self._tree_id()
        root_node_id = self._node_id()

        causal_refs: list[str] = []
        cross_chapter = False
        if cause is not None:
            source_node_id = str(cause.get("root_node_id") or cause.get("tree_id"))
            causal_refs = [source_node_id]
            # 前驱树不在本章 event_trees 中即来自已完成章节，天然跨章
            cross_chapter = payload.cause_tree_id not in self.event_trees

        bound_root = BoundEvent(
            node_id=root_node_id,
            tree_id=tree_id,
            parent_node_id=None,
            cause_role="root",
            description=payload.description,
            participants=[EventParticipantInput(**p.model_dump(mode="python")) for p in payload.participants],
            is_foreshadow_setup=payload.isforeshadowing,
            causal_event_refs=causal_refs,
        )
        planned_nodes: list[BoundEvent] = [bound_root]
        tree_nodes: dict[str, dict[str, str | None]] = {
            root_node_id: {
                "node_id": root_node_id,
                "parent_node_id": None,
                "cause_role": "root",
            }
        }
        trunk_tail = root_node_id
        appended: list[dict[str, str]] = []
        for child in payload.children:
            node_id = self._node_id()
            parent_node_id = trunk_tail
            role = child.type
            planned_nodes.append(
                BoundEvent(
                    node_id=node_id,
                    tree_id=tree_id,
                    parent_node_id=parent_node_id,
                    cause_role=role,
                    description=child.description,
                    participants=[
                        EventParticipantInput(**participant.model_dump(mode="python"))
                        for participant in child.participants
                    ],
                    is_foreshadow_setup=False,
                    causal_event_refs=[],
                )
            )
            tree_nodes[node_id] = {
                "node_id": node_id,
                "parent_node_id": parent_node_id,
                "cause_role": role,
            }
            appended.append(
                {
                    "node_id": node_id,
                    "type": role,
                    "parent_node_id": parent_node_id,
                }
            )
            if role == "main":
                trunk_tail = node_id

        bound_foreshadowing: BoundForeshadowing | None = None
        if payload.isforeshadowing:
            bound_foreshadowing = BoundForeshadowing(
                description=payload.description,
                confidence=Confidence.MEDIUM,
                setup_node_id=root_node_id,
                setup_kind=payload.setup_kind,
                expected_payoff_family=payload.expected_payoff_family,
                payoff_likelihood=payload.payoff_likelihood,
            )

        new_observations: list[BoundCharacterObservation] = []
        for node in planned_nodes:
            for participant in node.participants:
                if participant.narrative_role is None or participant.action is None or participant.emotion is None:
                    continue
                new_observations.append(
                    BoundCharacterObservation(
                        character=participant.entity,
                        role_function=participant.narrative_role,
                        action=participant.action,
                        emotion=participant.emotion,
                    )
                )
        observations_bound = list(self.bound_payloads.get("character_observations") or [])
        observations_bound.extend(new_observations)
        observation_keys: set[tuple[str, str]] = set()
        duplicate_observations: list[tuple[str, str]] = []
        for observation in observations_bound:
            observation_key = (observation.character, observation.action)
            if observation_key in observation_keys:
                duplicate_observations.append(observation_key)
            observation_keys.add(observation_key)
        if duplicate_observations:
            raise ValueError(f"write_event 人物动态状态重复: {duplicate_observations}")

        self.event_trees[tree_id] = {
            "tree_id": tree_id,
            "chapter_id": self.current_chapter_id,
            "chapter_order": self.current_chapter_order,
            "root_node_id": root_node_id,
            "trunk_tail": trunk_tail,
            "isforeshadowing": payload.isforeshadowing,
            "nodes": tree_nodes,
        }
        self.authorized_event_ids.update(node.node_id for node in planned_nodes)
        # 2026-09-04 登记 tree_id 以便误传时给出针对性纠错提示（tree_id 不授权 setup/payoff）
        self.authorized_tree_ids.add(tree_id)
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.extend(planned_nodes)
        self.domain_payloads["events"] = events_bound
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["character_observations"] = observations_bound
        self.bound_payloads["character_observations"] = observations_bound
        if payload.finalize_events:
            self._finalize_event_domain()

        foreshadow_receipt_node: str | None = None
        if bound_foreshadowing is not None:
            bound_foreshadowings = list(self.bound_payloads.get("foreshadowings") or [])
            bound_foreshadowings.append(bound_foreshadowing)
            self.bound_payloads["foreshadowings"] = bound_foreshadowings
            foreshadow_receipt_node = root_node_id

        self.write_records.append(
            {
                "chunk_id": self.current_chunk_id,
                "domain": "events",
                "payload": {
                    "tool": tool_name,
                    "tree_id": tree_id,
                    "description": payload.description,
                    "children": appended,
                    "character_observation_count": len(new_observations),
                    "finalized": payload.finalize_events,
                },
            }
        )
        self._rebuild_ready_chunk_if_complete()
        # 树已成功落账，草稿修复周期结束（无论本次是整体提交还是补丁提交）
        self.pending_event_draft = None
        receipt: dict[str, Any] = {
            "accepted": True,
            "tool": tool_name,
            "domain": "events",
            "tree_id": tree_id,
            "root_node_id": root_node_id,
            "cause_role": "root",
            "cross_chapter": cross_chapter,
            "children": appended,
            "trunk_tail": trunk_tail,
            "derived_domains": ["character_observations"],
            "character_observation_count": len(new_observations),
            "finalized": payload.finalize_events,
        }
        if foreshadow_receipt_node is not None:
            receipt["foreshadowing_setup_node_id"] = foreshadow_receipt_node
        return receipt

    # ------------------------------------------------------------------
    # 领域写入核心合同
    # ------------------------------------------------------------------

    def bind_sentence_labels(self, items: list[SentenceLabelInput]) -> None:
        """2026-09-07 用于把随 write_metrics 提交的自选句情绪标签定位绑定到章文本区间

        句标签不设独立工具（随既有 write_metrics 的可选参数搭车提交）；整体替换
        语义：每次调用以本列表为准。定位失败（非原句/改写）整次调用报错自纠。
        """
        bound_labels: list[BoundSentenceLabel] = []
        seen_spans: set[tuple[int, int]] = set()
        for item in items:
            located = _locate_sentence(self.current_chunk_text, item.sentence)
            if located is None:
                raise ValueError(
                    "write_metrics.sentence_labels.sentence 未在当前章节原文中找到唯一匹配: "
                    f"{item.sentence[:50]}"
                    "（请从正文原样摘录完整句子，不要改写或缩写）"
                )
            span = (located[0], located[1])
            if span in seen_spans:
                raise ValueError(f"write_metrics.sentence_labels 句子重复: {item.sentence[:50]}")
            seen_spans.add(span)
            bound_labels.append(
                BoundSentenceLabel(
                    sentence=located[2],
                    emotion=item.emotion,
                    start=span[0],
                    end=span[1],
                )
            )
        self.bound_payloads["sentence_labels"] = bound_labels

    def write_domain(self, domain: str, payload: Any, *, tool_name: str) -> dict[str, Any]:
        """2026-08-20 用于校验、绑定并完整替换当前 chunk 单个领域，成功即写入当前候选（优化：内联验证）"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许写入正式标注")
        if domain not in _DIRECT_WRITE_DOMAIN_NAMES:
            raise AnnotationInputError(f"未知标注领域: {domain}")

        # 2026-08-20 内联端点验证与领域绑定逻辑，扁平化调用链
        entity_types = self._fact_entity_catalog()
        errors: list[str] = []

        # 内联端点校验（仅对需要端点验证的领域执行）
        def check_entity(name: str, expected_types: tuple[EntityType, ...] | None, label: str, index: int) -> None:
            key = unicodedata.normalize("NFC", name).strip().casefold()
            resolved_key = key
            if self.graph is not None:
                resolved_key = _norm_graph_name(self.graph.resolve_name(name))
            actual_type = entity_types.get(resolved_key) or entity_types.get(key)
            if actual_type is None:
                errors.append(
                    f"[{index}] {label} 未在当前 chunk 的 write_entities 中声明: {name}"
                    "（请先在 write_entities 声明该实体，或改用已登记实体名）"
                )
                return
            if expected_types is not None and actual_type not in expected_types:
                errors.append(
                    f"[{index}] {label} 端点类型必须属于 {list(expected_types)}，"
                    f"实际为 {actual_type}（该名称在图上的登记类型是 {actual_type}，"
                    "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
                )

        if domain == "dialogues":
            for index, item in enumerate(payload):
                if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                    check_entity(item.speaker, ("character",), "dialogue.speaker", index)
        elif domain == "relations":
            for index, item in enumerate(payload):
                definition = RELATION_DEFINITIONS[str(item.relation_type)]
                check_entity(item.from_entity, definition["from_types"], "relation.from_entity", index)
                check_entity(item.to_entity, definition["to_types"], "relation.to_entity", index)

        if errors:
            raise ValueError(f"{domain} 校验失败: " + "；".join(errors))

        # 内联领域绑定逻辑（原 _bind_domain 实现）
        # 2026-09-04 单一写面：entities/relations 不再构造 bound 副本——
        # 图域登记与操作日志在下方 graph 分支完成，bound 仅服务非图领域
        if domain == "metrics":
            bound = payload
        elif domain == "entities":
            for entity in payload.entities:
                key = unicodedata.normalize("NFC", entity.name).strip().casefold()
                registered_type = self.graph.entity_types.get(key) if self.graph is not None else None
                if registered_type is not None and registered_type != entity.entity_type:
                    raise ValueError(
                        f"已登记实体不允许变更大类: {entity.name} "
                        f"registered={registered_type} actual={entity.entity_type}（"
                        '同一词条的不同身份请使用区分性名称，如"圣城"是 location、'
                        '"圣城朝堂"是 organization，不要互相改类）'
                    )
            bound = None
        elif domain == "dialogues":
            candidates = self.dialogue_candidates
            candidate_by_index = dict(enumerate(candidates, start=1))
            seen_indexes: set[int] = set()
            for item in payload:
                if item.candidate_index not in candidate_by_index:
                    raise ValueError(
                        f"write_dialogues.candidate_index 超出系统候选范围: "
                        f"index={item.candidate_index} expected=1..{len(candidates)}"
                    )
                if item.candidate_index in seen_indexes:
                    raise ValueError(f"write_dialogues.candidate_index 重复: {item.candidate_index}")
                seen_indexes.add(item.candidate_index)
            self.dialogue_missing_indexes = sorted(set(candidate_by_index) - seen_indexes)
            bound_dialogues: list[BoundDialogue] = []
            for item in sorted(payload, key=lambda entry: entry.candidate_index):
                if item.verdict == DialogueVerdict.NOT_DIALOGUE:
                    continue
                candidate = candidate_by_index[item.candidate_index]
                bound_dialogues.append(
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
            bound = bound_dialogues
        elif domain == "relations":
            bound = None
        else:
            raise AnnotationInputError(f"未知标注领域: {domain}")

        relation_outcomes: list[dict[str, Any]] = []
        if domain in {"entities", "relations"} and self.graph is None:
            # 2026-09-04 单一写面：图域写入必须有常驻事实图，否则操作日志无处登记
            raise AnnotationInvariantError(f"write_{domain} 需要常驻事实图，graph 缺失")
        if self.graph is not None:
            if domain == "entities":
                self.graph.register_entities(list(payload.entities))
                self.graph.record_entity_ops(list(payload.entities), chapter_id=self.current_chunk_id)
            elif domain == "relations":
                self.graph.reset_chapter_relations()
                resolved_items: list[RelationInput] = []
                for item in payload:
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
                        relation_outcomes.append(
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
                    relation_outcomes.append(
                        {
                            "from": resolved_from,
                            "to": resolved_to,
                            "relation_type": str(item.relation_type),
                            "outcome": "assert" if added else "skipped_existing",
                        }
                    )
                self.graph.record_relation_asserts(resolved_items, chapter_id=self.current_chunk_id)
        self.domain_payloads[domain] = payload
        # 2026-09-04 单一写面：entities/relations 不再进 bound_payloads（图真相源是 FactGraph）
        if domain not in {"entities", "relations"}:
            self.bound_payloads[domain] = bound
        self.domain_receipts.add(domain)
        dumped = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else [item.model_dump(mode="json") for item in payload]
        )
        self.write_records.append(
            {
                "chunk_id": self.current_chunk_id,
                "domain": domain,
                "payload": dumped,
            }
        )
        self._rebuild_ready_chunk_if_complete()
        return self._receipt(
            tool_name=tool_name,
            domain=domain,
            payload=payload,
            relation_outcomes=relation_outcomes or None,
        )

    def _receipt(
        self,
        *,
        tool_name: str,
        domain: str,
        payload: Any,
        relation_outcomes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """2026-08-10 用于生成模型可见的固定压缩回执"""
        if domain == "metrics":
            item_count = 1
        elif domain == "entities":
            item_count = len(payload.entities)
        else:
            item_count = len(payload)
        receipt: dict[str, Any] = {
            "accepted": True,
            "tool": tool_name,
            "domain": domain,
            "item_count": item_count,
        }
        if relation_outcomes is not None:
            receipt["relations"] = relation_outcomes
        if domain == "dialogues":
            receipt["defaulted_not_dialogue"] = list(self.dialogue_missing_indexes)
        return receipt

    # ------------------------------------------------------------------
    # 领域绑定与校验

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
                f"{label} 未在当前 chunk 的 write_entities 中声明: {name}（"
                "请先在 write_entities 声明该实体，或改用已登记实体名）"
            )
        if expected_types is not None and actual_type not in expected_types:
            raise ValueError(
                f"{label} 端点类型必须属于 {list(expected_types)}，实际为 {actual_type}"
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

    def _rebuild_ready_chunk_if_complete(self) -> None:
        """2026-08-30 用于在六个内部数据领域就绪后构造并缓存 ready_chunk"""
        if not _DOMAIN_NAMES_SET <= self.domain_receipts:
            return
        self.ready_chunk = self._build_ready_chunk()

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
                    f"[{index}] {label} 未在当前 chunk 的 write_entities 中声明: {name}"
                    "（请先在 write_entities 声明该实体，或改用已登记实体名）"
                )
                return
            if expected_types is not None and actual_type not in expected_types:
                errors.append(
                    f"[{index}] {label} 端点类型必须属于 {list(expected_types)}，"
                    f"实际为 {actual_type}（该名称在图上的登记类型是 {actual_type}，"
                    "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
                )

        # character_observations 端点校验
        for index, item in enumerate(payloads["character_observations"]):
            check_entity(item.character, ("character",), "character_observation.character", index)

        # dialogues 端点校验
        for index, item in enumerate(payloads["dialogues"]):
            if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                check_entity(item.speaker, ("character",), "dialogue.speaker", index)

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
            foreshadowings=list(self.bound_payloads.get("foreshadowings") or []),
            sentence_labels=list(self.bound_payloads.get("sentence_labels") or []),
        )

    def _dialogue_coverage_warnings(self) -> list[str]:
        """2026-09-05 用于在冻结前确定性登记对话候选覆盖缺口（仅告警不阻断冻结）

        空载荷回执（write_dialogues([])）同样算已写领域，但候选检出数与载荷的
        差值属于静默判定，这里把最终态缺口随 chunk 留痕，供报告附录 B 展示。
        """
        candidates = len(self.dialogue_candidates)
        if candidates == 0:
            return []
        payload = self.domain_payloads.get("dialogues")
        if not payload:
            return [f"对话覆盖: 检出 {candidates} 条系统对话候选但 write_dialogues 未提交任何判定"]
        if self.dialogue_missing_indexes:
            return [
                f"对话覆盖: {len(self.dialogue_missing_indexes)} 条候选未提交判定"
                f"（序号 {self.dialogue_missing_indexes}），按 not_dialogue 默认处理"
            ]
        return []

    def _sentence_label_coverage_warnings(self) -> list[str]:
        """2026-09-07 用于在冻结前确定性登记句级监督覆盖缺口（仅告警不阻断冻结）

        每章 2-3 句为用户定稿密度；低于 2 句（含空载荷）随 chunk 留痕，
        供 linguistic 阶段边界拟合的样本量判断与报告附录展示。
        """
        labels = self.bound_payloads.get("sentence_labels") or []
        if len(labels) >= _SENTENCE_LABEL_MIN_PER_CHUNK:
            return []
        return [f"句标签覆盖: 仅标注 {len(labels)} 句（每章应自选 2-3 句）"]

    def complete_active_chunk(self) -> BoundChunkAnnotation:
        """2026-08-30 用于检查六领域回执与 ready_chunk 后冻结当前 chunk"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 complete_chunk")
        missing = [domain for domain in _DOMAIN_NAMES if domain not in self.domain_receipts]
        if missing:
            raise ValueError(f"当前 chunk 尚未写入全部领域: {missing}")
        if self.ready_chunk is None:
            raise AnnotationInvariantError("六个领域均已写入但 ready_chunk 缺失，系统不变量被破坏")
        warnings = [*self._dialogue_coverage_warnings(), *self._sentence_label_coverage_warnings()]
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
                    "causal_event_refs": list(item.causal_event_refs),
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
        if "foreshadowings" in payloads:
            views["foreshadowings"] = [
                {
                    "description": item.description,
                    "confidence": str(item.confidence),
                    "setup_node_id": item.setup_node_id,
                }
                for item in payloads["foreshadowings"]
            ]
        return views

    def context_summary(self) -> dict[str, Any]:
        """2026-08-10 用于从账本确定性生成当前模型请求的上下文摘要"""
        return {
            "phase": self.phase,
            "chunk_id": self.current_chunk_id,
            "writes": {domain: {"accepted": domain in self.domain_receipts} for domain in _DOMAIN_NAMES},
            "missing_domains": [domain for domain in _DOMAIN_NAMES if domain not in self.domain_receipts],
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


def _normalize_query(query: str, *, tool_name: str) -> str:
    """2026-08-07 用于统一校验查询工具输入长度与空白"""
    normalized = unicodedata.normalize("NFC", query).strip()
    if not normalized or len(normalized) > 2000:
        raise AnnotationInputError(f"{tool_name}.query 必须为 1 至 2000 个 Unicode 字符")
    return normalized


def _locate_sentence(chunk_text: str, sentence: str) -> tuple[int, int, str] | None:
    """2026-09-07 用于把 agent 摘录句定位绑定到章文本唯一区间

    NFC 归一后精确匹配；命中多处（重复句）取第一处并仍算唯一合法绑定，
    句子本体以原文命中文本为准（NFC 等价差异归一）。
    """
    normalized_text = unicodedata.normalize("NFC", chunk_text)
    normalized_sentence = unicodedata.normalize("NFC", sentence).strip()
    if not normalized_sentence:
        return None
    index = normalized_text.find(normalized_sentence)
    if index < 0:
        return None
    return index, index + len(normalized_sentence), normalized_sentence


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


def _resolve_participant_numbers(
    participants: list[EventParticipantArg],
    *,
    graph: FactGraph | None,
    label: str,
) -> list[EventParticipantInput]:
    """2026-09-11 用于把编号形态的参与者翻成规范名形态（label 为补丁同源的点分路径前缀）"""
    if graph is None:
        raise AnnotationInvariantError("实体编号解析需要常驻事实图，graph 缺失")
    resolved: list[EventParticipantInput] = []
    for index, participant in enumerate(participants):
        resolved.append(
            EventParticipantInput(
                entity=graph.resolve_number(participant.entity, label=f"{label}.{index}"),
                role=participant.role,
                narrative_role=participant.narrative_role,
                action=participant.action,
                emotion=participant.emotion,
            )
        )
    return resolved


def _resolve_write_event_arg(arg: WriteEventArg, *, graph: FactGraph | None) -> WriteEventInput:
    """2026-09-11 用于把编号形态的事件树提交翻成内部规范名形态

    参与者编号缺失/未登记时按 write_event.children.i.participants.j 点分路径报错，
    与补丁路径同一语法，模型可直接照路径修正。
    """
    if graph is None:
        raise AnnotationInvariantError("write_event 实体编号解析需要常驻事实图，graph 缺失")
    children = [
        EventAppendItem(
            type=child.type,
            description=child.description,
            participants=_resolve_participant_numbers(
                child.participants,
                graph=graph,
                label=f"write_event.children.{child_index}.participants",
            ),
        )
        for child_index, child in enumerate(arg.children)
    ]
    return WriteEventInput(
        description=arg.description,
        participants=_resolve_participant_numbers(
            arg.participants,
            graph=graph,
            label="write_event.participants",
        ),
        children=children,
        isforeshadowing=arg.isforeshadowing,
        cause_tree_id=arg.cause_tree_id,
        setup_kind=arg.setup_kind,
        expected_payoff_family=arg.expected_payoff_family,
        payoff_likelihood=arg.payoff_likelihood,
        finalize_events=arg.finalize_events,
    )


def _resolve_relation_args(items: list[RelationArg], *, graph: FactGraph | None) -> list[RelationInput]:
    """2026-09-11 用于把编号形态的关系边翻成内部规范名形态（端点解析失败按索引报错）"""
    if graph is None:
        raise AnnotationInvariantError("write_relations 实体编号解析需要常驻事实图，graph 缺失")
    resolved: list[RelationInput] = []
    for index, item in enumerate(items):
        resolved.append(
            RelationInput(
                from_entity=graph.resolve_number(item.from_entity, label=f"write_relations[{index}].from_entity"),
                to_entity=graph.resolve_number(item.to_entity, label=f"write_relations[{index}].to_entity"),
                relation_type=item.relation_type,
            )
        )
    return resolved


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
        pivot_moment: bool = False,
        cliffhanger: bool = False,
        sentence_labels: list[SentenceLabelInput] | None = None,
    ) -> str:
        """2026-08-11 用于完整替换当前 chunk 摘要和叙事指标，章节摘要由系统用各 chunk summary 自动生成

        emotional_valence 为情绪分值整数 -2..2（-2 强烈负面 / -1 轻微负面 / 0 中性 /
        1 轻微正面 / 2 强烈正面）。

        2026-09-07 句级监督：可选 sentence_labels 参数随本工具提交从当前章正文自选的
        2-3 句整句情绪标签（每条 {sentence, emotion}；sentence 必须原样摘录完整句子
        不得改写，emotion 为同一套 -2..2 整数分值）。选句标准由模型自行判断——优先选
        情绪表达有代表性或语气/标点有区分度的句子，也允许选 0 分句。系统按原文定位
        绑定字符区间，找不到的句子整次调用报错自纠；重复调用 write_metrics 时句标签
        以最后一次提交为准。
        """
        payload = ChunkMetricsInput(
            summary=summary,
            emotional_valence=emotional_valence,
            narrative_function=narrative_function,
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
        )
        # 2026-09-07 句标签先绑定后写域：绑定失败整次调用报错，metrics 不落任何写入
        ledger.bind_sentence_labels(list(sentence_labels) if sentence_labels else [])
        return json.dumps(
            ledger.write_domain("metrics", payload, tool_name="write_metrics"),
            ensure_ascii=False,
        )

    @tool
    def write_entities(entities: list[EntityInput]) -> str:
        """2026-08-08 创建；2026-08-23 用于向当前 chunk 追加新实体或更新已有实体（单列表，不撤销已登记）

        回执 numbers 给出每个实体在本 run 的运行期编号；events/relations/dialogues
        的实体引用一律填该编号。"""
        if ledger.graph is not None and ledger.graph.entity_types and not ledger.graph_queried:
            raise AnnotationAuthorizationError("提交 write_entities 前必须先调用 search_graph 查询已登记实体")
        payload = EntityDirectoryInput(entities=entities)
        receipt = ledger.write_domain("entities", payload, tool_name="write_entities")
        if ledger.graph is not None:
            receipt["numbers"] = [
                [ledger.graph.entity_number(entity.name), entity.name] for entity in entities
            ]
        return json.dumps(receipt, ensure_ascii=False)

    @tool
    def write_dialogues(items: list[DialogueSubmissionItem]) -> str:
        """2026-08-12 用于按系统候选序号提交对话三态判断（数组格式）
        （items 每条为 [candidate_index, verdict, speaker, tone]；speaker 为运行期
        实体编号（write_entities 回执 numbers / search_graph 回执 n），未知时 null；
        tone 为语气闭合枚举：见参数说明，未知时 null；
        只提交 dialogue 与 inner_monologue 候选，未提交的候选系统默认按 not_dialogue
        处理，回执会列出被默认处理的候选序号，可再次调用补充）"""
        if ledger.graph is None and any(speaker is not None for (_i, _v, speaker, _t) in items):
            raise AnnotationInvariantError("write_dialogues 说话人编号解析需要常驻事实图，graph 缺失")
        payload = [
            DialogueInput(
                candidate_index=index,
                verdict=verdict,
                speaker=(
                    ledger.graph.resolve_number(speaker, label=f"write_dialogues[{index}].speaker")
                    if speaker is not None and ledger.graph is not None
                    else None
                ),
                tone=tone,
            )
            for (index, verdict, speaker, tone) in items
        ]
        return json.dumps(
            ledger.write_domain("dialogues", payload, tool_name="write_dialogues"),
            ensure_ascii=False,
        )

    @tool(args_schema=WriteEventPatchArgs)
    def write_event(
        finalize_events: bool = False,
        description: str | None = None,
        participants: list[EventParticipantArg] | None = None,
        children: list[EventAppendItemArg] | None = None,
        isforeshadowing: bool = False,
        cause_tree_id: str | None = None,
        setup_kind: str | None = None,
        expected_payoff_family: str | None = None,
        payoff_likelihood: PayoffLikelihood | None = None,
        patches: list[list[Any]] | None = None,
    ) -> str:
        """2026-08-30 用于一次提交单棵事件树并声明是否结束事件阶段

        2026-09-11 实体编号：参与者的 entity 是运行期编号（write_entities 回执
        numbers / search_graph 回执 n），不接受实体名称。

        2026-09-11 草稿补丁：上次 write_event 校验失败后，重调只需 patches=
        [[字段路径, 新值], ...]（路径与报错中的路径一致，如
        children.0.participants.0.emotion），系统在缓存的草稿上增量修正后整体校验，
        已正确的部分无需重发；带 patches 时其余字段忽略。无草稿场景（如流截断后）
        必须整体重交完整参数。
        """
        if patches:
            merged = ledger.merge_event_patches(patches)
            patch_arg = WriteEventPatchArgs.model_validate(merged)
            payload = _resolve_write_event_arg(patch_arg, graph=ledger.graph)
            receipt = ledger.write_event_tree(payload, tool_name="write_event")
            receipt["draft_repaired"] = True
            return json.dumps(receipt, ensure_ascii=False)
        arg = WriteEventArg(
            description=description,
            participants=participants or [],
            children=children or [],
            isforeshadowing=isforeshadowing,
            cause_tree_id=cause_tree_id,
            setup_kind=setup_kind,
            expected_payoff_family=expected_payoff_family,
            payoff_likelihood=payoff_likelihood,
            finalize_events=finalize_events,
        )
        payload = _resolve_write_event_arg(arg, graph=ledger.graph)
        return json.dumps(
            ledger.write_event_tree(payload),
            ensure_ascii=False,
        )

    @tool
    def write_relations(items: list[RelationArg]) -> str:
        """2026-08-12 用于完整替换当前 chunk 确认存在的闭合类型关系边

        2026-09-11 实体编号：两端 from_entity/to_entity 是运行期编号（write_entities
        回执 numbers / search_graph 回执 n），不接受实体名称。
        （新边建图 assert，已存在的同一条边自动接受为 skipped_existing；
        强化/削弱/解除一律走 resolve_fact_case，不通过本工具表达变化）"""
        payload = _resolve_relation_args(items, graph=ledger.graph)
        return json.dumps(
            ledger.write_domain("relations", payload, tool_name="write_relations"),
            ensure_ascii=False,
        )

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
        伏笔 setup/payoff 填 root_node_id。"""
        normalized_query = _normalize_query(keyword, tool_name="search_event")
        if ledger.phase != "chunk_open":
            raise AnnotationAuthorizationError(f"阶段 {ledger.phase} 不允许 search_event")
        results = query_service.search_event_history(
            normalized_query,
            limit=20,
        )
        views: list[dict[str, Any]] = []
        for item in results:
            # tree_id 供 write_event(cause_tree_id)，root_node_id 供伏笔 setup/payoff
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
        """2026-08-07 用于检索案例池与伏笔线程并返回临时案例编号

        案例不在正文中注入，本工具是发现案例的唯一通道：
        - 只给 query：按关键词匹配案例 keys/description 与活跃伏笔线程；
          查询支持多关键词（空格/标点分隔，任一命中即返回）与通配符
          （% 匹配任意长度、_ 匹配单个字符）。
        - 给 case_type（如 "entity_alias"/"伏笔疑点"，或 "all"）：按最新创建优先
          枚举该类型全部活动案例，不需要关键词；无命中提示时也可用它对案例重做全量枚举。
        回执 pool 汇报池内仍有检索价值的 active 案例总数与类型分布（resolved 不计）。"""
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
        result = query_service.search_pool(
            normalized_query,
            hidden_case_ids=ledger.resolved_case_ids,
            case_type=normalized_type,
            limit=50,
        )
        views: list[dict[str, Any]] = []
        case_numbers: list[int] = []
        for item in result.results:
            if isinstance(item, CaseSearchResult):
                case_number = ledger.register_case_number(item.id)
                # 案例展示即授权其源章（§12.3 章级定位），解决时不再因原文未读取被拒
                ledger.authorized_chapter_ids.add(item.chunk_id)
                case_numbers.append(case_number)
                views.append(
                    {
                        "result_kind": "case",
                        "case_number": case_number,
                        "type": item.type,
                        "created_chapter": item.created_chapter,
                        "description": item.description,
                        "keys": list(item.keys),
                    }
                )
            else:
                views.append(
                    {
                        "result_kind": "foreshadowing",
                        "id": item.record_id,
                        "content": item.content,
                    }
                )
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
                f"case_number 未由 search_pool 返回: {case_number}："
                "案例不在正文中注入，请先 search_pool 检索（可用 case_type=\"all\" 枚举全部未解决案例）"
                "再用回执中的 case_number 解决"
            )
        if case_id in ledger.resolved_case_ids:
            raise AnnotationInputError(f"case_number 已经解决: {case_number}")
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
            "正文对话候选的说话人/语气请用 write_dialogues 提交；"
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
        case_number: int,
        reason: str,
        speaker: EntityNumber | None = None,
        tone: str | None = None,
        description: str | None = None,
        is_inner_monologue: bool | None = None,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为对话记录更新（至少提供一个更新字段）

        2026-09-10 编号判据：case_number 仅指 search_pool 展示的案例
        （含 push_case 登记的对话疑点）；正文 DialogueCandidates 无编号，
        说话人/语气经 write_dialogues 按 candidate_index 提交，两类编号互不通用。

        2026-09-11 speaker 为运行期实体编号（write_entities 回执 numbers /
        search_graph 回执 n）。"""
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_dialogue_case",
        )
        _require_dialogue_case(details)
        resolved_speaker: str | None = None
        if speaker is not None:
            if ledger.graph is None:
                raise AnnotationInvariantError("resolve_dialogue_case speaker 编号解析需要常驻事实图，graph 缺失")
            resolved_speaker = ledger.graph.resolve_number(
                speaker,
                label="resolve_dialogue_case.speaker",
            )
            _require_action_entity(
                ledger,
                resolved_speaker,
                expected_types=("character",),
                label="resolve_dialogue_case.speaker",
            )
        if tone is not None:
            tone = normalize_semantic_text(tone, label="resolve_dialogue_case.tone")
            if tone not in Tone:
                raise AnnotationInputError(
                    f"resolve_dialogue_case.tone 必须是闭合语气枚举: {tone}，"
                    f"合法值: {tone_catalog_text()}"
                )
        resolved_tone: Tone | None = Tone(tone) if tone is not None else None
        resolved = ResolvedCase(
            case_id=details.id,
            action="dialogue",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
            speaker=resolved_speaker,
            tone=resolved_tone,
            description=description,
            is_inner_monologue=is_inner_monologue,
        )
        return _append_resolved(ledger, details, resolved)

    @tool
    def resolve_fact_case(
        case_number: int,
        reason: str,
        from_entity: EntityNumber,
        to_entity: EntityNumber,
        relation_type: str,
        change_kind: RelationChangeKindArg,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为图关系建改删（change_kind 表达变化）

        2026-09-11 端点 from_entity/to_entity 为运行期实体编号（write_entities 回执
        numbers / search_graph 回执 n）；change_kind 取值：新增/强化/削弱/解除/修正/取代/撤回。

        2026-09-04 单一写面：本工具只更新内存 FactGraph（终态即时生效 +
        操作日志登记），不再向 resolved_cases 追加 fact 动作；持久化层从
        操作日志派生关系事实。解除不存在的边会直接报错并回滚本回合，
        避免"accepted 但 search_graph 不变"的空转。"""
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
        from_name = ledger.graph.resolve_number(from_entity, label="resolve_fact_case.from_entity")
        to_name = ledger.graph.resolve_number(to_entity, label="resolve_fact_case.to_entity")
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
        case_number: int,
        reason: str,
        setup_summary: str | None = None,
        setup_kind: str | None = None,
        expected_payoff_family: str | None = None,
        payoff_likelihood: PayoffLikelihood | None = None,
        setup_status: SetupStatus | None = None,
        confidence: Confidence | None = None,
        strength: Confidence | None = None,
        setup_event_id: str | None = None,
        payoff_event_id: str | None = None,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为伏笔线程字段更新（至少提供一个更新字段）

        2026-08-18：setup_event_id/payoff_event_id 用于伏笔续接/回收时绑定事件。
        2026-08-30事件 id 由 write_event 回执或 search_event
        检索获得，须先经授权集合校验。
        2026-09-04未挂伏笔线程的疑点案例被确认为伏笔时，须提供 setup_event_id
        （埋设事件），系统据此就地建立伏笔线程记录确认；判断并非伏笔则用 close_case。"""
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_foreshadowing_case",
        )
        _require_suspicion_case(details, "resolve_foreshadowing_case")
        if not details.target_ref.get("setup_id"):
            if setup_event_id is None:
                raise AnnotationInputError(
                    "该案例未关联伏笔线程；确认其为伏笔须提供 setup_event_id"
                    "（埋设事件，由 write_event 回执或 search_event 授权），"
                    "系统会据此建立伏笔线程；若判断其并非伏笔，请改用 close_case"
                )
            if setup_summary is None:
                setup_summary = details.description
        resolved = ResolvedCase(
            case_id=details.id,
            action="foreshadowing",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
            setup_summary=setup_summary,
            setup_kind=setup_kind,
            expected_payoff_family=expected_payoff_family,
            payoff_likelihood=payoff_likelihood,
            setup_status=setup_status,
            confidence=confidence,
            strength=strength,
            setup_event_id=setup_event_id,
            payoff_event_id=payoff_event_id,
        )
        for event_id, field_name in (
            (setup_event_id, "setup_event_id"),
            (payoff_event_id, "payoff_event_id"),
        ):
            if event_id is None:
                continue
            if event_id not in ledger.authorized_event_ids:
                # 2026-09-04 第6章教训：write_event 回执同时含 tree_id 与 node_id，
                # 模型易把 tree_id 当节点 id 传（tree_id 只作 cause_tree_id 引用），
                # 随后 search_event 查不到本章事件（树仅覆盖已完成章节）→ 空转至回合上限。
                hint = (
                    "（这是事件树 id 而非事件节点 id；setup_event_id/payoff_event_id 须传"
                    " write_event 回执 children[].node_id 或 root_node_id）"
                    if event_id in ledger.authorized_tree_ids
                    else ""
                )
                raise AnnotationAuthorizationError(
                    f"{field_name} 未由 write_event 回执或 search_event 授权: {event_id}{hint}"
                )
        return _append_resolved(ledger, details, resolved)

    @tool
    def close_case(case_number: int, reason: str) -> str:
        """2026-08-11 用于通过临时编号关闭案例（不产生任何语义变化，仅标记已解决）"""
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
        setup_id: str | None = None,
    ) -> str:
        """2026-08-11 用于把分析中发现的新连续性疑点创建为新案例登记进案例池
        （type 是任意描述字符串；description 只写人类可读说明且不超过 100 字，
        keys/type/dialogue_id/setup_id
        必须作为独立参数提交，示例：push_case(description="玉戒尺在第 5 章异常发光",
        keys=["玉戒尺"], type="伏笔疑点", setup_id="S-123")）"""
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
        json_marker_fields = ('"keys"', '"type"', '"dialogue_id"', '"setup_id"')
        if any(marker in normalized_description for marker in json_marker_fields):
            raise AnnotationInputError(
                "push_case.description 只接受人类可读说明；keys/type/dialogue_id/setup_id"
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
        if setup_id is not None:
            normalized_setup_id = unicodedata.normalize("NFC", setup_id).strip()
            if not query_service.thread_exists(normalized_setup_id):
                raise AnnotationInputError(f"push_case.setup_id 不是当前 run 的活跃伏笔线程: {normalized_setup_id}")
            target_ref["setup_id"] = normalized_setup_id
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
        response = {"accepted": True, "target_key": target_key}
        return json.dumps(response, ensure_ascii=False)

    return [
        write_metrics,
        write_entities,
        write_dialogues,
        write_event,
        write_relations,
        search_graph,
        search_text,
        search_event,
        search_pool,
        resolve_dialogue_case,
        resolve_fact_case,
        resolve_foreshadowing_case,
        close_case,
        push_case,
    ]


__all__ = [
    "AnnotationQueryService",
    "AnnotationToolLedger",
    "build_annotation_tools",
]
