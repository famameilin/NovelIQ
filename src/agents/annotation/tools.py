"""
章节标注 Agent 工具与运行内账本
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from langchain_core.tools import tool

from .errors import AnnotationAuthorizationError, AnnotationInputError, AnnotationProtocolError
from .schema import (
    AfterChunkSearchResult,
    CaseSearchResult,
    ChapterAnnotation,
    ChapterAnnotationPatch,
    FactPushOutput,
    ForeshadowingPushOutput,
    ForeshadowingSearchResult,
    GraphSearchResult,
    PullResult,
    PushOutput,
    PushRequest,
    PushResult,
    SearchResult,
)


class AnnotationQueryService(Protocol):
    """2026-08-05 用于隔离 Agent 只读检索与具体数据库实现"""

    def find_initial_case_candidates(
        self,
        current_text: str,
        *,
        semantic_limit: int = 50,
        rotation_limit: int = 50,
    ) -> tuple[list[CaseSearchResult], list[str]]:
        """2026-08-05 用于返回 current 语义候选和活动案例轮转 ID"""

    def search_continuity(
        self,
        query: str,
        *,
        hidden_case_ids: set[str],
        limit: int = 50,
    ) -> SearchResult:
        """2026-08-05 用于同时检索案例图事实与伏笔线程"""

    def fetch_active_cases(self, ids: list[str]) -> list[CaseSearchResult]:
        """2026-08-05 用于按真实案例 ID 回读当前活动案例"""

    def search_after(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> list[AfterChunkSearchResult]:
        """2026-08-06 用于检索当前位置之后的后文 chunk"""

    def read_after_chunk(
        self,
        *,
        chapter_id: int,
        chunk_id: int,
    ) -> str:
        """2026-08-06 用于读取本轮 search 已授权的完整后文 chunk"""


@dataclass(slots=True)
class ToolAuditRecord:
    """2026-08-05 用于记录工具调用请求结果与阶段"""

    tool_name: str
    phase: str
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class AnnotationToolLedger:
    """2026-08-05 用于保存一次 LangGraph 尝试的全部运行内业务状态"""

    current_chapter_id: int
    current_chunk_ids: tuple[int, ...]
    initial_cases: dict[str, CaseSearchResult] = field(default_factory=dict)
    rotation_case_ids: list[str] = field(default_factory=list)
    visible_case_ids: set[str] = field(default_factory=set)
    visible_setup_ids: set[str] = field(default_factory=set)
    visible_graph_entity_node_ids: set[str] = field(default_factory=set)
    visible_evidence_chapter_ids: set[int] = field(default_factory=set)
    pulled_case_ids: list[str] = field(default_factory=list)
    staged_outputs: list[PushOutput] = field(default_factory=list)
    authorized_after_chunks: set[tuple[int, int]] = field(default_factory=set)
    audit_records: list[ToolAuditRecord] = field(default_factory=list)
    frozen: bool = False

    def register_initial_cases(
        self,
        cases: list[CaseSearchResult],
        rotation_case_ids: list[str],
    ) -> None:
        """2026-08-05 用于登记第一次模型调用前可见的案例候选"""
        self.initial_cases = {case.id: case for case in cases}
        self.rotation_case_ids = list(dict.fromkeys(rotation_case_ids))
        self.visible_case_ids.update(self.initial_cases)
        self.visible_evidence_chapter_ids.update(case.evidence.chapterid for case in cases)

    def record(
        self,
        *,
        tool_name: str,
        phase: str,
        request: dict[str, Any],
        response: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """2026-08-05 用于按真实调用顺序追加工具审计"""
        self.audit_records.append(
            ToolAuditRecord(
                tool_name=tool_name,
                phase=phase,
                request=request,
                response=response,
                error=error,
            )
        )

    def freeze_business_results(self) -> None:
        """2026-08-05 用于在首次有效 finish 后冻结案例与事实候选"""
        self.validate_staged_outputs()
        self.frozen = True

    def validate_staged_outputs(self) -> None:
        """2026-08-05 用于校验 pull 覆盖来源归属与 rejected 排他"""
        pulled = set(self.pulled_case_ids)
        covered: set[str] = set()
        rejected: set[str] = set()
        non_rejected: set[str] = set()
        for output in self.staged_outputs:
            source_ids = set(output.source_case_ids)
            if not source_ids.issubset(pulled):
                unknown = sorted(source_ids - pulled)
                raise AnnotationInputError(f"push 引用了本轮未 pull 的案例: {unknown}")
            covered.update(source_ids)
            if output.output_kind == "rejected":
                rejected.update(source_ids)
            else:
                non_rejected.update(source_ids)
        missing = sorted(pulled - covered)
        if missing:
            raise ValueError(f"pulled 案例未被任何 push 输出覆盖: {missing}")
        conflicts = sorted(rejected & non_rejected)
        if conflicts:
            raise ValueError(f"同一来源案例同时进入 rejected 与非 rejected 输出: {conflicts}")

    def audit_payload(self) -> list[dict[str, Any]]:
        """2026-08-05 用于生成完成事务可持久化的工具审计结构"""
        return [asdict(record) for record in self.audit_records]


def _register_search_visibility(ledger: AnnotationToolLedger, result: SearchResult) -> None:
    """2026-08-05 用于把连续性检索结果登记为本轮可引用对象"""
    for item in result.results:
        if isinstance(item, CaseSearchResult):
            ledger.visible_case_ids.add(item.id)
        elif isinstance(item, ForeshadowingSearchResult):
            ledger.visible_setup_ids.add(item.record_id)
        elif isinstance(item, GraphSearchResult):
            ledger.visible_graph_entity_node_ids.update(
                node.node_id
                for node in item.matched_nodes
                if node.node_kind == "entity"
            )
        evidence = getattr(item, "evidence", None)
        if evidence is not None:
            ledger.visible_evidence_chapter_ids.add(evidence.chapterid)


def _validate_output_visibility(output: PushOutput, ledger: AnnotationToolLedger) -> None:
    """2026-08-05 用于校验 push Evidence 与既有事实伏笔引用均来自本轮可见范围"""
    allowed_chapters = {ledger.current_chapter_id} | ledger.visible_evidence_chapter_ids
    if output.evidence.chapterid not in allowed_chapters:
        raise AnnotationAuthorizationError(
            f"push evidence.chapterid 不在本轮可见范围: {output.evidence.chapterid}"
        )
    if isinstance(output, FactPushOutput):
        representative_node = output.payload.representative_node
        if (
            representative_node is not None
            and representative_node.node_id is not None
            and representative_node.node_id not in ledger.visible_graph_entity_node_ids
        ):
            raise AnnotationAuthorizationError(
                "representative_node.node_id 未由本轮图 search 返回: "
                f"{representative_node.node_id}"
            )
    if isinstance(output, ForeshadowingPushOutput):
        linked_setup_id = output.payload.linked_setup_id
        if linked_setup_id is not None and linked_setup_id not in ledger.visible_setup_ids:
            raise AnnotationAuthorizationError(f"linked_setup_id 未由本轮 search 返回: {linked_setup_id}")


def build_annotation_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
) -> list[Any]:
    """2026-08-05 用于构建按 finish 前后切换语义的章节 Agent 工具集"""

    @tool
    def search(query: str) -> str:
        """2026-08-05 用于在初始阶段检索连续性并在 finish 后检索固定后文范围"""
        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 2000:
            raise AnnotationInputError("search.query 必须为 1 至 2000 个 Unicode 字符")
        if ledger.frozen:
            results = query_service.search_after(
                normalized_query,
                limit=50,
            )
            ledger.authorized_after_chunks.update((item.chapter_id, item.chunk_id) for item in results)
            payload = SearchResult(results=list(results))
            response = payload.model_dump(mode="json")
            ledger.record(
                tool_name="search",
                phase="after_open",
                request={"query": normalized_query},
                response=response,
            )
            return payload.model_dump_json()

        result = query_service.search_continuity(
            normalized_query,
            hidden_case_ids=set(ledger.pulled_case_ids),
            limit=50,
        )
        _register_search_visibility(ledger, result)
        response = result.model_dump(mode="json")
        ledger.record(
            tool_name="search",
            phase="running_current",
            request={"query": normalized_query},
            response=response,
        )
        return result.model_dump_json()

    @tool
    def pull(ids: list[str]) -> str:
        """2026-08-05 用于把可见活动案例加入本次运行的处理责任集合"""
        if ledger.frozen:
            raise AnnotationProtocolError("首次有效 finish 后不允许 pull")
        normalized_ids = [case_id.strip() for case_id in ids]
        if not normalized_ids or len(normalized_ids) > 50 or any(not case_id for case_id in normalized_ids):
            raise AnnotationInputError("pull.ids 必须包含 1 至 50 个非空案例 ID")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise AnnotationInputError("pull.ids 不允许重复")
        already_pulled = sorted(set(normalized_ids) & set(ledger.pulled_case_ids))
        if already_pulled:
            raise AnnotationInputError(f"案例已经被本轮 pull: {already_pulled}")
        invisible = sorted(set(normalized_ids) - ledger.visible_case_ids)
        if invisible:
            raise AnnotationAuthorizationError(f"案例 ID 未由初始候选或本轮 search 返回: {invisible}")
        cases = query_service.fetch_active_cases(normalized_ids)
        returned = {case.id for case in cases}
        missing = sorted(set(normalized_ids) - returned)
        if missing:
            raise AnnotationInputError(f"案例不存在或已不再 active: {missing}")
        ledger.pulled_case_ids.extend(normalized_ids)
        result = PullResult(cases=cases)
        response = result.model_dump(mode="json")
        ledger.record(
            tool_name="pull",
            phase="running_current",
            request={"ids": normalized_ids},
            response=response,
        )
        return result.model_dump_json()

    @tool
    def push(outputs: list[PushOutput]) -> str:
        """2026-08-05 用于把案例事实伏笔或否定结果暂存到本次运行内存"""
        if ledger.frozen:
            raise AnnotationProtocolError("首次有效 finish 后不允许 push")
        request = PushRequest(outputs=outputs)
        for output in request.outputs:
            _validate_output_visibility(output, ledger)
        candidate_outputs = [*ledger.staged_outputs, *request.outputs]
        original_outputs = ledger.staged_outputs
        ledger.staged_outputs = candidate_outputs
        try:
            ledger.validate_staged_outputs()
        except ValueError as exc:
            if "未被任何 push 输出覆盖" not in str(exc):
                ledger.staged_outputs = original_outputs
                raise
        result = PushResult(staged_count=len(request.outputs))
        ledger.record(
            tool_name="push",
            phase="running_current",
            request=request.model_dump(mode="json"),
            response=result.model_dump(mode="json"),
        )
        return result.model_dump_json()

    @tool
    def read_chunk(chapter_id: int, chunk_id: int) -> str:
        """2026-08-05 用于读取本轮 after search 已命中的完整后文 chunk"""
        if not ledger.frozen:
            raise AnnotationAuthorizationError("首次有效 finish 前不允许读取后文 chunk")
        target = (chapter_id, chunk_id)
        if target not in ledger.authorized_after_chunks:
            raise AnnotationAuthorizationError(
                f"read_chunk 目标未由本轮 after search 命中: chapter_id={chapter_id} chunk_id={chunk_id}"
            )
        content = query_service.read_after_chunk(
            chapter_id=chapter_id,
            chunk_id=chunk_id,
        )
        ledger.record(
            tool_name="read_chunk",
            phase="after_open",
            request={"chapter_id": chapter_id, "chunk_id": chunk_id},
            response={"content_chars": len(content)},
        )
        return content

    @tool
    def finish(annotation: ChapterAnnotation) -> str:
        """2026-08-05 用于首次提交当前完整章节标注候选"""
        return "由 annotation 专用 LangGraph 校验"

    @tool
    def revise_finish(correction: ChapterAnnotationPatch) -> str:
        """2026-08-05 用于只提交相对当前候选实际变化的章节字段"""
        return "由 annotation 专用 LangGraph 合并并校验"

    return [search, pull, push, read_chunk, finish, revise_finish]
