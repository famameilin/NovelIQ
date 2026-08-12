"""
章节标注语义写入工具与系统运行账本

核心合同: 每个 write_* 调用完成该领域的全部业务校验并写入当前候选 revision，
返回固定压缩回执 {accepted, tool, domain, revision, item_count, state_digest}。
完整参数、完整结果和历史 revision 只进入审计库，不回到模型上下文。
"""
from __future__ import annotations

import hashlib
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
    RELATION_DEFINITIONS,
    ActiveCaseDetails,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundChunkAnnotation,
    BoundDialogue,
    BoundEntity,
    BoundEntityDirectory,
    BoundEvent,
    BoundForeshadowing,
    BoundRelation,
    CaseSearchResult,
    CharacterObservationInput,
    ChunkMetricsInput,
    Confidence,
    DialogueCandidate,
    DialogueInput,
    DialogueSubmissionItem,
    DialogueVerdict,
    EmotionalValence,
    EntityDirectoryInput,
    EntityInput,
    EntityType,
    EventInput,
    ForeshadowingInput,
    NarrativeFunction,
    PayoffLikelihood,
    PendingCase,
    RelationChangeKind,
    RelationInput,
    ResolvedCase,
    SearchResult,
    SetupStatus,
    TextSearchResult,
    Tone,
    normalize_semantic_text,
)

_DOMAIN_NAMES = (
    "metrics",
    "entities",
    "character_observations",
    "dialogues",
    "events",
    "relations",
    "foreshadowings",
)
_DOMAIN_NAMES_SET = frozenset(_DOMAIN_NAMES)
_INTERNAL_GRAPH_KEYS = {
    "candidate_key",
    "chunk_id",
    "end",
    "fact_id",
    "fact_revision",
    "relation_id",
    "representative_entity_id",
    "start",
}


class AnnotationQueryService(Protocol):
    """2026-08-07 用于隔离 Agent 查询工具和数据库实现"""

    def find_initial_case_candidates(
        self,
        current_text: str,
        *,
        semantic_limit: int = 50,
        rotation_limit: int = 50,
    ) -> tuple[list[CaseSearchResult], list[str]]:
        """2026-08-07 用于返回章节相关活动案例和轮转 ID"""

    def search_pool(
        self,
        query: str,
        *,
        hidden_case_ids: set[str],
        limit: int = 50,
    ) -> SearchResult:
        """2026-08-07 用于检索活动案例与伏笔线程"""

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> list[TextSearchResult]:
        """2026-08-07 用于定位前文或后文原文候选"""

    def read_text(self, chunk_id: int) -> str:
        """2026-08-07 用于读取系统已登记的原文候选"""

    def fetch_active_case_details(self, case_id: str) -> ActiveCaseDetails | None:
        """2026-08-07 用于读取活动案例内部稳定目标"""

    def thread_exists(self, setup_id: str) -> bool:
        """2026-08-11 用于校验 push_case 携带的伏笔线程 id 属于当前 run 活跃线程"""


def _content_digest(value: Any) -> str:
    """2026-08-10 用于生成确定性内容摘要标识"""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


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
    domain_revision_counts: dict[str, int] = field(default_factory=dict)
    write_revisions: list[dict[str, Any]] = field(default_factory=list)
    completed_chunks: list[BoundChunkAnnotation] = field(default_factory=list)
    ready_chunk: BoundChunkAnnotation | None = None
    initial_cases: dict[str, CaseSearchResult] = field(default_factory=dict)
    rotation_case_ids: list[str] = field(default_factory=list)
    case_number_registry: dict[int, str] = field(default_factory=dict)
    case_number_by_id: dict[str, int] = field(default_factory=dict)
    text_result_registry: dict[int, TextSearchResult] = field(default_factory=dict)
    text_result_range: dict[int, str] = field(default_factory=dict)
    next_case_number: int = 1
    next_text_result_number: int = 1
    resolved_cases: list[ResolvedCase] = field(default_factory=list)
    pushed_cases: list[PendingCase] = field(default_factory=list)
    authorized_text_chunk_ids: set[int] = field(default_factory=set)
    # 2026-08-12 最近一次 write_dialogues 未提交候选序号（系统默认按 not_dialogue 处理）
    dialogue_missing_indexes: list[int] = field(default_factory=list)
    annotation: BoundChapterAnnotation | None = None
    errors: list[str] = field(default_factory=list)
    search_log: list[dict[str, Any]] = field(default_factory=list)
    graph_queried: bool = False
    graph: FactGraph | None = None

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
        """2026-08-07 用于返回本轮已经解决的真实案例 ID"""
        return {item.case_id for item in self.resolved_cases}

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于同步 LangGraph 和工具账本阶段"""
        self.phase = phase

    def snapshot(self) -> dict[str, Any]:
        """2026-08-10 用于在单个工具调用执行前保存可回滚账本状态"""
        return deepcopy(
            {
                "phase": self.phase,
                "domain_payloads": self.domain_payloads,
                "bound_payloads": self.bound_payloads,
                "domain_receipts": self.domain_receipts,
                "domain_revision_counts": self.domain_revision_counts,
                "write_revisions": self.write_revisions,
                "completed_chunks": self.completed_chunks,
                "ready_chunk": self.ready_chunk,
                "case_number_registry": self.case_number_registry,
                "case_number_by_id": self.case_number_by_id,
                "text_result_registry": self.text_result_registry,
                "text_result_range": self.text_result_range,
                "next_case_number": self.next_case_number,
                "next_text_result_number": self.next_text_result_number,
                "resolved_cases": self.resolved_cases,
                "pushed_cases": self.pushed_cases,
                "authorized_text_chunk_ids": self.authorized_text_chunk_ids,
                "dialogue_missing_indexes": self.dialogue_missing_indexes,
                "annotation": self.annotation,
                "search_log": self.search_log,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-10 用于在单个工具调用失败时恢复该调用开始前的账本状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

    def register_initial_cases(
        self,
        cases: list[CaseSearchResult],
        rotation_case_ids: list[str],
    ) -> None:
        """2026-08-12 用于登记初始案例并分配运行内临时编号（案例展示即授权其源 chunk）"""
        self.initial_cases = {case.id: case for case in cases}
        self.rotation_case_ids = list(dict.fromkeys(rotation_case_ids))
        for case in cases:
            self.register_case_number(case.id)
            self.authorized_text_chunk_ids.add(case.chunk_id)

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

    def initial_case_views(self) -> list[dict[str, Any]]:
        """2026-08-07 用于生成不暴露数据库 ID 的初始案例视图"""
        return [
            {
                "case_number": self.register_case_number(case.id),
                "type": case.type,
                "description": case.description,
                "keys": list(case.keys),
            }
            for case in self.initial_cases.values()
        ]

    # ------------------------------------------------------------------
    # 领域写入核心合同
    # ------------------------------------------------------------------

    def write_domain(self, domain: str, payload: Any, *, tool_name: str) -> dict[str, Any]:
        """2026-08-10 用于校验、绑定并完整替换当前 chunk 单个领域，成功即写入候选 revision"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许写入正式标注")
        if domain not in _DOMAIN_NAMES:
            raise AnnotationInputError(f"未知标注领域: {domain}")
        bound = self._bind_domain(domain, payload)
        relation_outcomes: list[dict[str, Any]] = []
        if self.graph is not None:
            if domain == "entities":
                self.graph.register_entities(list(payload.entities))
            elif domain == "relations":
                self.graph.reset_chapter_relations()
                for item in payload:
                    resolved_from = self.graph.resolve_name(item.from_entity)
                    resolved_to = self.graph.resolve_name(item.to_entity)
                    dumped = item.model_dump(mode="python")
                    dumped["from_entity"] = resolved_from
                    dumped["to_entity"] = resolved_to
                    added = self.graph.apply_relation(RelationInput(**dumped))
                    relation_outcomes.append(
                        {
                            "from": resolved_from,
                            "to": resolved_to,
                            "relation_type": str(item.relation_type),
                            "outcome": "assert" if added else "skipped_existing",
                        }
                    )
        chunk_id = self.current_chunk_id
        revision = self.domain_revision_counts.get(domain, 0) + 1
        self.domain_revision_counts[domain] = revision
        self.domain_payloads[domain] = payload
        self.bound_payloads[domain] = bound
        self.domain_receipts.add(domain)
        dumped = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else [item.model_dump(mode="json") for item in payload]
        )
        self.write_revisions.append(
            {
                "chunk_id": chunk_id,
                "domain": domain,
                "revision": revision,
                "payload": dumped,
            }
        )
        self._rebuild_ready_chunk_if_complete()
        return self._receipt(
            tool_name=tool_name,
            domain=domain,
            payload=payload,
            revision=revision,
            relation_outcomes=relation_outcomes or None,
        )

    def _receipt(
        self,
        *,
        tool_name: str,
        domain: str,
        payload: Any,
        revision: int,
        relation_outcomes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """2026-08-10 用于生成模型可见的固定压缩回执"""
        if domain == "metrics":
            item_count = 1
        elif domain == "entities":
            item_count = len(payload.entities)
        else:
            item_count = len(payload)
        dumped = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else [item.model_dump(mode="json") for item in payload]
        )
        receipt: dict[str, Any] = {
            "accepted": True,
            "tool": tool_name,
            "domain": domain,
            "revision": revision,
            "item_count": item_count,
            "state_digest": f"sha256:{_content_digest(dumped)}",
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
        catalog = (
            dict(self.graph.entity_types) if self.graph is not None else {}
        )
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

    def _require_entity_collected(
        self,
        name: str,
        *,
        entity_types: dict[str, EntityType],
        expected_types: tuple[EntityType, ...] | None = None,
        label: str,
        index: int,
    ) -> list[str]:
        """2026-08-11 用于收集式校验事实端点并返回带条目索引的错误文本"""
        key = unicodedata.normalize("NFC", name).strip().casefold()
        resolved_key = key
        if self.graph is not None:
            resolved_key = _norm_graph_name(self.graph.resolve_name(name))
        actual_type = entity_types.get(resolved_key) or entity_types.get(key)
        if actual_type is None:
            return [
                f"[{index}] {label} 未在当前 chunk 的 write_entities 中声明: {name}"
                "（请先在 write_entities 声明该实体，或改用已登记实体名）"
            ]
        if expected_types is not None and actual_type not in expected_types:
            return [
                f"[{index}] {label} 端点类型必须属于 {list(expected_types)}，"
                f"实际为 {actual_type}（该名称在图上的登记类型是 {actual_type}，"
                "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
            ]
        return []

    def _validate_domain_endpoints(
        self,
        domain: str,
        payload: Any,
        *,
        entity_types: dict[str, EntityType],
    ) -> None:
        """2026-08-11 用于在单个领域写入时收集式校验事实端点，一次返回全部错误"""
        errors: list[str] = []
        if domain == "character_observations":
            for index, item in enumerate(payload):
                errors.extend(
                    self._require_entity_collected(
                        item.character,
                        entity_types=entity_types,
                        expected_types=("character",),
                        label="character_observation.character",
                        index=index,
                    )
                )
        elif domain == "dialogues":
            for index, item in enumerate(payload):
                if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                    errors.extend(
                        self._require_entity_collected(
                            item.speaker,
                            entity_types=entity_types,
                            expected_types=("character",),
                            label="dialogue.speaker",
                            index=index,
                        )
                    )
        elif domain == "events":
            for index, item in enumerate(payload):
                for participant in item.participants:
                    expected: tuple[EntityType, ...] | None = (
                        ("location",)
                        if participant.role == "地点"
                        else None
                    )
                    errors.extend(
                        self._require_entity_collected(
                            participant.entity,
                            entity_types=entity_types,
                            expected_types=expected,
                            label="event.participant.entity",
                            index=index,
                        )
                    )
        elif domain == "relations":
            for index, item in enumerate(payload):
                definition = RELATION_DEFINITIONS[str(item.relation_type)]
                errors.extend(
                    self._require_entity_collected(
                        item.from_entity,
                        entity_types=entity_types,
                        expected_types=definition["from_types"],
                        label="relation.from_entity",
                        index=index,
                    )
                )
                errors.extend(
                    self._require_entity_collected(
                        item.to_entity,
                        entity_types=entity_types,
                        expected_types=definition["to_types"],
                        label="relation.to_entity",
                        index=index,
                    )
                )
        if errors:
            raise ValueError(f"{domain} 校验失败: " + "；".join(errors))

    def _validate_domain_duplicates(self, payloads: dict[str, Any]) -> None:
        """2026-08-07 用于拒绝当前 chunk 各领域的重复语义事实"""
        keys_by_domain: dict[str, list[tuple[Any, ...]]] = {
            "character_observations": [
                (item.character, item.action)
                for item in payloads["character_observations"]
            ],
            "events": [
                (
                    item.description,
                    tuple((part.entity, part.role) for part in item.participants),
                )
                for item in payloads["events"]
            ],
            "relations": [
                (
                    item.from_entity,
                    item.to_entity,
                    str(item.relation_type),
                )
                for item in payloads["relations"]
            ],
            "foreshadowings": [
                item.description for item in payloads["foreshadowings"]
            ],
        }
        errors: list[str] = []
        for domain, keys in keys_by_domain.items():
            seen: dict[tuple[Any, ...], list[int]] = {}
            for index, key in enumerate(keys):
                seen.setdefault(key, []).append(index)
            for _key, indexes in seen.items():
                if len(indexes) > 1:
                    errors.append(
                        f"[{', '.join(str(i) for i in indexes)}] {domain} 重复语义项"
                    )
        if errors:
            raise ValueError("；".join(errors))

    def _validate_fact_endpoints(
        self,
        payloads: dict[str, Any],
        *,
        entity_types: dict[str, EntityType],
    ) -> None:
        """2026-08-10 用于在 ready_chunk 构造时按最终实体目录全量校验事实端点"""
        self._validate_domain_endpoints(
            "character_observations",
            payloads["character_observations"],
            entity_types=entity_types,
        )
        self._validate_domain_endpoints(
            "dialogues",
            payloads["dialogues"],
            entity_types=entity_types,
        )
        self._validate_domain_endpoints(
            "events",
            payloads["events"],
            entity_types=entity_types,
        )
        self._validate_domain_endpoints(
            "relations",
            payloads["relations"],
            entity_types=entity_types,
        )

    def _bound_entities(
        self,
        directory: EntityDirectoryInput,
    ) -> BoundEntityDirectory:
        """2026-08-08 用于把当前 chunk 实体目录转换为系统绑定结果"""
        return BoundEntityDirectory(
            entities=[
                BoundEntity(**item.model_dump(mode="python"))
                for item in directory.entities
            ]
        )

    def _bind_domain(self, domain: str, payload: Any) -> Any:
        """2026-08-10 用于校验单个领域并构造系统绑定结果，校验失败直接抛出"""
        entity_types = self._fact_entity_catalog()
        self._validate_domain_endpoints(domain, payload, entity_types=entity_types)
        if domain == "metrics":
            return payload
        if domain == "entities":
            for entity in payload.entities:
                key = unicodedata.normalize("NFC", entity.name).strip().casefold()
                registered_type = (
                    self.graph.entity_types.get(key)
                    if self.graph is not None
                    else None
                )
                if registered_type is not None and registered_type != entity.entity_type:
                    raise ValueError(
                        f"已登记实体不允许变更大类: {entity.name} "
                        f"registered={registered_type} actual={entity.entity_type}（"
                        "同一词条的不同身份请使用区分性名称，如\"圣城\"是 location、"
                        "\"圣城朝堂\"是 organization，不要互相改类）"
                    )
            return self._bound_entities(payload)
        if domain == "character_observations":
            return [
                BoundCharacterObservation(**item.model_dump(mode="python"))
                for item in payload
            ]
        if domain == "dialogues":
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
                    raise ValueError(
                        f"write_dialogues.candidate_index 重复: {item.candidate_index}"
                    )
                seen_indexes.add(item.candidate_index)
            # 2026-08-12 软覆盖：未提交候选默认按 not_dialogue 处理（不再硬拒绝），
            # 缺失序号记入回执供模型补充提交
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
            return bound_dialogues
        if domain == "events":
            return [
                BoundEvent(**item.model_dump(mode="python"))
                for item in payload
            ]
        if domain == "relations":
            bound_relations: list[BoundRelation] = []
            for item in payload:
                resolved_from = (
                    self.graph.resolve_name(item.from_entity)
                    if self.graph is not None
                    else item.from_entity
                )
                resolved_to = (
                    self.graph.resolve_name(item.to_entity)
                    if self.graph is not None
                    else item.to_entity
                )
                dumped = item.model_dump(mode="python")
                dumped["from_entity"] = resolved_from
                dumped["to_entity"] = resolved_to
                bound_relations.append(
                    BoundRelation(
                        **dumped,
                        directionality=RELATION_DEFINITIONS[str(item.relation_type)][
                            "directionality"
                        ],
                        relation_semantics=RELATION_DEFINITIONS[str(item.relation_type)][
                            "semantics"
                        ],
                    )
                )
            return bound_relations
        if domain == "foreshadowings":
            return [
                BoundForeshadowing(**item.model_dump(mode="python"))
                for item in payload
            ]
        raise AnnotationInputError(f"未知标注领域: {domain}")

    # ------------------------------------------------------------------
    # ready_chunk 构造与冻结
    # ------------------------------------------------------------------

    def _rebuild_ready_chunk_if_complete(self) -> None:
        """2026-08-10 用于在第七个领域写入成功后同步构造并缓存 ready_chunk"""
        if not _DOMAIN_NAMES_SET <= self.domain_receipts:
            return
        self.ready_chunk = self._build_ready_chunk()

    def _build_ready_chunk(self) -> BoundChunkAnnotation:
        """2026-08-10 用于从全部已接受领域校验并构造完整 BoundChunkAnnotation"""
        payloads = self.domain_payloads
        entity_types, _entity_names = self._entity_catalog(payloads["entities"])
        resolved_entity_types = {
            **(self.graph.entity_types if self.graph is not None else {}),
            **entity_types,
        }
        self._validate_fact_endpoints(payloads, entity_types=resolved_entity_types)
        self._validate_domain_duplicates(payloads)
        bound_dialogues = list(self.bound_payloads["dialogues"])
        return BoundChunkAnnotation(
            chunk_id=self.current_chunk_id,
            metrics=payloads["metrics"],
            entities=self.bound_payloads["entities"],
            character_observations=list(self.bound_payloads["character_observations"]),
            dialogues=bound_dialogues,
            events=list(self.bound_payloads["events"]),
            relations=list(self.bound_payloads["relations"]),
            foreshadowings=list(self.bound_payloads["foreshadowings"]),
        )

    def complete_active_chunk(self) -> BoundChunkAnnotation:
        """2026-08-10 用于只检查阶段、七个 receipt 与 ready_chunk，然后冻结当前 chunk"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 complete_chunk")
        missing = [
            domain
            for domain in _DOMAIN_NAMES
            if domain not in self.domain_receipts
        ]
        if missing:
            raise ValueError(f"当前 chunk 尚未写入全部领域: {missing}")
        if self.ready_chunk is None:
            raise AnnotationInvariantError(
                "七个领域均已写入但 ready_chunk 缺失，系统不变量被破坏"
            )
        chunk = self.ready_chunk
        self.completed_chunks.append(chunk)
        self.authorized_text_chunk_ids.add(self.current_chunk_id)
        self.phase = "continuity_open"
        return chunk

    def finish(self) -> BoundChapterAnnotation:
        """2026-08-11 用于在 chunk 冻结后由系统用各 chunk summary 生成章节摘要并冻结章节"""
        if self.phase != "continuity_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish_chapter")
        annotation = BoundChapterAnnotation(
            chapter_summary="\n".join(
                chunk.metrics.summary for chunk in self.completed_chunks
            ),
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
                    "description": item.description,
                    "participants": [
                        {"entity": participant.entity, "role": str(participant.role)}
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
        if "foreshadowings" in payloads:
            views["foreshadowings"] = [
                {
                    "description": item.description,
                    "confidence": str(item.confidence),
                }
                for item in payloads["foreshadowings"]
            ]
        return views

    def context_summary(self) -> dict[str, Any]:
        """2026-08-10 用于从账本确定性生成当前模型请求的上下文摘要"""
        return {
            "phase": self.phase,
            "chunk_id": self.current_chunk_id,
            "revisions": {
                domain: {
                    "revision": self.domain_revision_counts.get(domain, 0),
                    "accepted": domain in self.domain_receipts,
                }
                for domain in _DOMAIN_NAMES
            },
            "missing_domains": [
                domain for domain in _DOMAIN_NAMES if domain not in self.domain_receipts
            ],
            "entities": {
                "declared": [
                    {"name": entity.name, "entity_type": entity.entity_type}
                    for entity in self.domain_payloads.get("entities", EntityDirectoryInput()).entities
                ],
                "registered": (
                    [
                        {"name": display_name, "entity_type": self.graph.entity_types[key]}
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
                ],
            },
            "text_results": [
                {
                    "result_number": number,
                    "range": self.text_result_range.get(number),
                    "excerpt": item.excerpt[:80],
                }
                for number, item in sorted(self.text_result_registry.items())
            ],
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


def _live_graph_response(
    graph: FactGraph,
    entities: list[str],
    *,
    relation_type: str | None,
    limit: int,
) -> dict[str, Any]:
    """2026-08-11 用于从常驻内存图回答节点邻域查询（运行时唯一图真相源）"""
    names_by_key = dict(graph.entity_names)
    types_by_key = dict(graph.entity_types)
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
                "name": display_name,
                "entity_type": types_by_key[resolved_key],
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
                "attributes": _semantic_graph_value(
                    dict(relation_attributes.get((from_key, to_key, rel_type)) or {})
                ),
            }
        )
        if from_key not in matched_keys:
            neighbor_keys.add(from_key)
        if to_key not in matched_keys:
            neighbor_keys.add(to_key)
    relations = relations[:limit]

    neighbors = [
        {
            "name": names_by_key[neighbor_key],
            "entity_type": types_by_key[neighbor_key],
            "tags": list(tags_by_key.get(neighbor_key) or []),
            "state": _semantic_graph_value(state_by_key[neighbor_key]),
        }
        for neighbor_key in sorted(neighbor_keys)
    ][:limit]

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
        emotional_valence: EmotionalValence,
        narrative_function: NarrativeFunction,
        pivot_moment: bool = False,
        cliffhanger: bool = False,
    ) -> str:
        """2026-08-11 用于完整替换当前 chunk 摘要和叙事指标，章节摘要由系统用各 chunk summary 自动生成"""
        payload = ChunkMetricsInput(
            summary=summary,
            emotional_valence=emotional_valence,
            narrative_function=narrative_function,
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
        )
        return json.dumps(
            ledger.write_domain("metrics", payload, tool_name="write_metrics"),
            ensure_ascii=False,
        )

    @tool
    def write_entities(entities: list[EntityInput]) -> str:
        """2026-08-08 用于完整替换当前 chunk 实体出现目录（单列表）"""
        if (
            ledger.graph is not None
            and ledger.graph.entity_types
            and not ledger.graph_queried
        ):
            raise AnnotationAuthorizationError(
                "提交 write_entities 前必须先调用 search_graph 查询已登记实体"
            )
        payload = EntityDirectoryInput(entities=entities)
        return json.dumps(
            ledger.write_domain("entities", payload, tool_name="write_entities"),
            ensure_ascii=False,
        )

    @tool
    def write_character_observations(items: list[CharacterObservationInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 人物动作观察"""
        return json.dumps(
            ledger.write_domain(
                "character_observations",
                items,
                tool_name="write_character_observations",
            ),
            ensure_ascii=False,
        )

    @tool
    def write_dialogues(items: list[DialogueSubmissionItem]) -> str:
        """2026-08-12 用于按系统候选序号提交对话三态判断（数组格式）
        （items 每条为 [candidate_index, verdict, speaker, tone]，speaker/tone 未知时 null；
        只提交 dialogue 与 inner_monologue 候选，未提交的候选系统默认按 not_dialogue
        处理，回执会列出被默认处理的候选序号，可再次调用补充）"""
        payload = [
            DialogueInput(
                candidate_index=index,
                verdict=verdict,
                speaker=speaker,
                tone=tone,
            )
            for (index, verdict, speaker, tone) in items
        ]
        return json.dumps(
            ledger.write_domain("dialogues", payload, tool_name="write_dialogues"),
            ensure_ascii=False,
        )

    @tool
    def write_events(items: list[EventInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 事件描述"""
        return json.dumps(
            ledger.write_domain("events", items, tool_name="write_events"),
            ensure_ascii=False,
        )

    @tool
    def write_relations(items: list[RelationInput]) -> str:
        """2026-08-12 用于完整替换当前 chunk 确认存在的闭合类型关系边
        （新边建图 assert，已存在的同一条边自动接受为 skipped_existing；
        强化/削弱/解除一律走 resolve_fact_case，不通过本工具表达变化）"""
        return json.dumps(
            ledger.write_domain("relations", items, tool_name="write_relations"),
            ensure_ascii=False,
        )

    @tool
    def write_foreshadowings(items: list[ForeshadowingInput]) -> str:
        """2026-08-11 用于提交当前 chunk 新埋设的伏笔（只创建新伏笔，强化和回收走 resolve_foreshadowing_case）"""
        return json.dumps(
            ledger.write_domain("foreshadowings", items, tool_name="write_foreshadowings"),
            ensure_ascii=False,
        )

    @tool
    def search_graph(entities: list[str], relation_type: str | None = None) -> str:
        """2026-08-09 用于按实体名查询图节点及与其相连的一跳邻域（边和邻居节点）"""
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_graph")
        if not entities:
            raise AnnotationInputError("search_graph.entities 不能为空")
        normalized_entities = [
            _normalize_query(entity, tool_name="search_graph") for entity in entities
        ]
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
                "digest": f"sha256:{_content_digest(response)}",
            }
        )
        return json.dumps(response, ensure_ascii=False)

    @tool
    async def search_text(query: str) -> str:
        """2026-08-07 用于返回运行内编号而不暴露真实 chunk ID（范围由当前阶段自动决定）"""
        normalized_query = _normalize_query(query, tool_name="search_text")
        expected_range = "previous" if ledger.phase == "chunk_open" else "future"
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationAuthorizationError(
                f"阶段 {ledger.phase} 不允许 search_text"
            )
        if expected_range == "future" and not ledger.allow_future_context:
            raise AnnotationAuthorizationError("allow_future_context=false 时禁止读取 future")
        results = await query_service.search_text(
            normalized_query,
            range_name=expected_range,
            limit=50,
        )
        views: list[dict[str, Any]] = []
        result_numbers: list[int] = []
        for item in results:
            result_number = ledger.next_text_result_number
            ledger.next_text_result_number += 1
            ledger.text_result_registry[result_number] = item
            ledger.text_result_range[result_number] = expected_range
            result_numbers.append(result_number)
            views.append(
                {
                    "result_number": result_number,
                    "excerpt": item.excerpt,
                    "keyword_score": item.keyword_score,
                    "semantic_score": item.semantic_score,
                }
            )
        ledger.append_search_log(
            {
                "tool": "search_text",
                "query": normalized_query,
                "hits": result_numbers,
                "digest": f"sha256:{_content_digest(views)}",
            }
        )
        return json.dumps(views, ensure_ascii=False)

    @tool
    def read_text(result_number: int) -> str:
        """2026-08-07 用于通过运行内编号读取真实原文"""
        item = ledger.text_result_registry.get(result_number)
        if item is None:
            raise AnnotationAuthorizationError(
                f"read_text.result_number 未由本轮 search_text 返回: {result_number}"
            )
        expected_range = "previous" if ledger.phase == "chunk_open" else "future"
        if ledger.text_result_range.get(result_number) != expected_range:
            raise AnnotationAuthorizationError(
                f"read_text.result_number 不属于当前 {expected_range} 阶段"
            )
        content = query_service.read_text(item.chunk_id)
        ledger.authorized_text_chunk_ids.add(item.chunk_id)
        return json.dumps({"content": content}, ensure_ascii=False)

    @tool
    def search_pool(query: str) -> str:
        """2026-08-07 用于返回临时案例编号和无 ID 伏笔语义"""
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_pool")
        normalized_query = _normalize_query(query, tool_name="search_pool")
        result = query_service.search_pool(
            normalized_query,
            hidden_case_ids=ledger.resolved_case_ids,
            limit=50,
        )
        views: list[dict[str, Any]] = []
        case_numbers: list[int] = []
        for item in result.results:
            if isinstance(item, CaseSearchResult):
                case_number = ledger.register_case_number(item.id)
                # 案例展示即授权其源 chunk，解决时不再因原文未读取被拒
                ledger.authorized_text_chunk_ids.add(item.chunk_id)
                case_numbers.append(case_number)
                views.append(
                    {
                        "result_kind": "case",
                        "case_number": case_number,
                        "type": item.type,
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
                "hits": case_numbers,
                "digest": f"sha256:{_content_digest(views)}",
            }
        )
        return json.dumps({"results": views}, ensure_ascii=False)

    def _resolve_case_details(
        *,
        ledger: AnnotationToolLedger,
        case_number: int,
        tool_name: str,
    ) -> ActiveCaseDetails:
        """2026-08-11 用于公共校验案例编号并回读活动案例稳定目标"""
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 {tool_name}")
        case_id = ledger.case_number_registry.get(case_number)
        if case_id is None:
            raise AnnotationAuthorizationError(
                f"case_number 未由初始候选或 search_pool 返回: {case_number}"
            )
        if case_id in ledger.resolved_case_ids:
            raise AnnotationInputError(f"case_number 已经解决: {case_number}")
        details = query_service.fetch_active_case_details(case_id)
        if details is None:
            raise AnnotationInputError(f"案例不存在或已不再 active: {case_number}")
        allowed_chunk_ids = ledger.authorized_text_chunk_ids | {ledger.current_chunk_id}
        if details.chunk_id not in allowed_chunk_ids:
            raise AnnotationAuthorizationError(
                f"案例 {details.id} 原文所在 chunk {details.chunk_id} 未经本轮读取授权，"
                "请先 search_text + read_text 读取原文后再解决"
            )
        return details

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
        speaker: str | None = None,
        tone: str | None = None,
        description: str | None = None,
        is_inner_monologue: bool | None = None,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为对话记录更新（至少提供一个更新字段）"""
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_dialogue_case",
        )
        if speaker is not None:
            _require_action_entity(
                ledger,
                speaker,
                expected_types=("character",),
                label="resolve_dialogue_case.speaker",
            )
        if tone is not None:
            tone = normalize_semantic_text(tone, label="resolve_dialogue_case.tone")
            if tone not in Tone:
                raise AnnotationInputError(
                    f"resolve_dialogue_case.tone 必须是闭合语气枚举: {tone}，"
                    f"合法值: {[member.value for member in Tone]}"
                )
        resolved_tone: Tone | None = Tone(tone) if tone is not None else None
        resolved = ResolvedCase(
            case_id=details.id,
            action="dialogue",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
            speaker=speaker,
            tone=resolved_tone,
            description=description,
            is_inner_monologue=is_inner_monologue,
        )
        return _append_resolved(ledger, details, resolved)

    @tool
    def resolve_fact_case(
        case_number: int,
        reason: str,
        from_entity: str,
        to_entity: str,
        relation_type: str,
        change_kind: str,
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为图关系建改删（change_kind 表达变化）"""
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_fact_case",
        )
        definition = RELATION_DEFINITIONS.get(relation_type)
        if definition is None:
            raise AnnotationInputError(
                f"resolve_fact_case.relation_type 必须是闭合关系类型: {relation_type}"
            )
        if change_kind not in RelationChangeKind:
            raise AnnotationInputError(
                f"resolve_fact_case.change_kind 必须是闭合关系变化类型: {change_kind}，"
                f"合法值: {[member.value for member in RelationChangeKind]}"
            )
        _require_action_entity(
            ledger,
            from_entity,
            expected_types=tuple(definition["from_types"]),
            label="resolve_fact_case.from_entity",
        )
        _require_action_entity(
            ledger,
            to_entity,
            expected_types=tuple(definition["to_types"]),
            label="resolve_fact_case.to_entity",
        )
        resolved = ResolvedCase(
            case_id=details.id,
            action="fact",
            type=details.type,
            reason=reason,
            target_key=details.target_key,
            target_ref=details.target_ref,
            from_entity=from_entity,
            to_entity=to_entity,
            relation_type=relation_type,
            change_kind=RelationChangeKind(change_kind),
        )
        return _append_resolved(ledger, details, resolved)

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
    ) -> str:
        """2026-08-11 用于通过临时编号把案例解决为伏笔线程字段更新（至少提供一个更新字段）"""
        details = _resolve_case_details(
            ledger=ledger,
            case_number=case_number,
            tool_name="resolve_foreshadowing_case",
        )
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
        （type 是任意描述字符串；description 只写人类可读说明，keys/type/dialogue_id/setup_id
        必须作为独立参数提交，示例：push_case(description="玉戒尺在第 5 章异常发光",
        keys=["玉戒尺"], type="伏笔疑点", setup_id="S-123")）"""
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 push_case")
        normalized_type = unicodedata.normalize("NFC", type).strip()
        if not normalized_type:
            raise AnnotationInputError("push_case.type 不能为空")
        normalized_description = unicodedata.normalize("NFC", description).strip()
        if not normalized_description:
            raise AnnotationInputError("push_case.description 不能为空")
        json_marker_fields = ('"keys"', '"type"', '"dialogue_id"', '"setup_id"')
        if any(marker in normalized_description for marker in json_marker_fields):
            raise AnnotationInputError(
                "push_case.description 只接受人类可读说明；keys/type/dialogue_id/setup_id"
                " 必须作为独立参数提交，不能写入 description 字符串"
            )
        normalized_keys = [
            unicodedata.normalize("NFC", key).strip() for key in keys
        ]
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
            candidate_keys = {
                candidate.candidate_key for candidate in ledger.dialogue_candidates
            }
            if normalized_dialogue_id not in candidate_keys:
                raise AnnotationInputError(
                    f"push_case.dialogue_id 不是当前 chunk 的对话候选 id: {normalized_dialogue_id}"
                )
            target_ref["dialogue_id"] = normalized_dialogue_id
        if setup_id is not None:
            normalized_setup_id = unicodedata.normalize("NFC", setup_id).strip()
            if not query_service.thread_exists(normalized_setup_id):
                raise AnnotationInputError(
                    f"push_case.setup_id 不是当前 run 的活跃伏笔线程: {normalized_setup_id}"
                )
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
        write_character_observations,
        write_dialogues,
        write_events,
        write_relations,
        write_foreshadowings,
        search_graph,
        search_text,
        read_text,
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