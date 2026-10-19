"""诊断素材独立只读查询，模型会话仍在 agents"""

from __future__ import annotations

from typing import Any

from src.config.paths import resolve_model_dir
from src.event_trees.read.foreshadowing import (
    calculate_foreshadow_expectation,
    fetch_foreshadowing_sources,
    fetch_foreshadowing_trees,
)
from src.fact_graph.read.entities import fetch_latest_entities
from src.fact_graph.read.storage_projection import graph_projection
from src.metrics.queries.annotations import fetch_chapter_annotations_full
from src.storage import Storage
from src.storage.records.annotation import ForeshadowingTreeView
from src.topic.artifacts import load_topic_artifact


class DiagnosisQueries:
    def __init__(self, session: Storage) -> None:
        self.session = session

    def fetch_pivot_blocks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str]]:
        """从章节标注读取转折点原文素材"""
        row_limit = limit if limit is not None else 20
        text_by_chapter = dict(self.session.chapters.fetch_chapter_texts(run_id))
        rows = [
            (row.chapter_id, text_by_chapter.get(row.chapter_id, ""), row.event_type)
            for row in fetch_chapter_annotations_full(self.session, run_id)
            if row.pivot_moment
        ]
        return rows[:row_limit]

    def fetch_relation_changes(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, str, str, str]]:
        """从章节关系版本逐次变化读取诊断素材"""
        row_limit = limit if limit is not None else 50
        if row_limit == 0:
            return []
        rows: list[tuple[int, str, str, str, str]] = []
        for relation in graph_projection(self.session.graph).fetch_relation_history(run_id):
            if relation.relation_semantics == "same_character":
                continue
            for change in relation.changes:
                chapter_id = change.get("chapter_id")
                if chapter_id is None:
                    continue
                raw_after = change.get("after")
                after = raw_after if isinstance(raw_after, dict) else {}
                rows.append(
                    (
                        int(chapter_id),
                        relation.from_name,
                        relation.to_name,
                        str(after.get("relation_type") or relation.relation_type),
                        str(change.get("change_kind") or "refine"),
                    )
                )
                if row_limit > 0 and len(rows) >= row_limit:
                    return rows
        return rows[:row_limit]

    def fetch_foreshadowing_trees(self, run_id: str) -> list[ForeshadowingTreeView]:
        """读取伏笔树最新汇总视图"""
        return fetch_foreshadowing_trees(self.session, run_id)

    def fetch_foreshadowing_sources(self, run_id: str) -> list[dict[str, Any]]:
        """读取诊断尚未发布时的来源声明与明确动作，不借正式树伪造事件身份"""
        return fetch_foreshadowing_sources(self.session, run_id)

    def calculate_foreshadow_expectation(
        self, run_id: str, *, declaration_bindings: dict[str, str] | None = None
    ) -> float | None:
        """读取伏笔线程生命周期聚合预期"""
        return calculate_foreshadow_expectation(self.session, run_id, declaration_bindings=declaration_bindings)

    def fetch_pivot_moments(self, run_id: str, limit: int | None = None) -> list[tuple[int, str]]:
        """读取章节标注中的转折时刻"""
        return [(chapter_id, text) for chapter_id, text, _event_type in self.fetch_pivot_blocks(run_id, limit=limit)]

    def fetch_topic_words(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        """读取按累计权重排序的主题词（含主题词与标签，模型缺失时仅 id/weight）。

        Paragraph-only 主题聚合按原始 token 数加权
        （SUM(topic_weight * inference_token_count)），
        与 /topics 端点及 export 的聚合口径一致。
        """
        rows = self.session.diagnosis.fetch_topic_weights(run_id, top_n=top_n)
        artifact_words, artifact_labels, _reason = load_topic_artifact(resolve_model_dir(run_id))
        words_by_topic = {
            identifier: (values, artifact_labels.get(identifier)) for identifier, values in artifact_words.items()
        }
        for row in rows:
            words, label = words_by_topic.get(int(row["topic_id"]), ([], None))
            row["words"] = words
            row["label"] = label
        return rows

    def fetch_known_characters(self, run_id: str) -> list[str]:
        """从消歧后的规范人物视图读取诊断人物名单"""
        from src.fact_graph.read import KnowledgeGraphAuthorityService

        authority = KnowledgeGraphAuthorityService.from_session(self.session)
        try:
            view = authority.build_export_view(run_id)
        except ValueError:
            graph_repo = graph_projection(self.session.graph)
            return sorted(entity.name for entity in fetch_latest_entities(graph_repo, run_id, entity_type="character"))
        rows: list[str] = []
        for entity in view.canonical_entities:
            if entity.entity_type != "character":
                continue
            if not entity.name or not entity.name.strip() or entity.name == "null":
                continue
            if not entity.aliases:
                rows.append(entity.name)
                continue
            rows.append(f"{entity.name}（别名：{'、'.join(entity.aliases)}）")
        return rows

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        return self.session.diagnosis.fetch_high_tension_chunks(run_id, limit=limit)
