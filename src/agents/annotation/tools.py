"""
章节标注语义写入工具与系统运行账本
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from langchain_core.tools import tool

from .candidates import extract_dialogue_candidates
from .errors import AnnotationAuthorizationError, AnnotationInputError, AnnotationProtocolError
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
    BoundState,
    CaseSearchResult,
    CharacterObservationInput,
    ChunkMetricsInput,
    Confidence,
    DialogueCandidate,
    DialogueInput,
    EmotionalValence,
    EntityDirectoryInput,
    EntityInput,
    EntityType,
    EventInput,
    EvidenceList,
    ForeshadowingInput,
    GraphSearchResult,
    NarrativeFunction,
    PendingCase,
    RelationInput,
    ResolvedCase,
    SearchResult,
    StateInput,
    TextEvidence,
    TextSearchResult,
)

_DOMAIN_NAMES = (
    "metrics",
    "entities",
    "character_observations",
    "dialogues",
    "events",
    "relations",
    "states",
    "foreshadowings",
)
_INTERNAL_GRAPH_KEYS = {
    "candidate_key",
    "chunk_id",
    "end",
    "fact_id",
    "fact_revision",
    "relation_id",
    "representative_entity_id",
    "resolved_by_case_id",
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

    def search_graph(self, query: str, *, limit: int = 50) -> GraphSearchResult | None:
        """2026-08-07 用于查询上一已完成章节图版本"""

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


@dataclass(slots=True)
class ToolAuditRecord:
    """2026-08-07 用于记录真实工具请求结果和运行阶段"""

    tool_name: str
    phase: str
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None


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
    domain_receipts: set[str] = field(default_factory=set)
    domain_revision_counts: dict[str, int] = field(default_factory=dict)
    write_revisions: list[dict[str, Any]] = field(default_factory=list)
    completed_chunks: list[BoundChunkAnnotation] = field(default_factory=list)
    initial_cases: dict[str, CaseSearchResult] = field(default_factory=dict)
    rotation_case_ids: list[str] = field(default_factory=list)
    case_number_registry: dict[int, str] = field(default_factory=dict)
    case_number_by_id: dict[str, int] = field(default_factory=dict)
    text_result_registry: dict[int, TextSearchResult] = field(default_factory=dict)
    text_result_range: dict[int, str] = field(default_factory=dict)
    next_case_number: int = 1
    next_text_result_number: int = 1
    resolved_cases: list[ResolvedCase] = field(default_factory=list)
    pending_cases: list[PendingCase] = field(default_factory=list)
    authorized_text_chunk_ids: set[int] = field(default_factory=set)
    last_evidence_chunk_id: int | None = None
    annotation: BoundChapterAnnotation | None = None
    audit_records: list[ToolAuditRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        """2026-08-07 用于初始化唯一 chunk 的对话候选"""
        if not self.current_chunk_text.strip():
            raise AnnotationInputError("current_chunk_text 不能为空")
        self.dialogue_candidates = extract_dialogue_candidates(
            self.current_chunk_id,
            self.current_chunk_text,
        )
        self.last_evidence_chunk_id = self.current_chunk_id

    @property
    def resolved_case_ids(self) -> set[str]:
        """2026-08-07 用于返回本轮已经解决的真实案例 ID"""
        return {item.case_id for item in self.resolved_cases}

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于同步 LangGraph 和工具账本阶段"""
        self.phase = phase

    def snapshot(self) -> dict[str, Any]:
        """2026-08-07 用于在工具批次执行前保存可回滚账本状态"""
        return deepcopy(
            {
                "phase": self.phase,
                "domain_payloads": self.domain_payloads,
                "domain_receipts": self.domain_receipts,
                "domain_revision_counts": self.domain_revision_counts,
                "write_revisions": self.write_revisions,
                "completed_chunks": self.completed_chunks,
                "case_number_registry": self.case_number_registry,
                "case_number_by_id": self.case_number_by_id,
                "text_result_registry": self.text_result_registry,
                "text_result_range": self.text_result_range,
                "next_case_number": self.next_case_number,
                "next_text_result_number": self.next_text_result_number,
                "resolved_cases": self.resolved_cases,
                "pending_cases": self.pending_cases,
                "authorized_text_chunk_ids": self.authorized_text_chunk_ids,
                "last_evidence_chunk_id": self.last_evidence_chunk_id,
                "annotation": self.annotation,
                "audit_records": self.audit_records,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-07 用于在工具批次失败时恢复全部系统暂存状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

    def record(
        self,
        *,
        tool_name: str,
        request: dict[str, Any],
        response: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """2026-08-07 用于按真实调用顺序追加工具审计"""
        self.audit_records.append(
            ToolAuditRecord(
                tool_name=tool_name,
                phase=self.phase,
                request=request,
                response=response,
                error=error,
            )
        )

    def audit_payload(self) -> list[dict[str, Any]]:
        """2026-08-07 用于生成可持久化工具审计结构"""
        return [asdict(record) for record in self.audit_records]

    def register_initial_cases(
        self,
        cases: list[CaseSearchResult],
        rotation_case_ids: list[str],
    ) -> None:
        """2026-08-07 用于登记初始案例并分配运行内临时编号"""
        self.initial_cases = {case.id: case for case in cases}
        self.rotation_case_ids = list(dict.fromkeys(rotation_case_ids))
        for case in cases:
            self.register_case_number(case.id)

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

    def write_domain(self, domain: str, payload: Any) -> dict[str, Any]:
        """2026-08-07 用于完整替换当前 chunk 单个领域暂存值"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许写入正式标注")
        if domain not in _DOMAIN_NAMES:
            raise AnnotationInputError(f"未知标注领域: {domain}")
        chunk_id = self.current_chunk_id
        revision = self.domain_revision_counts.get(domain, 0) + 1
        self.domain_revision_counts[domain] = revision
        self.domain_payloads[domain] = payload
        self.domain_receipts.add(domain)
        dumped = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in payload
            ]
        )
        self.write_revisions.append(
            {
                "chunk_id": chunk_id,
                "domain": domain,
                "revision": revision,
                "payload": dumped,
            }
        )
        return {"accepted": True, "domain": domain, "revision": revision}

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

    def _require_entity(
        self,
        name: str,
        *,
        entity_types: dict[str, EntityType],
        expected_types: tuple[EntityType, ...] | None = None,
        label: str,
    ) -> str:
        """2026-08-07 用于校验事实端点已经由当前 chunk 实体目录声明"""
        key = unicodedata.normalize("NFC", name).strip().casefold()
        actual_type = entity_types.get(key)
        if actual_type is None:
            raise ValueError(f"{label} 未在当前 chunk 的 write_entities 中声明: {name}")
        if expected_types is not None and actual_type not in expected_types:
            raise ValueError(
                f"{label} 端点类型必须属于 {list(expected_types)}，实际为 {actual_type}"
            )
        return key

    def _validate_fact_endpoints(
        self,
        payloads: dict[str, Any],
        *,
        entity_types: dict[str, EntityType],
    ) -> None:
        """2026-08-07 用于校验当前 chunk 全部事实端点和闭合关系约束"""
        for item in payloads["character_observations"]:
            self._require_entity(
                item.character,
                entity_types=entity_types,
                expected_types=("character",),
                label="character_observation.character",
            )
        for item in payloads["dialogues"]:
            if item.is_dialogue and item.speaker is not None:
                self._require_entity(
                    item.speaker,
                    entity_types=entity_types,
                    expected_types=("character",),
                    label="dialogue.speaker",
                )
        for item in payloads["events"]:
            for participant in item.participants:
                self._require_entity(
                    participant.entity,
                    entity_types=entity_types,
                    label="event.participant.entity",
                )
            if item.location is not None:
                self._require_entity(
                    item.location,
                    entity_types=entity_types,
                    expected_types=("location",),
                    label="event.location",
                )
        for item in payloads["relations"]:
            definition = RELATION_DEFINITIONS[str(item.relation_type)]
            self._require_entity(
                item.from_entity,
                entity_types=entity_types,
                expected_types=definition["from_types"],
                label="relation.from_entity",
            )
            self._require_entity(
                item.to_entity,
                entity_types=entity_types,
                expected_types=definition["to_types"],
                label="relation.to_entity",
            )
        for item in payloads["states"]:
            self._require_entity(
                item.entity,
                entity_types=entity_types,
                label="state.entity",
            )
            if item.object is not None:
                self._require_entity(
                    item.object,
                    entity_types=entity_types,
                    label="state.object",
                )

    def _validate_domain_duplicates(self, payloads: dict[str, Any]) -> None:
        """2026-08-07 用于拒绝当前 chunk 各领域的重复语义事实"""
        keys_by_domain: dict[str, list[tuple[Any, ...]]] = {
            "character_observations": [
                (item.character, item.action, str(item.action_type))
                for item in payloads["character_observations"]
            ],
            "events": [
                (
                    item.description,
                    tuple((part.entity, part.participation) for part in item.participants),
                    item.location,
                )
                for item in payloads["events"]
            ],
            "relations": [
                (
                    item.from_entity,
                    item.to_entity,
                    str(item.relation_type),
                    str(item.change_kind),
                )
                for item in payloads["relations"]
            ],
            "states": [
                (
                    item.entity,
                    item.predicate,
                    item.object,
                    json.dumps(item.value, ensure_ascii=False, sort_keys=True),
                    str(item.assertion),
                )
                for item in payloads["states"]
            ],
            "foreshadowings": [
                (
                    item.setup_summary,
                    str(item.setup_kind),
                    item.expected_payoff_family,
                )
                for item in payloads["foreshadowings"]
            ],
        }
        for domain, keys in keys_by_domain.items():
            if len(set(keys)) != len(keys):
                raise ValueError(f"当前 chunk 的 {domain} 存在重复语义项")

    def _evidence(self, reason: str, chunk_id: int) -> EvidenceList:
        """2026-08-07 用于把 Agent 理由绑定为当前 chunk 系统文本依据"""
        return EvidenceList.model_validate(
            [TextEvidence(reason=reason, chunk_id=chunk_id)]
        )

    def _bound_entities(
        self,
        directory: EntityDirectoryInput,
        *,
        chunk_id: int,
    ) -> BoundEntityDirectory:
        """2026-08-08 用于给当前 chunk 实体目录注入系统文本依据"""
        return BoundEntityDirectory(
            entities=[
                BoundEntity(
                    **item.model_dump(mode="python"),
                    evidence=self._evidence(item.reason, chunk_id),
                )
                for item in directory.entities
            ]
        )

    def _pending_case(
        self,
        dialogue: BoundDialogue,
        *,
        chunk_id: int,
    ) -> PendingCase:
        """2026-08-07 用于从 speaker 为空的系统对话自动构造连续性案例"""
        content_hash = hashlib.sha256(dialogue.content.encode("utf-8")).hexdigest()
        target_key = hashlib.sha256(
            (
                f"{self.run_scope}:dialogue:{chunk_id}:{dialogue.start}:"
                f"{dialogue.end}:{content_hash}"
            ).encode()
        ).hexdigest()
        return PendingCase(
            chunk_id=chunk_id,
            keys=[dialogue.content, "说话人"],
            description=f"确认对话“{dialogue.content[:40]}”的说话人",
            target_key=target_key,
            target_ref={
                "kind": "dialogue",
                "candidate_key": dialogue.candidate_key,
                "chunk_id": chunk_id,
                "start": dialogue.start,
                "end": dialogue.end,
                "text": dialogue.content,
            },
            evidence=dialogue.evidence,
        )

    def complete_active_chunk(self) -> BoundChunkAnnotation:
        """2026-08-07 用于校验八个领域并冻结当前 chunk 正式标注"""
        if self.phase != "chunk_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 complete_chunk")
        chunk_id = self.current_chunk_id
        missing = [
            domain
            for domain in _DOMAIN_NAMES
            if domain not in self.domain_receipts
        ]
        if missing:
            raise ValueError(f"当前 chunk 尚未写入全部领域: {missing}")
        payloads = self.domain_payloads
        candidates = self.dialogue_candidates
        dialogue_inputs: list[DialogueInput] = payloads["dialogues"]
        if len(dialogue_inputs) != len(candidates):
            raise ValueError(
                "write_dialogues 必须按系统候选顺序逐项提交: "
                f"expected={len(candidates)} actual={len(dialogue_inputs)}"
            )
        entity_types, _entity_names = self._entity_catalog(payloads["entities"])
        self._validate_fact_endpoints(payloads, entity_types=entity_types)
        self._validate_domain_duplicates(payloads)

        bound_dialogues: list[BoundDialogue] = []
        for candidate, item in zip(candidates, dialogue_inputs, strict=True):
            if not item.is_dialogue:
                continue
            dialogue = BoundDialogue(
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                description=str(item.description),
                speaker=item.speaker,
                tone=item.tone,
                is_inner_monologue=item.is_inner_monologue,
                confidence=item.confidence,
                reason=item.reason,
                evidence=self._evidence(item.reason, chunk_id),
            )
            bound_dialogues.append(dialogue)
            if dialogue.speaker is None:
                pending = self._pending_case(dialogue, chunk_id=chunk_id)
                if not any(item.target_key == pending.target_key for item in self.pending_cases):
                    self.pending_cases.append(pending)

        metrics: ChunkMetricsInput = payloads["metrics"]
        chunk = BoundChunkAnnotation(
            chunk_id=chunk_id,
            metrics=metrics,
            entities=self._bound_entities(payloads["entities"], chunk_id=chunk_id),
            character_observations=[
                BoundCharacterObservation(
                    **item.model_dump(mode="python"),
                    evidence=self._evidence(item.reason, chunk_id),
                )
                for item in payloads["character_observations"]
            ],
            dialogues=bound_dialogues,
            events=[
                BoundEvent(
                    **item.model_dump(mode="python"),
                    evidence=self._evidence(item.reason, chunk_id),
                )
                for item in payloads["events"]
            ],
            relations=[
                BoundRelation(
                    **item.model_dump(mode="python"),
                    directionality=RELATION_DEFINITIONS[str(item.relation_type)][
                        "directionality"
                    ],
                    relation_semantics=RELATION_DEFINITIONS[str(item.relation_type)][
                        "semantics"
                    ],
                    evidence=self._evidence(item.reason, chunk_id),
                )
                for item in payloads["relations"]
            ],
            states=[
                BoundState(
                    **item.model_dump(mode="python"),
                    evidence=self._evidence(item.reason, chunk_id),
                )
                for item in payloads["states"]
            ],
            foreshadowings=[
                BoundForeshadowing(
                    **item.model_dump(mode="python"),
                    evidence=self._evidence(item.reason, chunk_id),
                )
                for item in payloads["foreshadowings"]
            ],
        )
        self.completed_chunks.append(chunk)
        self.authorized_text_chunk_ids.add(chunk_id)
        self.last_evidence_chunk_id = chunk_id
        self.phase = "continuity_open"
        return chunk

    def finish(self, chapter_summary: str) -> BoundChapterAnnotation:
        """2026-08-07 用于在 chunk 冻结后生成章节正式标注"""
        if self.phase != "continuity_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish_chapter")
        annotation = BoundChapterAnnotation(
            chapter_summary=chapter_summary,
            chunks=list(self.completed_chunks),
        )
        self.annotation = annotation
        self.phase = "completed"
        return annotation


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
        confidence: Confidence,
        reason: str,
        pivot_moment: bool = False,
        cliffhanger: bool = False,
    ) -> str:
        """2026-08-07 用于完整替换当前 chunk 摘要和叙事指标"""
        payload = ChunkMetricsInput(
            summary=summary,
            emotional_valence=emotional_valence,
            narrative_function=narrative_function,
            confidence=confidence,
            reason=reason,
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
        )
        result = ledger.write_domain("metrics", payload)
        ledger.record(
            tool_name="write_metrics",
            request=payload.model_dump(mode="json"),
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_entities(entities: list[EntityInput]) -> str:
        """2026-08-08 用于完整替换当前 chunk 实体出现目录（单列表）"""
        payload = EntityDirectoryInput(entities=entities)
        result = ledger.write_domain("entities", payload)
        ledger.record(
            tool_name="write_entities",
            request=payload.model_dump(mode="json"),
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_character_observations(items: list[CharacterObservationInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 人物动作观察"""
        result = ledger.write_domain("character_observations", items)
        ledger.record(
            tool_name="write_character_observations",
            request={"items": [item.model_dump(mode="json") for item in items]},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_dialogues(items: list[DialogueInput]) -> str:
        """2026-08-07 用于按系统候选顺序完整替换当前 chunk 对话判断"""
        result = ledger.write_domain("dialogues", items)
        ledger.record(
            tool_name="write_dialogues",
            request={"items": [item.model_dump(mode="json") for item in items]},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_events(items: list[EventInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 事件描述"""
        result = ledger.write_domain("events", items)
        ledger.record(
            tool_name="write_events",
            request={"items": [item.model_dump(mode="json") for item in items]},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_relations(items: list[RelationInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 闭合类型关系变化"""
        result = ledger.write_domain("relations", items)
        ledger.record(
            tool_name="write_relations",
            request={"items": [item.model_dump(mode="json") for item in items]},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_states(items: list[StateInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 实体状态"""
        result = ledger.write_domain("states", items)
        ledger.record(
            tool_name="write_states",
            request={"items": [item.model_dump(mode="json") for item in items]},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def write_foreshadowings(items: list[ForeshadowingInput]) -> str:
        """2026-08-07 用于完整替换当前 chunk 伏笔语义"""
        result = ledger.write_domain("foreshadowings", items)
        ledger.record(
            tool_name="write_foreshadowings",
            request={"items": [item.model_dump(mode="json") for item in items]},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def complete_chunk() -> str:
        """2026-08-07 用于校验冻结当前 chunk 并进入连续性阶段"""
        chunk = ledger.complete_active_chunk()
        result = {
            "accepted": True,
            "completed_chunk": chunk.chunk_id,
        }
        ledger.record(tool_name="complete_chunk", request={}, response=result)
        return json.dumps(result, ensure_ascii=False)

    @tool
    def finish_chapter(chapter_summary: str) -> str:
        """2026-08-07 用于完成全部正式 chunk 和连续性操作"""
        annotation = ledger.finish(chapter_summary)
        result = {
            "accepted": True,
            "contract_version": annotation.contract_version,
            "chunk_count": len(annotation.chunks),
        }
        ledger.record(
            tool_name="finish_chapter",
            request={"chapter_summary": chapter_summary},
            response=result,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    def search_graph(query: str) -> str:
        """2026-08-07 用于返回不含数据库 ID 的前序图语义视图"""
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_graph")
        normalized_query = _normalize_query(query, tool_name="search_graph")
        result = query_service.search_graph(normalized_query, limit=50)
        if result is None:
            response: dict[str, Any] = {"entities": [], "facts": [], "relations": []}
        else:
            response = {
                "entities": [
                    {
                        "name": item.name,
                        "entity_type": item.entity_type,
                        "state": _semantic_graph_value(item.state),
                    }
                    for item in result.entities
                ],
                "facts": [
                    {
                        "fact_type": item.fact_type,
                        "predicate": item.predicate,
                        "content": _semantic_graph_value(item.content),
                    }
                    for item in result.facts
                ],
                "relations": [
                    {
                        "from_name": item.from_name,
                        "to_name": item.to_name,
                        "relation_type": item.relation_type,
                        "is_active": item.is_active,
                        "attributes": _semantic_graph_value(item.attributes),
                    }
                    for item in result.relations
                ],
            }
        ledger.record(
            tool_name="search_graph",
            request={"query": normalized_query},
            response=response,
        )
        return json.dumps(response, ensure_ascii=False)

    @tool
    async def search_text(query: str, range: Literal["previous", "future"]) -> str:
        """2026-08-07 用于返回运行内编号而不暴露真实 chunk ID"""
        normalized_query = _normalize_query(query, tool_name="search_text")
        expected_range = "previous" if ledger.phase == "chunk_open" else "future"
        if ledger.phase not in {"chunk_open", "continuity_open"} or range != expected_range:
            raise AnnotationAuthorizationError(
                f"阶段 {ledger.phase} 的 search_text.range 必须为 {expected_range}"
            )
        if range == "future" and not ledger.allow_future_context:
            raise AnnotationAuthorizationError("allow_future_context=false 时禁止读取 future")
        results = await query_service.search_text(
            normalized_query,
            range_name=range,
            limit=50,
        )
        views: list[dict[str, Any]] = []
        for item in results:
            result_number = ledger.next_text_result_number
            ledger.next_text_result_number += 1
            ledger.text_result_registry[result_number] = item
            ledger.text_result_range[result_number] = range
            views.append(
                {
                    "result_number": result_number,
                    "excerpt": item.excerpt,
                    "keyword_score": item.keyword_score,
                    "semantic_score": item.semantic_score,
                }
            )
        ledger.record(
            tool_name="search_text",
            request={"query": normalized_query, "range": range},
            response={"results": views},
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
        ledger.last_evidence_chunk_id = item.chunk_id
        ledger.record(
            tool_name="read_text",
            request={"result_number": result_number},
            response={"content_chars": len(content)},
        )
        return content

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
        for item in result.results:
            if isinstance(item, CaseSearchResult):
                views.append(
                    {
                        "result_kind": "case",
                        "case_number": ledger.register_case_number(item.id),
                        "type": item.type,
                        "description": item.description,
                        "keys": list(item.keys),
                    }
                )
            else:
                views.append(
                    {
                        "result_kind": "foreshadowing",
                        "content": item.content,
                    }
                )
        ledger.record(
            tool_name="search_pool",
            request={"query": normalized_query},
            response={"results": views},
        )
        return json.dumps({"results": views}, ensure_ascii=False)

    @tool
    def resolve_case(case_number: int, speaker: str, reason: str) -> str:
        """2026-08-07 用于通过临时编号解决活动对话说话人案例"""
        if ledger.phase not in {"chunk_open", "continuity_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 resolve_case")
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
        evidence_chunk_id = ledger.last_evidence_chunk_id
        if evidence_chunk_id is None:
            raise AnnotationAuthorizationError("当前没有可用于案例解决的系统原文")
        resolved = ResolvedCase(
            case_id=case_id,
            type=details.type,
            speaker=speaker,
            reason=reason,
            evidence_chunk_id=evidence_chunk_id,
            target_key=details.target_key,
            target_ref=details.target_ref,
        )
        ledger.resolved_cases.append(resolved)
        response = {"accepted": True, "case_number": case_number}
        ledger.record(
            tool_name="resolve_case",
            request={
                "case_number": case_number,
                "speaker": speaker,
                "reason": reason,
            },
            response=response,
        )
        return json.dumps(response, ensure_ascii=False)

    return [
        write_metrics,
        write_entities,
        write_character_observations,
        write_dialogues,
        write_events,
        write_relations,
        write_states,
        write_foreshadowings,
        complete_chunk,
        finish_chapter,
        search_graph,
        search_text,
        read_text,
        search_pool,
        resolve_case,
    ]


__all__ = [
    "AnnotationQueryService",
    "AnnotationToolLedger",
    "ToolAuditRecord",
    "build_annotation_tools",
]
