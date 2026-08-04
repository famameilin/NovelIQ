"""
标注 Agent 工具

- lookup_identity: 查询身份记忆（消歧查询）
- register_identity: 注册/更新身份映射（消歧集成进 agent 循环）
- lookup_authority_facts: Level1 权威事实查询
- list_recent_context: Level2 近期导航上下文
- search_paragraph_evidence: Level3 自然段语义检索
- search_paragraph_by_keywords: Level3 自然段关键词精确检索
- read_chunk: 受历史边界保护的原文展开
- finish: 提交最终合并标注结果
"""

from __future__ import annotations

import re
import time
from typing import Any

from langchain_core.tools import tool

from src.rag import EvidenceObjective, EvidenceRequest, NarrativeEvidenceService

from .evidence import AnnotationEvidenceLedger
from .memory import IdentityMemory
from .schema import MergedChunkAnnotation, MergedChunkAnnotationPatch


def _render_authority_evidence(bundle) -> str:
    """
    2026-08-02 用于只渲染请求裁剪后的 Level1 权威事实
    """
    parts: list[str] = []

    alias_lines = [
        item.content
        for item in bundle.structured_evidence
        if item.evidence_type == "alias_mapping"
    ]
    entity_lines = [
        item.content
        for item in bundle.structured_evidence
        if item.evidence_type == "canonical_entity"
    ]
    type_lines = [
        item.content
        for item in bundle.structured_evidence
        if item.evidence_type == "entity_type"
    ]
    relation_lines = [
        item.content
        for item in bundle.structured_evidence
        if item.evidence_type == "confirmed_relation"
    ]
    if alias_lines:
        parts.append("<已确认别名>\n" + "\n".join(dict.fromkeys(alias_lines)))
    if entity_lines:
        parts.append("<已确认实体>\n" + "\n".join(dict.fromkeys(entity_lines)))
    if type_lines:
        parts.append("<已确认实体类型>\n" + "\n".join(dict.fromkeys(type_lines)))
    if relation_lines:
        parts.append("<已确认关系>\n" + "\n".join(dict.fromkeys(relation_lines)))

    return "\n\n".join(parts)


def _render_recent_context(bundle, *, limit: int) -> str:
    """
    2026-08-02 用于把 Level2 活跃实体渲染为非证明性的近期导航上下文
    """
    lines: list[str] = []
    for item in bundle.local_evidence[:limit]:
        if item.evidence_type != "active_entity":
            continue
        metadata = item.metadata
        details = [
            f"type={metadata.get('entity_type') or 'character'}",
            f"last_chunk={metadata.get('last_seen_chunk')}",
        ]
        if metadata.get("role"):
            details.append(f"role={metadata['role']}")
        if metadata.get("recent_action"):
            details.append(f"action={metadata['recent_action']}")
        if metadata.get("recent_emotion"):
            details.append(f"emotion={metadata['recent_emotion']}")
        lines.append(f"{item.content} | " + " | ".join(details))
    if not lines:
        return ""
    return "<近期导航上下文>\n" + "\n".join(lines)


def _render_historical_evidence(
    bundle,
    *,
    objective: str,
    ledger: AnnotationEvidenceLedger,
) -> tuple[str, list[str]]:
    """
    2026-08-03 用于登记并渲染统一历史取证结果
    """
    historical_items = list(bundle.historical_evidence)
    evidence_ids = ledger.register_evidence_items(historical_items, objective=objective)
    lines: list[str] = []
    for item in historical_items:
        if not item.evidence_id:
            continue
        metadata = item.metadata
        details = [f"evidence_id={item.evidence_id}", f"chunk={item.chunk_id}"]
        if item.retrieval_method == "semantic":
            score = item.score if item.score is not None else 0.0
            details.append(f"score={score:.3f}")
        if item.retrieval_method == "keyword":
            matched_keywords = metadata.get("matched_keywords", [])
            details.append(f"matches={metadata.get('match_count', len(matched_keywords))}")
            if matched_keywords:
                details.append(f"keywords={','.join(str(keyword) for keyword in matched_keywords)}")
        lines.append(f"[{' '.join(details)}] {item.content}")
    if not lines:
        return "", evidence_ids
    return "<历史自然段证据>\n" + "\n".join(lines), evidence_ids


def build_annotation_tools(
    evidence_service: NarrativeEvidenceService | None,
    memory: IdentityMemory,
    *,
    run_id: str | None,
    chunk_id: int | None,
    session: Any | None = None,
    evidence_ledger: AnnotationEvidenceLedger | None = None,
) -> list[Any]:
    """
    2026-08-02 用于构建持有当前 chunk 身份记忆和证据账本的标注 Agent 工具集
    """
    ledger = evidence_ledger or AnnotationEvidenceLedger()

    @tool
    async def lookup_authority_facts(
        names: list[str],
        objective: EvidenceObjective = "identity",
    ) -> str:
        """
        2026-08-02 用于查询指定名字的已确认别名规范实体类型与当前关系
        names 只包含当前任务需要核对的名字且结果不代表当前 chunk 发生对应事件
        """
        started_at = time.perf_counter()
        normalized_names = [name.strip() for name in names if name.strip()]
        request_payload = {"names": normalized_names, "objective": objective}
        if evidence_service is None:
            ledger.record_tool_call(
                tool_name="lookup_authority_facts",
                objective=objective,
                request=request_payload,
                status="unavailable",
            )
            return "（证据服务不可用）"
        if not normalized_names:
            ledger.record_tool_call(
                tool_name="lookup_authority_facts",
                objective=objective,
                request=request_payload,
                status="empty_request",
            )
            return "（未提供需要核对的名字）"
        request = EvidenceRequest(
            consumer="annotation_agent",
            objective=objective,
            requested_names=normalized_names,
            seed_entities=normalized_names,
            background_entities=sorted(memory.known_canonical_names),
            current_chunk=chunk_id,
            need_level1=True,
            need_level2=False,
            top_k=0,
        )
        try:
            bundle = await evidence_service.collect(request)
        except Exception as exc:
            ledger.record_tool_call(
                tool_name="lookup_authority_facts",
                objective=objective,
                request=request_payload,
                status="error",
                error=str(exc),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise
        rendered = _render_authority_evidence(bundle)
        ledger.record_tool_call(
            tool_name="lookup_authority_facts",
            objective=objective,
            request=request_payload,
            status="success" if rendered else "empty",
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return rendered if rendered else "（未找到相关权威事实）"

    @tool
    async def list_recent_context(limit: int = 10) -> str:
        """
        2026-08-02 用于查询当前 chunk 之前的近期活跃实体导航状态
        结果只用于决定继续核对谁和检索什么且不能单独证明最终结论
        """
        started_at = time.perf_counter()
        effective_limit = max(1, min(limit, 30))
        request_payload = {"limit": effective_limit}
        if evidence_service is None:
            ledger.record_tool_call(
                tool_name="list_recent_context",
                objective="navigation",
                request=request_payload,
                status="unavailable",
            )
            return "（证据服务不可用）"
        request = EvidenceRequest(
            consumer="annotation_agent",
            objective="identity",
            requested_names=[],
            seed_entities=[],
            background_entities=sorted(memory.known_canonical_names),
            current_chunk=chunk_id,
            need_level1=False,
            need_level2=True,
            top_k=effective_limit,
        )
        try:
            bundle = await evidence_service.collect(request)
        except Exception as exc:
            ledger.record_tool_call(
                tool_name="list_recent_context",
                objective="navigation",
                request=request_payload,
                status="error",
                error=str(exc),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise
        rendered = _render_recent_context(bundle, limit=effective_limit)
        ledger.record_tool_call(
            tool_name="list_recent_context",
            objective="navigation",
            request=request_payload,
            status="success" if rendered else "empty",
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return rendered if rendered else "（无近期活跃实体）"

    @tool
    async def search_paragraph_evidence(
        query: str,
        objective: EvidenceObjective = "identity",
        top_k: int = 5,
    ) -> str:
        """
        2026-08-02 用于检索当前 chunk 之前与 query 语义相似的历史自然段原文
        返回的 evidence_id 用于 historical_evidence_citations 引用具体历史依据
        """
        started_at = time.perf_counter()
        normalized_query = query.strip()
        effective_top_k = max(1, min(top_k, 10))
        request_payload = {
            "mode": "semantic",
            "query": normalized_query,
            "objective": objective,
            "top_k": effective_top_k,
            "current_chunk": chunk_id,
        }
        if evidence_service is None:
            ledger.record_tool_call(
                tool_name="search_paragraph_evidence",
                objective=objective,
                request=request_payload,
                status="unavailable",
            )
            return "（证据服务不可用）"
        if not normalized_query:
            ledger.record_tool_call(
                tool_name="search_paragraph_evidence",
                objective=objective,
                request=request_payload,
                status="empty_request",
            )
            return "（检索问题为空）"
        request = EvidenceRequest(
            consumer="annotation_agent",
            objective=objective,
            mode="semantic",
            query_text=normalized_query,
            current_chunk=chunk_id,
            top_k=effective_top_k,
        )
        try:
            bundle = await evidence_service.collect(request)
        except Exception as exc:
            ledger.record_tool_call(
                tool_name="search_paragraph_evidence",
                objective=objective,
                request=request_payload,
                status="error",
                error=str(exc),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise
        rendered, evidence_ids = _render_historical_evidence(
            bundle,
            objective=objective,
            ledger=ledger,
        )
        ledger.record_tool_call(
            tool_name="search_paragraph_evidence",
            objective=objective,
            request=request_payload,
            status="success" if rendered else "empty",
            evidence_ids=evidence_ids,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return rendered if rendered else "（未检索到历史自然段证据）"

    @tool
    def lookup_identity(name: str) -> str:
        """
        2026-08-02 用于查询表面称呼的规范名实体类型与当前已知规范名
        标注人物前调用以避免把同一角色拆成多个实体
        """
        normalized = name.strip()
        if not normalized:
            return "（名字为空）"
        canonical = memory.alias_map.get(normalized, normalized)
        entity_type = memory.entity_types.get(canonical, "character")
        known = sorted(memory.known_canonical_names)
        return (
            f"表面称呼: {normalized}\n"
            f"规范名: {canonical}\n"
            f"实体类型: {entity_type}\n"
            f"已知规范名: {known}"
        )

    @tool
    def register_identity(name: str, canonical: str, entity_type: str = "character", evidence: str = "") -> str:
        """
        2026-08-02 用于把当前 chunk 中已确认的表面称呼登记到规范身份
        仅在两个称呼能够确认为同一人物时调用
        """
        memory.apply_decisions(
            [
                {
                    "name": name,
                    "canonical": canonical,
                    "entity_type": entity_type,
                    "confidence": "high",
                    "evidence": evidence,
                }
            ]
        )
        return f"已注册身份映射: {name} -> {canonical} (entity_type={entity_type})"

    @tool
    def list_active_foreshadowing_threads() -> str:
        """
        2026-08-02 用于查询当前 chunk 之前可见的活跃伏笔线程及真实 setup_id
        用于判断当前伏笔是新建线程还是强化兑现既有线程
        """
        if session is None or not run_id or chunk_id is None:
            return "（伏笔线程服务不可用）"

        from src.storage.repositories.annotation.foreshadowing_threads import (
            fetch_active_foreshadowing_threads_for_prompt,
        )

        entries = fetch_active_foreshadowing_threads_for_prompt(
            session,
            run_id,
            max_chunk_id=chunk_id - 1,
        )
        if not entries:
            return "（无可见的活跃伏笔线程）"

        lines = ["<活跃伏笔线程>"]
        for entry in entries:
            lines.append(
                f"setup_id={entry.setup_id} | summary={entry.setup_summary} | "
                f"kind={entry.setup_kind} | payoff={entry.expected_payoff_family} | "
                f"likelihood={entry.payoff_likelihood} | status={entry.status} | "
                f"last_chunk={entry.last_chunk_id}"
            )
        lines.append("</活跃伏笔线程>")
        return "\n".join(lines)

    @tool
    async def search_paragraph_by_keywords(
        keywords: str,
        objective: EvidenceObjective = "identity",
        top_k: int = 10,
    ) -> str:
        """
        2026-08-03 用于通过 EvidenceService 按关键词字面匹配当前 chunk 之前的历史自然段
        适合确认人物名事件名与专有名词的精确出处
        """
        started_at = time.perf_counter()
        effective_top_k = max(1, min(top_k, 10))
        keyword_list = [kw.strip() for kw in re.split(r"[,，\s]+", keywords) if kw.strip()]
        request_payload = {
            "mode": "keyword",
            "keywords": keyword_list,
            "objective": objective,
            "top_k": effective_top_k,
            "current_chunk": chunk_id,
        }
        if evidence_service is None:
            ledger.record_tool_call(
                tool_name="search_paragraph_by_keywords",
                objective=objective,
                request=request_payload,
                status="unavailable",
            )
            return "（关键词检索不可用）"
        if not keyword_list:
            ledger.record_tool_call(
                tool_name="search_paragraph_by_keywords",
                objective=objective,
                request=request_payload,
                status="empty_request",
            )
            return "（关键词为空）"
        request = EvidenceRequest(
            consumer="annotation_agent",
            objective=objective,
            mode="keyword",
            keywords=keyword_list,
            current_chunk=chunk_id,
            top_k=effective_top_k,
        )
        try:
            bundle = await evidence_service.collect(request)
        except Exception as exc:
            ledger.record_tool_call(
                tool_name="search_paragraph_by_keywords",
                objective=objective,
                request=request_payload,
                status="error",
                error=str(exc),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise
        rendered, evidence_ids = _render_historical_evidence(
            bundle,
            objective=objective,
            ledger=ledger,
        )
        if not rendered:
            skipped_reason = bundle.generation_meta.get("historical_skipped_reason")
            status = "unavailable" if skipped_reason == "storage_unavailable" else "empty"
            ledger.record_tool_call(
                tool_name="search_paragraph_by_keywords",
                objective=objective,
                request=request_payload,
                status=status,
                evidence_ids=evidence_ids,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            return "（未找到关键词匹配的段落）"
        ledger.record_tool_call(
            tool_name="search_paragraph_by_keywords",
            objective=objective,
            request=request_payload,
            status="success",
            evidence_ids=evidence_ids,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return rendered

    @tool
    async def read_chunk(
        chunk_id_to_read: int,
        objective: EvidenceObjective = "identity",
    ) -> str:
        """
        2026-08-03 用于通过 EvidenceService 展开已被同一检索目标定位的历史 chunk 原文
        当前 chunk 边界和读取授权由 EvidenceService 统一校验
        """
        started_at = time.perf_counter()
        request_payload = {
            "mode": "read",
            "chunk_id": chunk_id_to_read,
            "objective": objective,
            "current_chunk": chunk_id,
        }
        if evidence_service is None:
            ledger.record_tool_call(
                tool_name="read_chunk",
                objective=objective,
                request=request_payload,
                status="unavailable",
            )
            return "（原文读取不可用）"
        request = EvidenceRequest(
            consumer="annotation_agent",
            objective=objective,
            mode="read",
            read_chunk_id=chunk_id_to_read,
            current_chunk=chunk_id,
        )
        try:
            bundle = await evidence_service.collect(request)
        except Exception as exc:
            ledger.record_tool_call(
                tool_name="read_chunk",
                objective=objective,
                request=request_payload,
                status="error",
                error=str(exc),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            raise
        read_status = bundle.generation_meta.get("read_status")
        if read_status == "blocked_by_policy":
            ledger.record_tool_call(
                tool_name="read_chunk",
                objective=objective,
                request=request_payload,
                status="blocked_by_policy",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            return "（只能读取同一检索目标已经定位且位于当前 chunk 之前的历史原文）"
        if read_status == "unavailable":
            ledger.record_tool_call(
                tool_name="read_chunk",
                objective=objective,
                request=request_payload,
                status="unavailable",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            return "（原文读取不可用）"
        if read_status == "empty":
            ledger.record_tool_call(
                tool_name="read_chunk",
                objective=objective,
                request=request_payload,
                status="empty",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            return f"（chunk {chunk_id_to_read} 不存在）"
        rendered, evidence_ids = _render_historical_evidence(
            bundle,
            objective=objective,
            ledger=ledger,
        )
        if not rendered:
            ledger.record_tool_call(
                tool_name="read_chunk",
                objective=objective,
                request=request_payload,
                status="empty",
                evidence_ids=evidence_ids,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            return f"（chunk {chunk_id_to_read} 不存在）"
        evidence_id = evidence_ids[0] if evidence_ids else f"chunk:{chunk_id_to_read}"
        ledger.record_tool_call(
            tool_name="read_chunk",
            objective=objective,
            request=request_payload,
            status="success",
            evidence_ids=evidence_ids,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        content = bundle.historical_evidence[0].content
        return f"<历史 chunk 原文 evidence_id={evidence_id}>\n{content}\n</历史 chunk 原文>"

    @tool
    def finish(annotation: MergedChunkAnnotation) -> str:
        """
        2026-08-03 用于首次提交当前 chunk 的完整四阶段标注与历史证据引用
        必须在完成所需检索与身份登记后调用
        """
        return "OK"

    @tool
    def revise_finish(correction: MergedChunkAnnotationPatch) -> str:
        """
        2026-08-03 用于校验失败后只提交需要修改的顶层字段
        仅在收到 finish 校验错误后调用且无需重复提交完整四阶段结果
        """
        return "OK"

    return [
        lookup_identity,
        register_identity,
        lookup_authority_facts,
        list_recent_context,
        search_paragraph_evidence,
        search_paragraph_by_keywords,
        read_chunk,
        list_active_foreshadowing_threads,
        finish,
        revise_finish,
    ]
