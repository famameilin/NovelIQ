"""
语言结构基础数据仓储（《分析能力扩展路线图》§5.3-5.7）

管理五个段落派生基础表：paragraph_linguistic_features、paragraph_entities、
paragraph_phrase_hits、word2vec_model_runs、paragraph_pos_embeddings。
全部按 run 先清后插（同 run 重跑语义是重新计算），content_hash 溯源到
paragraphs 事实源。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Mapper, Session

from src.storage.models import (
    ParagraphEntity,
    ParagraphLinguisticFeature,
    ParagraphPhraseHit,
    ParagraphPosEmbedding,
    Word2VecModelRun,
)
from src.storage.repositories.base import BaseRepository


class LinguisticRepository(BaseRepository[ParagraphLinguisticFeature]):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # ------------------------------------------------------------------
    # paragraph_linguistic_features（§5.3）
    # ------------------------------------------------------------------

    def insert_linguistic_features(
        self,
        run_id: str,
        rows: Sequence[dict[str, Any]],
    ) -> int:
        """先清后插写入 run 的段落语言结构行（rows 为 result.to_dict() + 元数据）"""
        if not rows:
            return 0
        self.session.execute(
            delete(ParagraphLinguisticFeature).where(ParagraphLinguisticFeature.run_id == run_id)
        )
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphLinguisticFeature), rows)
        return len(rows)

    def fetch_linguistic_features(self, run_id: str) -> Sequence[ParagraphLinguisticFeature]:
        statement = (
            select(ParagraphLinguisticFeature)
            .where(ParagraphLinguisticFeature.run_id == run_id)
            .order_by(ParagraphLinguisticFeature.paragraph_id)
        )
        return self.session.execute(statement).scalars().all()

    def has_linguistic_features(self, run_id: str) -> bool:
        return (
            self.session.execute(
                select(ParagraphLinguisticFeature.paragraph_id)
                .where(ParagraphLinguisticFeature.run_id == run_id)
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    # ------------------------------------------------------------------
    # paragraph_entities（§5.4）
    # ------------------------------------------------------------------

    def insert_entities(self, run_id: str, rows: Sequence[dict[str, Any]]) -> int:
        """先清后插写入 run 的实体候选行（LTP NER 输出，非图谱事实）"""
        if not rows:
            return 0
        self.session.execute(delete(ParagraphEntity).where(ParagraphEntity.run_id == run_id))
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphEntity), rows)
        return len(rows)

    def fetch_entities(self, run_id: str) -> Sequence[Row]:
        statement = (
            select(
                ParagraphEntity.paragraph_id,
                ParagraphEntity.surface_text,
                ParagraphEntity.raw_entity_type,
                ParagraphEntity.normalized_entity_type,
                ParagraphEntity.local_start_char,
                ParagraphEntity.local_end_char,
                ParagraphEntity.source_kind,
            )
            .where(ParagraphEntity.run_id == run_id)
            .order_by(ParagraphEntity.paragraph_id, ParagraphEntity.local_start_char)
        )
        return self.session.execute(statement).all()

    # ------------------------------------------------------------------
    # paragraph_phrase_hits（§5.5）
    # ------------------------------------------------------------------

    def insert_phrase_hits(self, run_id: str, rows: Sequence[dict[str, Any]]) -> int:
        """先清后插写入 run 的固定短语命中行（词表命中 + 四字候选）"""
        if not rows:
            return 0
        self.session.execute(delete(ParagraphPhraseHit).where(ParagraphPhraseHit.run_id == run_id))
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphPhraseHit), rows)
        return len(rows)

    def fetch_phrase_hits(self, run_id: str) -> Sequence[Row]:
        statement = (
            select(
                ParagraphPhraseHit.paragraph_id,
                ParagraphPhraseHit.surface_text,
                ParagraphPhraseHit.local_start_char,
                ParagraphPhraseHit.local_end_char,
                ParagraphPhraseHit.match_kind,
                ParagraphPhraseHit.is_metric_hit,
            )
            .where(ParagraphPhraseHit.run_id == run_id)
            .order_by(ParagraphPhraseHit.paragraph_id, ParagraphPhraseHit.local_start_char)
        )
        return self.session.execute(statement).all()

    # ------------------------------------------------------------------
    # word2vec_model_runs（§5.6）
    # ------------------------------------------------------------------

    def insert_word2vec_model_run(self, run_id: str, row: dict[str, Any]) -> None:
        self.session.execute(delete(Word2VecModelRun).where(Word2VecModelRun.run_id == run_id))
        self.session.execute(insert(Word2VecModelRun), row)

    def fetch_word2vec_model_run(self, run_id: str) -> Word2VecModelRun | None:
        statement = select(Word2VecModelRun).where(Word2VecModelRun.run_id == run_id)
        return self.session.execute(statement).scalar_one_or_none()

    # ------------------------------------------------------------------
    # paragraph_pos_embeddings（§5.7）
    # ------------------------------------------------------------------

    def insert_pos_embeddings(self, run_id: str, rows: Sequence[dict[str, Any]]) -> int:
        """先清后插写入 run 的词性聚合向量行"""
        if not rows:
            return 0
        self.session.execute(delete(ParagraphPosEmbedding).where(ParagraphPosEmbedding.run_id == run_id))
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphPosEmbedding), rows)
        return len(rows)

    def fetch_pos_embeddings(self, run_id: str) -> Sequence[Row]:
        statement = (
            select(
                ParagraphPosEmbedding.paragraph_id,
                ParagraphPosEmbedding.pos_group,
                ParagraphPosEmbedding.embedding_vector,
                ParagraphPosEmbedding.source_token_count,
                ParagraphPosEmbedding.in_vocabulary_token_count,
            )
            .where(ParagraphPosEmbedding.run_id == run_id)
            .order_by(ParagraphPosEmbedding.paragraph_id, ParagraphPosEmbedding.pos_group)
        )
        return self.session.execute(statement).all()

    def fetch_pos_embedding_coverage(self, run_id: str) -> Sequence[Row]:
        """按词性分组返回覆盖率分子分母（§5.11 词性向量覆盖率）"""
        statement = (
            select(
                ParagraphPosEmbedding.pos_group,
                func.sum(ParagraphPosEmbedding.source_token_count).label("source_total"),
                func.sum(ParagraphPosEmbedding.in_vocabulary_token_count).label("in_vocab_total"),
            )
            .where(ParagraphPosEmbedding.run_id == run_id)
            .group_by(ParagraphPosEmbedding.pos_group)
            .order_by(ParagraphPosEmbedding.pos_group)
        )
        return self.session.execute(statement).all()