"""
标注 Agent 工具

- search_paragraph_evidence: 自然段级 RAG 证据检索（粒度固定为一个自然段）
- lookup_identity: 查询身份记忆（消歧查询）
- register_identity: 注册/更新身份映射（消歧集成进 agent 循环）
- finish: 提交最终合并标注结果
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from src.rag import EvidenceRequest, NarrativeEvidenceService

from .memory import IdentityMemory
from .schema import MergedChunkAnnotation


def _render_evidence_bundle(bundle) -> str:
    """把 EvidenceBundle 渲染成 agent 可读的证据文本"""
    parts: list[str] = []

    if bundle.level1_snapshot is not None and bundle.level1_snapshot.alias_mappings:
        alias_lines = [
            f"{m.alias} -> {m.canonical}" for m in bundle.level1_snapshot.alias_mappings
        ]
        if alias_lines:
            parts.append("<已确认别名表>\n" + "\n".join(alias_lines))

    if bundle.structured_evidence:
        entity_lines = [item.content for item in bundle.structured_evidence if item.evidence_type == "canonical_entity"]
        relation_lines = [
            item.content for item in bundle.structured_evidence if item.evidence_type == "confirmed_relation"
        ]
        if entity_lines:
            parts.append("<已知角色>\n" + "\n".join(entity_lines))
        if relation_lines:
            parts.append("<已确认关系>\n" + "\n".join(relation_lines))

    if bundle.local_evidence:
        active_lines = [str(item.content) for item in bundle.local_evidence if item.content]
        if active_lines:
            parts.append("<活跃实体>\n" + "\n".join(active_lines))

    paragraph_items = [item for item in bundle.semantic_evidence if item.evidence_type == "semantic_recall"]
    if paragraph_items:
        para_lines = []
        for item in paragraph_items:
            score = item.score if item.score is not None else 0.0
            para_lines.append(f"[chunk {item.chunk_id}] (score={score:.3f}) {item.content}")
        parts.append("<历史自然段证据>\n" + "\n".join(para_lines))

    return "\n\n".join(parts)


def build_annotation_tools(
    evidence_service: NarrativeEvidenceService | None,
    memory: IdentityMemory,
    *,
    run_id: str | None,
    chunk_id: int | None,
) -> list[Any]:
    """构建标注 agent 工具集（每次 chunk 运行创建，持有该 chunk 的身份记忆）"""

    @tool
    async def search_paragraph_evidence(query: str, top_k: int = 5) -> str:
        """
        在全书历史中检索与 query 语义相似的自然段证据（粒度固定为一个自然段）。
        用于确认人物身份、别名、历史事件与关系依据。query 应为具体的人物名、称呼或事件描述。
        """
        if evidence_service is None:
            return "（证据服务不可用）"
        request = EvidenceRequest(
            consumer="annotation_agent",
            objective="identity",
            query_text=query,
            requested_names=list(memory.known_canonical_names)[:10],
            seed_entities=[],
            background_entities=list(memory.known_canonical_names),
            current_chunk=chunk_id,
            max_chunk_id=chunk_id,
            exclude_chunk_ids=[chunk_id] if chunk_id is not None else [],
            need_level1=True,
            need_level2=True,
            need_level3=True,
            top_k=max(1, min(top_k, 10)),
        )
        try:
            bundle = await evidence_service.collect(request)
        except Exception as exc:  # noqa: BLE001
            return f"（证据检索失败: {exc}）"
        rendered = _render_evidence_bundle(bundle)
        return rendered if rendered else "（未检索到相关证据）"

    @tool
    def lookup_identity(name: str) -> str:
        """
        查询身份记忆：给定表面称呼，返回其规范名、实体类型与已知规范名列表。
        标注人物前先查询，避免把同一角色拆成多个实体。
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
        注册/更新身份映射：把当前 chunk 中的表面称呼绑定到规范名。
        当确定两个称呼是同一人物时必须调用；无法确定时不要合并。
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
    def finish(annotation: MergedChunkAnnotation) -> str:
        """
        完成标注：提交本 chunk 的完整合并标注结果（人物/伏笔/对话/关系/身份决策）。
        必须在完成所有检索与身份注册后调用；输出必须是完整 JSON。
        """
        return "OK"

    return [
        search_paragraph_evidence,
        lookup_identity,
        register_identity,
        finish,
    ]
