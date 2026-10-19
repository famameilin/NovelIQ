"""
语言结构领域仓储

语言面落点：
- paragraph_spans：词元（token_index/raw_pos）、NER（raw_entity_type）、固定短语
  （phrase_match_kind）三种互斥区间的唯一事实表；词面按原文切片，POS/NER 归一
  由固定代码映射（POS_GROUP_MAP/ENTITY_TYPE_MAP）投影
- paragraph_arcs：依存（dep:*，单头，ROOT 以 head_span_id 为空表达）与语义依存
  （sdp:*，多头多标签）的有序弧；source_ordinal 保留各层段落内真实源顺序
- paragraph_features：句式五类计数与 POS 分组向量（pos_vector:<group>）等封闭计算种类
- paragraph_metrics：语言完成事实 linguistic_completed_at/phrase_completed_at、
  共享句数 sentence_count 与边界监督观测（boundary_*_score_sum）
- runs：run 级 LTP 合同、固定短语合同与 w2v_* 构建事实

存储的 token_index 为 0 起词元序号（冻结模型合同）；读取投影转回 LTP 原生
1 起坐标（ROOT=0）。派生量（词长分组、POS 分组计数、依存统计、词典与 mNEG
对照计数、情绪事件）一律不落库，按正式词元/弧投影（fetch_linguistic_features）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.orm import Mapper, Session

from src.storage.ids import new_id
from src.storage.models import (
    LinguisticArc,
    LinguisticSpan,
    Paragraph,
    ParagraphFeature,
    ParagraphMetric,
    Run,
)
from src.storage.repositories.base import BaseRepository

#: 依存弧 / 语义依存弧的 relation_code 命名空间（与冻结模型一致）
_DEP_PREFIX = "dep:"
_SDP_PREFIX = "sdp:"

#: 句式五类计数 feature_code（封闭目录，零项保留）
_SENTENCE_FEATURE_CODES = (
    "sentence_short",
    "sentence_medium",
    "sentence_long",
    "sentence_compound",
    "sentence_parallel_candidate",
)

#: 句式 feature_code → 原 counts 键（写入/读取同源）
_SENTENCE_CODE_TO_KEY = {
    "sentence_short": "short",
    "sentence_medium": "medium",
    "sentence_long": "long",
    "sentence_compound": "compound",
    "sentence_parallel_candidate": "parallel_candidate",
}

#: POS 向量 feature_code 前缀
_POS_VECTOR_PREFIX = "pos_vector:"

#: 语义向量 feature_code（嵌入模型，列宽按运行合同解析）
FEATURE_SEMANTIC_VECTOR = "semantic_vector"

#: 短语命中封闭匹配方式（来源由运行唯一 fixed_phrases 合同取得）
PHRASE_MATCH_KIND_LEXICON = "lexicon"
PHRASE_MATCH_KIND_FOUR_CHAR = "four_char_candidate"

#: 未映射 POS 标签的归一组（与 ltp_client._OTHER_POS_GROUP 同值；此处仅为读取
#: 侧默认，映射唯一事实源仍是 ltp_client.POS_GROUP_MAP 版本合同）
_DEFAULT_POS_GROUP = "other"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class LinguisticRepository(BaseRepository[ParagraphMetric]):
    "语言结构仓储：run 合同、逐段区间/弧/特征写入与读取投影"

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # ------------------------------------------------------------------
    # 语言结构产出
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 段落语言结构：spans（词元）+ arcs（dep/sdp）+ 句式特征 + 完成事实
    # ------------------------------------------------------------------

    def insert_linguistic_features(
        self,
        run_id: str,
        rows: Sequence[dict[str, Any]],
        *,
        clear_first: bool = True,
    ) -> int:
        "先清后插写入 run 的逐段语言结构（冻结结构）"
        if not rows:
            return 0

        if clear_first:
            # spans 级联删除全部弧（DDL ondelete=CASCADE）
            self.session.execute(delete(LinguisticSpan).where(LinguisticSpan.run_id == run_id))
            self.session.execute(
                delete(ParagraphFeature).where(
                    ParagraphFeature.run_id == run_id,
                    ParagraphFeature.feature_code.in_(_SENTENCE_FEATURE_CODES),
                )
            )
            self.session.execute(
                update(ParagraphMetric).where(ParagraphMetric.run_id == run_id).values(linguistic_completed_at=None)
            )

        span_rows: list[dict[str, Any]] = []
        arc_rows: list[dict[str, Any]] = []
        feature_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        completed_at = _utcnow()

        for row in rows:
            paragraph_id = int(row["paragraph_id"])
            span_id_by_ltp_index: dict[int, str] = {}
            for token in row.get("tokens") or []:
                # LTP 原生坐标 1 起（ROOT=0）；存储按冻结模型合同转 0 起
                ltp_index = int(token["token_index"])
                span_id = new_id()
                span_id_by_ltp_index[ltp_index] = span_id
                span_rows.append(
                    {
                        "span_id": span_id,
                        "run_id": run_id,
                        "paragraph_id": paragraph_id,
                        "start_char": int(token["local_start_char"]),
                        "end_char": int(token["local_end_char"]),
                        "token_index": ltp_index - 1,
                        "raw_pos": str(token["pos_tag"]),
                    }
                )

            def _span_of(ltp_index: int, span_ids: dict[int, str] = span_id_by_ltp_index) -> str | None:
                # ROOT=0 无词元；其余索引必须命中本段词元（不造假区间）
                if ltp_index <= 0:
                    return None
                return span_ids.get(ltp_index)

            for ordinal, arc in enumerate(row.get("dependency_arcs") or []):
                dependent = _span_of(int(arc["dependent_index"]))
                if dependent is None:
                    continue
                arc_rows.append(
                    {
                        "arc_id": new_id(),
                        "dependent_span_id": dependent,
                        "head_span_id": _span_of(int(arc["head_index"])),
                        "relation_code": f"{_DEP_PREFIX}{arc['relation']}",
                        "source_ordinal": ordinal,
                    }
                )
            for ordinal, arc in enumerate(row.get("sdp_arcs") or []):
                dependent = _span_of(int(arc["dependent_index"]))
                if dependent is None:
                    continue
                arc_rows.append(
                    {
                        "arc_id": new_id(),
                        "dependent_span_id": dependent,
                        "head_span_id": _span_of(int(arc["head_index"])),
                        "relation_code": f"{_SDP_PREFIX}{arc['label']}",
                        "source_ordinal": ordinal,
                    }
                )

            patterns = row.get("sentence_pattern_counts") or {}
            for feature_code in _SENTENCE_FEATURE_CODES:
                key = _SENTENCE_CODE_TO_KEY[feature_code]
                feature_rows.append(
                    {
                        "run_id": run_id,
                        "paragraph_id": paragraph_id,
                        "feature_code": feature_code,
                        "count_value": int(patterns.get(key) or 0),
                        "created_at": completed_at,
                    }
                )

            sentence_count = row.get("sentence_count")
            metric_rows.append(
                {
                    "run_id": run_id,
                    "paragraph_id": paragraph_id,
                    "sentence_count": int(sentence_count) if sentence_count is not None else None,
                    "linguistic_completed_at": completed_at,
                }
            )

        if span_rows:
            self.session.bulk_insert_mappings(cast(Mapper[Any], LinguisticSpan), span_rows)
        if arc_rows:
            self.session.bulk_insert_mappings(cast(Mapper[Any], LinguisticArc), arc_rows)
        if feature_rows:
            self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphFeature), feature_rows)
        if metric_rows:
            statement = pg_insert(ParagraphMetric).values(metric_rows)
            self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["run_id", "paragraph_id"],
                    set_={
                        "sentence_count": statement.excluded.sentence_count,
                        "linguistic_completed_at": statement.excluded.linguistic_completed_at,
                    },
                )
            )
        return len(rows)

    def has_linguistic_features(self, run_id: str) -> bool:
        "该 run 是否存在语言完成事实（零词元段落同样计入已完成）"
        return (
            self.session.execute(
                select(ParagraphMetric.paragraph_id)
                .where(
                    ParagraphMetric.run_id == run_id,
                    ParagraphMetric.linguistic_completed_at.is_not(None),
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def fetch_linguistic_sources(self, run_id: str) -> dict[str, Any]:
        "按 3NF 前读取形状返回段落语言结构投影行"
        metric_rows = (
            self.session.execute(
                select(
                    ParagraphMetric.paragraph_id,
                    ParagraphMetric.sentence_count,
                    ParagraphMetric.boundary_pos_score_sum,
                    ParagraphMetric.boundary_neg_score_sum,
                )
                .where(ParagraphMetric.run_id == run_id, ParagraphMetric.linguistic_completed_at.is_not(None))
                .order_by(ParagraphMetric.paragraph_id)
            )
            .mappings()
            .all()
        )
        if not metric_rows:
            return {
                "metric_rows": [],
                "paragraph_texts": {},
                "tokens_by_paragraph": {},
                "arcs_by_paragraph": {},
                "token_index_by_span": {},
                "patterns_by_paragraph": {},
            }
        paragraph_texts = {
            int(row.paragraph_id): row.text
            for row in self.session.execute(
                select(Paragraph.paragraph_id, Paragraph.text).where(Paragraph.run_id == run_id)
            ).all()
        }
        tokens_by_paragraph: dict[int, list[Row]] = {}
        for row in self.session.execute(
            select(
                LinguisticSpan.paragraph_id,
                LinguisticSpan.token_index,
                LinguisticSpan.start_char,
                LinguisticSpan.end_char,
                LinguisticSpan.raw_pos,
            )
            .where(LinguisticSpan.run_id == run_id, LinguisticSpan.token_index.is_not(None))
            .order_by(LinguisticSpan.paragraph_id, LinguisticSpan.token_index)
        ).all():
            tokens_by_paragraph.setdefault(int(row.paragraph_id), []).append(row)
        token_index_by_span: dict[str, int] = {}
        arcs_by_paragraph: dict[int, list[Row]] = {}
        for arc_row in self.session.execute(
            select(
                LinguisticSpan.paragraph_id,
                LinguisticArc.relation_code,
                LinguisticArc.source_ordinal,
                LinguisticArc.dependent_span_id,
                LinguisticArc.head_span_id,
                LinguisticSpan.span_id,
                LinguisticSpan.token_index.label("dependent_index"),
            )
            .select_from(LinguisticArc)
            .join(LinguisticSpan, LinguisticSpan.span_id == LinguisticArc.dependent_span_id)
            .where(LinguisticSpan.run_id == run_id)
            .order_by(LinguisticSpan.paragraph_id, LinguisticArc.source_ordinal)
        ).all():
            arcs_by_paragraph.setdefault(int(arc_row.paragraph_id), []).append(arc_row)
            token_index_by_span[str(arc_row.span_id)] = int(arc_row.dependent_index)
        patterns_by_paragraph: dict[int, dict[str, int]] = {}
        for pattern_row in self.session.execute(
            select(ParagraphFeature.paragraph_id, ParagraphFeature.feature_code, ParagraphFeature.count_value).where(
                ParagraphFeature.run_id == run_id, ParagraphFeature.feature_code.in_(_SENTENCE_FEATURE_CODES)
            )
        ).all():
            patterns_by_paragraph.setdefault(int(pattern_row.paragraph_id), {})[str(pattern_row.feature_code)] = int(
                pattern_row.count_value or 0
            )
        return {
            "metric_rows": metric_rows,
            "paragraph_texts": paragraph_texts,
            "tokens_by_paragraph": tokens_by_paragraph,
            "arcs_by_paragraph": arcs_by_paragraph,
            "token_index_by_span": token_index_by_span,
            "patterns_by_paragraph": patterns_by_paragraph,
        }

    def insert_boundary_scores(
        self,
        run_id: str,
        rows: Sequence[tuple[int, float, float]],
    ) -> int:
        "回写段落级边界监督观测（boundary_pos/neg_score_sum，paragraph_metrics 列）"
        if not rows:
            return 0
        metric_table = cast(Any, ParagraphMetric.__table__)
        statement = (
            update(metric_table)
            .where(
                metric_table.c.run_id == bindparam("b_run_id"),
                metric_table.c.paragraph_id == bindparam("b_paragraph_id"),
            )
            .values(
                boundary_pos_score_sum=bindparam("b_pos"),
                boundary_neg_score_sum=bindparam("b_neg"),
            )
        )
        params = [{"b_run_id": run_id, "b_paragraph_id": pid, "b_pos": pos, "b_neg": neg} for pid, pos, neg in rows]
        self.session.execute(statement, params, execution_options={"synchronize_session": False})
        return len(params)

    # ------------------------------------------------------------------
    # NER 区间（linguistic_spans 的 raw_entity_type 分支）
    # ------------------------------------------------------------------

    def insert_entities(
        self,
        run_id: str,
        rows: Sequence[dict[str, Any]],
        *,
        clear_first: bool = True,
    ) -> int:
        "先清后插写入 run 的实体候选区间（LTP NER，非图谱事实）"
        if not rows:
            return 0
        if clear_first:
            self.session.execute(
                delete(LinguisticSpan).where(
                    LinguisticSpan.run_id == run_id,
                    LinguisticSpan.raw_entity_type.is_not(None),
                )
            )
        span_rows = [
            {
                "span_id": new_id(),
                "run_id": run_id,
                "paragraph_id": int(row["paragraph_id"]),
                "start_char": int(row["local_start_char"]),
                "end_char": int(row["local_end_char"]),
                "raw_entity_type": str(row["raw_entity_type"]),
            }
            for row in rows
        ]
        self.session.bulk_insert_mappings(cast(Mapper[Any], LinguisticSpan), span_rows)
        return len(span_rows)

    def fetch_entities(self, run_id: str) -> Sequence[SimpleNamespace]:
        "实体候选投影：词面按原文切片，归一类型按固定代码映射"
        rows = self.session.execute(
            text(
                """
                SELECT e.paragraph_id,
                       substring(p.text FROM e.start_char + 1
                                 FOR e.end_char - e.start_char) AS surface_text,
                       e.raw_entity_type,
                       e.start_char AS local_start_char,
                       e.end_char AS local_end_char
                  FROM paragraph_spans e
                  JOIN paragraphs p
                         ON p.run_id = e.run_id AND p.paragraph_id = e.paragraph_id
                 WHERE e.run_id = :run_id
                   AND e.raw_entity_type IS NOT NULL
                 ORDER BY e.paragraph_id, e.start_char
                """
            ),
            {"run_id": run_id},
        ).all()
        return [
            SimpleNamespace(
                paragraph_id=int(row.paragraph_id),
                surface_text=row.surface_text,
                raw_entity_type=row.raw_entity_type,
                normalized_entity_type=None,
                local_start_char=int(row.local_start_char),
                local_end_char=int(row.local_end_char),
                source_kind="ltp",
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 固定短语（linguistic_spans 的 phrase_match_kind 分支）
    # ------------------------------------------------------------------

    def insert_phrase_hits(
        self,
        run_id: str,
        rows: Sequence[dict[str, Any]],
        *,
        clear_first: bool = True,
    ) -> int:
        "先清后插写入 run 的固定短语命中区间"
        if not rows:
            return 0
        lexicon_keys = {str(row["lexicon_key"]) for row in rows if row.get("lexicon_key")}
        if len(lexicon_keys) > 1:
            raise ValueError(f"固定短语来源必须唯一（运行级合同），收到多个: {sorted(lexicon_keys)}")
        if clear_first:
            self.session.execute(
                delete(LinguisticSpan).where(
                    LinguisticSpan.run_id == run_id,
                    LinguisticSpan.phrase_match_kind.is_not(None),
                )
            )
            self.session.execute(
                update(ParagraphMetric).where(ParagraphMetric.run_id == run_id).values(phrase_completed_at=None)
            )
        span_rows = [
            {
                "span_id": new_id(),
                "run_id": run_id,
                "paragraph_id": int(row["paragraph_id"]),
                "start_char": int(row["local_start_char"]),
                "end_char": int(row["local_end_char"]),
                "phrase_match_kind": str(row["match_kind"]),
            }
            for row in rows
        ]
        self.session.bulk_insert_mappings(cast(Mapper[Any], LinguisticSpan), span_rows)
        return len(span_rows)

    def mark_phrase_completed(self, run_id: str, paragraph_ids: Sequence[int]) -> int:
        "把指定段落的 phrase_completed_at 置为真实完成时间（含零命中的段落）"
        if not paragraph_ids:
            return 0
        completed_at = _utcnow()
        statement = pg_insert(ParagraphMetric).values(
            [
                {
                    "run_id": run_id,
                    "paragraph_id": int(paragraph_id),
                    "phrase_completed_at": completed_at,
                }
                for paragraph_id in paragraph_ids
            ]
        )
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["run_id", "paragraph_id"],
                set_={"phrase_completed_at": statement.excluded.phrase_completed_at},
            )
        )
        return len(paragraph_ids)

    def fetch_phrase_hits(self, run_id: str) -> Sequence[SimpleNamespace]:
        "短语命中投影：词面按原文切片，is_metric_hit 由运行固定短语合同投影"
        from src.config.constants.contracts import FIXED_PHRASE_METRIC_ENABLED

        rows = self.session.execute(
            text(
                """
                SELECT h.paragraph_id,
                       substring(p.text FROM h.start_char + 1
                                 FOR h.end_char - h.start_char) AS surface_text,
                       h.start_char AS local_start_char,
                       h.end_char AS local_end_char,
                       h.phrase_match_kind AS match_kind
                  FROM paragraph_spans h
                  JOIN paragraphs p
                         ON p.run_id = h.run_id AND p.paragraph_id = h.paragraph_id
                 WHERE h.run_id = :run_id
                   AND h.phrase_match_kind IS NOT NULL
                 ORDER BY h.paragraph_id, h.start_char
                """
            ),
            {"run_id": run_id},
        ).all()
        return [
            SimpleNamespace(
                paragraph_id=int(row.paragraph_id),
                surface_text=row.surface_text,
                local_start_char=int(row.local_start_char),
                local_end_char=int(row.local_end_char),
                match_kind=str(row.match_kind),
                is_metric_hit=bool(FIXED_PHRASE_METRIC_ENABLED and str(row.match_kind) == PHRASE_MATCH_KIND_LEXICON),
            )
            for row in rows
        ]

    def has_phrase_hits(self, run_id: str) -> bool:
        "run 是否存在短语完成事实（phrase_completed_at 非空）"
        return (
            self.session.execute(
                select(ParagraphMetric.paragraph_id)
                .where(
                    ParagraphMetric.run_id == run_id,
                    ParagraphMetric.phrase_completed_at.is_not(None),
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    # ------------------------------------------------------------------
    # Word2Vec 合同与 POS 向量（实际 Word2Vec 产物与 paragraph_features）
    # ------------------------------------------------------------------

    def insert_word2vec_model_run(self, run_id: str, row: dict[str, Any]) -> None:
        "验证已保存词向量产物后标记完成"
        from gensim.models import Word2Vec

        from src.config.paths import resolve_run_model_dir

        model = Word2Vec.load(str(resolve_run_model_dir(run_id, "word2vec") / "word2vec.model"))
        if model.wv.vector_size != row["embedding_dimension"] or len(model.wv) != row["vocabulary_size"]:
            raise ValueError("Word2Vec 产物属性校验失败")
        self.session.execute(update(Run).where(Run.id == run_id).values(w2v_completed=True))

    def fetch_word2vec_model_run(self, run_id: str) -> SimpleNamespace | None:
        "从实际词向量产物读取模型属性"
        if not self.session.scalar(select(Run.w2v_completed).where(Run.id == run_id)):
            return None
        from gensim.models import Word2Vec

        from src.config.paths import resolve_run_model_dir

        model = Word2Vec.load(str(resolve_run_model_dir(run_id, "word2vec") / "word2vec.model"))
        return SimpleNamespace(
            run_id=run_id, embedding_dimension=int(model.wv.vector_size), vocabulary_size=len(model.wv)
        )

    def insert_pos_embeddings(self, run_id: str, rows: Sequence[dict[str, Any]]) -> int:
        "先清后插写入 run 的词性聚合向量（paragraph_features 的 pos_vector 行）"
        materialized = [row for row in rows if row.get("embedding_vector") is not None]
        self.session.execute(
            delete(ParagraphFeature).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code.like(f"{_POS_VECTOR_PREFIX}%"),
            )
        )
        if not materialized:
            return 0
        created_at = _utcnow()
        payload = [
            {
                "run_id": run_id,
                "paragraph_id": int(row["paragraph_id"]),
                "feature_code": f"{_POS_VECTOR_PREFIX}{row['pos_group']}",
                "vector_value": row["embedding_vector"],
                "in_vocabulary_token_count": row.get("in_vocabulary_token_count"),
                "created_at": created_at,
            }
            for row in materialized
        ]
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphFeature), payload)
        return len(payload)

    def fetch_pos_embedding_coverage(self, run_id: str, pos_mappings: Mapping[str, str]) -> Sequence[SimpleNamespace]:
        "按词性分组返回覆盖率分子分母（分母由正式词元 × 版本分组投影）"
        source_counts: dict[str, int] = {}
        for row in self.session.execute(
            select(LinguisticSpan.raw_pos).where(
                LinguisticSpan.run_id == run_id,
                LinguisticSpan.token_index.is_not(None),
            )
        ).all():
            group = pos_mappings.get(str(row.raw_pos), _DEFAULT_POS_GROUP)
            source_counts[group] = source_counts.get(group, 0) + 1

        in_vocab_counts: dict[str, int] = {}
        for vocab_row in self.session.execute(
            select(ParagraphFeature.feature_code, ParagraphFeature.in_vocabulary_token_count).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code.like(f"{_POS_VECTOR_PREFIX}%"),
                ParagraphFeature.in_vocabulary_token_count.is_not(None),
            )
        ).all():
            group = str(vocab_row.feature_code)[len(_POS_VECTOR_PREFIX) :]
            in_vocab_counts[group] = in_vocab_counts.get(group, 0) + int(vocab_row.in_vocabulary_token_count or 0)

        groups = sorted(set(source_counts) | set(in_vocab_counts))
        return [
            SimpleNamespace(
                pos_group=group,
                source_total=source_counts.get(group, 0),
                in_vocab_total=in_vocab_counts.get(group, 0),
            )
            for group in groups
        ]

    def fetch_weighted_pos_embeddings(self, run_id: str) -> Sequence[Row]:
        "在数据库内汇总词性向量，避免传输所有段落的高维向量"
        statement = text(
            """
            SELECT substr(feature_code, :prefix_len) AS pos_group,
                   SUM(in_vocabulary_token_count) AS weighted_token_total,
                   SUM(
                       vector_value * array_fill(
                           in_vocabulary_token_count::real,
                           ARRAY[vector_dims(vector_value)]
                       )::vector
                   ) AS weighted_sum
            FROM paragraph_features
            WHERE run_id = :run_id
              AND feature_code LIKE :pos_prefix
              AND in_vocabulary_token_count > 0
              AND vector_value IS NOT NULL
              AND vector_dims(vector_value) > 0
            GROUP BY 1
            ORDER BY 1
            """
        ).columns(weighted_sum=Vector())
        return self.session.execute(
            statement,
            {
                "run_id": run_id,
                "pos_prefix": f"{_POS_VECTOR_PREFIX}%",
                "prefix_len": len(_POS_VECTOR_PREFIX) + 1,
            },
        ).all()

    # ------------------------------------------------------------------
    # paragraph_features：语义向量读取（边界打分/语义检索共用）
    # ------------------------------------------------------------------

    def fetch_semantic_vectors(self, run_id: str) -> dict[int, list[float]]:
        "读取 run 的段落语义向量（feature_code='semantic_vector'，NULL 略过）"
        rows = self.session.execute(
            select(ParagraphFeature.paragraph_id, ParagraphFeature.vector_value).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR,
                ParagraphFeature.vector_value.is_not(None),
            )
        ).all()
        return {int(row.paragraph_id): [float(value) for value in row.vector_value] for row in rows}
