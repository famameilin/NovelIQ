"""
章节标注 Agent 图原文案例伏笔工具与运行内审计
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from langchain_core.tools import tool

from .errors import AnnotationAuthorizationError, AnnotationInputError, AnnotationProtocolError
from .schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    CaseTargetAnchor,
    CaseType,
    ChapterFinish,
    ChapterFinishPatch,
    DialogueSpeakerResolution,
    EntityType,
    ForeshadowingSearchResult,
    GraphEvidence,
    GraphSearchResult,
    PulledResult,
    PullRequest,
    PullResult,
    PushCase,
    PushResult,
    SearchResult,
    StagedPushCase,
    TextEvidence,
    TextSearchResult,
)

_DIALOGUE_SPEAKER_META_KEYS = {"说话人", "speaker", "谁说的", "谁说出"}


class AnnotationQueryService(Protocol):
    """2026-08-07 用于隔离 Agent 只读图原文案例池查询与数据库实现"""

    def find_initial_case_candidates(
        self,
        current_text: str,
        *,
        semantic_limit: int = 50,
        rotation_limit: int = 50,
    ) -> tuple[list[CaseSearchResult], list[str]]:
        """2026-08-07 用于返回 current 相关案例候选和活动案例轮转 ID"""

    def search_pool(
        self,
        query: str,
        *,
        hidden_case_ids: set[str],
        limit: int = 50,
    ) -> SearchResult:
        """2026-08-07 用于检索案例与伏笔池"""

    def search_graph(self, query: str, *, limit: int = 50) -> GraphSearchResult | None:
        """2026-08-07 用于固定查询上一已完成章节图版本"""

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> list[TextSearchResult]:
        """2026-08-07 用于按范围联合定位原文候选"""

    def read_text(self, chunk_id: int) -> str:
        """2026-08-07 用于读取本轮文本搜索候选的完整原文"""

    def fetch_active_case_details(self, case_id: str) -> ActiveCaseDetails | None:
        """2026-08-07 用于回读单个活动案例及其内部稳定目标"""


@dataclass(slots=True)
class ToolAuditRecord:
    """2026-08-07 用于记录工具调用请求结果与阶段"""

    tool_name: str
    phase: str
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class AnnotationToolLedger:
    """2026-08-07 用于保存一次章节 Agent 尝试的授权状态和暂存结果"""

    current_chapter_id: int
    current_chunks: dict[int, str]
    allow_future_context: bool
    phase: str = "current_open"
    initial_cases: dict[str, CaseSearchResult] = field(default_factory=dict)
    rotation_case_ids: list[str] = field(default_factory=list)
    visible_case_ids: set[str] = field(default_factory=set)
    visible_setup_ids: set[str] = field(default_factory=set)
    visible_graph_entities: dict[int, EntityType] = field(default_factory=dict)
    visible_graph_fact_refs: set[tuple[str, int]] = field(default_factory=set)
    visible_graph_relation_ids: set[str] = field(default_factory=set)
    pulled_results: list[PulledResult] = field(default_factory=list)
    staged_push_cases: list[StagedPushCase] = field(default_factory=list)
    candidate_text_ranges: dict[int, str] = field(default_factory=dict)
    authorized_text_chunk_ids: set[int] = field(default_factory=set)
    audit_records: list[ToolAuditRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        """2026-08-07 用于把 current 输入登记为直接授权的 TextEvidence"""
        self.authorized_text_chunk_ids.update(self.current_chunks)

    @property
    def current_chunk_ids(self) -> tuple[int, ...]:
        """2026-08-07 用于按输入顺序返回 current chunk ID"""
        return tuple(self.current_chunks)

    @property
    def pulled_case_ids(self) -> set[str]:
        """2026-08-07 用于返回本轮已经提交解决结果的案例 ID"""
        return {result.case_id for result in self.pulled_results}

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于让工具权限与 LangGraph 当前阶段保持同步"""
        self.phase = phase

    def _register_evidence(self, evidence_items: Any) -> None:
        """2026-08-07 用于登记案例伏笔转交的根 Evidence 授权"""
        for evidence in evidence_items:
            if isinstance(evidence, GraphEvidence):
                self.visible_graph_fact_refs.add((evidence.fact_id, evidence.fact_revision))
            elif isinstance(evidence, TextEvidence):
                self.authorized_text_chunk_ids.add(evidence.chunk_id)

    def register_initial_cases(
        self,
        cases: list[CaseSearchResult],
        rotation_case_ids: list[str],
    ) -> None:
        """2026-08-07 用于登记第一次模型调用前可见的案例与根 Evidence"""
        self.initial_cases = {case.id: case for case in cases}
        self.rotation_case_ids = list(dict.fromkeys(rotation_case_ids))
        self.visible_case_ids.update(self.initial_cases)
        for case in cases:
            self._register_evidence(case.evidence)

    def register_pool_result(self, result: SearchResult) -> None:
        """2026-08-07 用于登记案例伏笔池搜索返回的可见对象和根 Evidence"""
        for item in result.results:
            if isinstance(item, CaseSearchResult):
                self.visible_case_ids.add(item.id)
            elif isinstance(item, ForeshadowingSearchResult):
                self.visible_setup_ids.add(item.record_id)
            self._register_evidence(item.evidence)

    def register_graph_result(self, result: GraphSearchResult) -> None:
        """2026-08-07 用于登记图搜索返回的事实关系和实体授权"""
        self.visible_graph_entities.update(
            {
                entity.existing_entity_id: entity.entity_type
                for entity in result.entities
            }
        )
        self.visible_graph_fact_refs.update(
            (fact.fact_id, fact.fact_revision)
            for fact in result.facts
        )
        self.visible_graph_relation_ids.update(relation.relation_id for relation in result.relations)

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
        """2026-08-07 用于生成完成事务可持久化的工具 Audit 结构"""
        return [asdict(record) for record in self.audit_records]


def _normalize_query(query: str, *, tool_name: str) -> str:
    """2026-08-07 用于统一校验查询工具输入长度与空白"""
    normalized = query.strip()
    if not normalized or len(normalized) > 2000:
        raise AnnotationInputError(f"{tool_name}.query 必须为 1 至 2000 个 Unicode 字符")
    return normalized


def _target_key(run_scope: str, case: PushCase) -> str:
    """2026-08-07 用于根据类型 chunk 和规范化关键词生成稳定案例目标键"""
    keys = "\x1f".join(sorted(case.keys))
    digest = hashlib.sha256(
        f"{run_scope}:{case.type}:{case.chunkid}:{keys}".encode()
    ).hexdigest()
    return digest


def _key_occurrences(text: str, key: str) -> list[int]:
    """2026-08-07 用于返回关键词在 current chunk 中的全部非重叠位置"""
    positions: list[int] = []
    start = 0
    while True:
        index = text.find(key, start)
        if index < 0:
            return positions
        positions.append(index)
        start = index + max(1, len(key))


def _locate_dialogue_speaker_anchor(case: PushCase, chunk_text: str) -> CaseTargetAnchor:
    """2026-08-07 用于从案例关键词定位唯一待确认对话文本锚点"""
    normalized_meta = {
        unicodedata.normalize("NFC", key).lower()
        for key in _DIALOGUE_SPEAKER_META_KEYS
    }
    content_keys = [
        key
        for key in sorted(case.keys, key=len, reverse=True)
        if key.lower() not in normalized_meta
    ]
    for key in content_keys:
        positions = _key_occurrences(chunk_text, key)
        if len(positions) == 1:
            start = positions[0]
            return CaseTargetAnchor(
                chunk_id=case.chunkid,
                start=start,
                end=start + len(key),
                text=key,
            )
    raise AnnotationInputError(
        "dialogue_speaker push 必须用 keys 在指定 current chunk 中定位唯一原文"
    )


def build_annotation_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
    *,
    run_scope: str,
) -> list[Any]:
    """2026-08-07 用于构建章节 Agent 的图原文案例与提交工具集"""

    @tool
    def search_graph(query: str) -> str:
        """2026-08-07 用于固定查询上一已完成章节图版本"""
        if ledger.phase not in {"current_open", "future_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_graph")
        normalized_query = _normalize_query(query, tool_name="search_graph")
        result = query_service.search_graph(normalized_query, limit=50)
        response = {"result": None} if result is None else result.model_dump(mode="json")
        if result is not None:
            ledger.register_graph_result(result)
        ledger.record(
            tool_name="search_graph",
            request={"query": normalized_query},
            response=response,
        )
        return "null" if result is None else result.model_dump_json()

    @tool
    async def search_text(query: str, range: Literal["previous", "future"]) -> str:
        """2026-08-07 用于关键词加 pgvector 定位授权范围内原文"""
        normalized_query = _normalize_query(query, tool_name="search_text")
        expected_range = "previous" if ledger.phase == "current_open" else "future"
        if ledger.phase not in {"current_open", "future_open"} or range != expected_range:
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
        for item in results:
            ledger.candidate_text_ranges[item.chunk_id] = range
        payload = [item.model_dump(mode="json") for item in results]
        ledger.record(
            tool_name="search_text",
            request={"query": normalized_query, "range": range},
            response={"results": payload},
        )
        return json.dumps(payload, ensure_ascii=False)

    @tool
    def read_text(chunk_id: int) -> str:
        """2026-08-07 用于读取本轮 search_text 命中的完整同 run 原文"""
        expected_range = "previous" if ledger.phase == "current_open" else "future"
        if ledger.phase not in {"current_open", "future_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 read_text")
        if ledger.candidate_text_ranges.get(chunk_id) != expected_range:
            raise AnnotationAuthorizationError(
                f"read_text 目标未由当前阶段 search_text 命中: chunk_id={chunk_id}"
            )
        content = query_service.read_text(chunk_id)
        ledger.authorized_text_chunk_ids.add(chunk_id)
        ledger.record(
            tool_name="read_text",
            request={"chunk_id": chunk_id},
            response={"content_chars": len(content)},
        )
        return content

    @tool
    def search_pool(query: str) -> str:
        """2026-08-07 用于检索活动案例与伏笔线程"""
        if ledger.phase not in {"current_open", "future_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 search_pool")
        normalized_query = _normalize_query(query, tool_name="search_pool")
        result = query_service.search_pool(
            normalized_query,
            hidden_case_ids=ledger.pulled_case_ids,
            limit=50,
        )
        ledger.register_pool_result(result)
        response = result.model_dump(mode="json")
        ledger.record(
            tool_name="search_pool",
            request={"query": normalized_query},
            response=response,
        )
        return result.model_dump_json()

    @tool
    def pull(
        case_id: str,
        type: Literal["dialogue_speaker"],
        resolution: DialogueSpeakerResolution,
    ) -> str:
        """2026-08-07 用于暂存单个已确认活动案例的严格解决结果"""
        if ledger.phase not in {"current_open", "future_open"}:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 pull")
        request = PullRequest(case_id=case_id, type=type, resolution=resolution)
        normalized_case_id = request.case_id.strip()
        if not normalized_case_id:
            raise AnnotationInputError("pull.case_id 不能为空")
        if normalized_case_id in ledger.pulled_case_ids:
            raise AnnotationInputError(f"案例已经被本轮 pull: {normalized_case_id}")
        if normalized_case_id not in ledger.visible_case_ids:
            raise AnnotationAuthorizationError(
                f"案例 ID 未由初始候选或本轮 search_pool 返回: {normalized_case_id}"
            )
        details = query_service.fetch_active_case_details(normalized_case_id)
        if details is None:
            raise AnnotationInputError(f"案例不存在或已不再 active: {normalized_case_id}")
        if details.type != request.type:
            raise AnnotationInputError(
                f"pull.type 与案例类型不一致: expected={details.type} actual={request.type}"
            )
        evidence_chunk_id = request.resolution.evidence_chunkid
        if evidence_chunk_id not in ledger.authorized_text_chunk_ids:
            raise AnnotationAuthorizationError(
                f"pull evidence_chunkid 未经 current 输入或 read_text 授权: {evidence_chunk_id}"
            )
        pulled = PulledResult(
            **request.model_dump(mode="python"),
            target_key=details.target_key,
            target_ref=details.target_ref,
        )
        ledger.pulled_results.append(pulled)
        result = PullResult(case_id=normalized_case_id)
        ledger.record(
            tool_name="pull",
            request=request.model_dump(mode="json"),
            response=result.model_dump(mode="json"),
        )
        return result.model_dump_json()

    @tool
    def push(
        description: str,
        keys: list[str],
        type: CaseType,
        chunkid: int,
    ) -> str:
        """2026-08-07 用于暂存当前章节新发现且仍未解决的单个案例"""
        allowed = (
            ledger.phase == "current_open" and not ledger.allow_future_context
        ) or (
            ledger.phase in {"future_open", "future_finalize"}
            and ledger.allow_future_context
        )
        if not allowed:
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 push")
        case = PushCase(
            description=description,
            keys=keys,
            type=type,
            chunkid=chunkid,
        )
        if case.chunkid not in ledger.current_chunks:
            raise AnnotationInputError(f"push.chunkid 必须属于 current: {case.chunkid}")
        if case.type != "dialogue_speaker":
            raise AnnotationInputError(f"尚未注册案例类型: {case.type}")
        target_anchor = _locate_dialogue_speaker_anchor(
            case,
            ledger.current_chunks[case.chunkid],
        )
        target_key = _target_key(run_scope, case)
        if any(item.target_key == target_key for item in ledger.staged_push_cases):
            raise AnnotationInputError(f"同一目标已经被本轮 push: {target_key}")
        staged = StagedPushCase(
            **case.model_dump(mode="python"),
            target_key=target_key,
            target_anchor=target_anchor,
        )
        ledger.staged_push_cases.append(staged)
        result = PushResult(target_key=target_key)
        ledger.record(
            tool_name="push",
            request=case.model_dump(mode="json"),
            response=result.model_dump(mode="json"),
        )
        return result.model_dump_json()

    @tool
    def finish(annotation: ChapterFinish) -> str:
        """2026-08-07 用于首次提交当前完整章节标注候选"""
        return "由 annotation 专用 LangGraph 校验"

    @tool
    def revise_finish(correction: ChapterFinishPatch) -> str:
        """2026-08-07 用于按 ref 局部修正当前完整章节标注候选"""
        return "由 annotation 专用 LangGraph 合并并校验"

    return [
        search_graph,
        search_text,
        read_text,
        search_pool,
        pull,
        push,
        finish,
        revise_finish,
    ]
