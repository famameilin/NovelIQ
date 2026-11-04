"""语言结构、逐段统计及情绪观测的存取"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from types import SimpleNamespace
from typing import Any, cast

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
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
from src.storage.records.linguistic import (
    LINGUISTIC_COUNT_FIELDS,
    LINGUISTIC_GROUP_PREFIXES,
    LINGUISTIC_SCALAR_FIELDS,
    SENTENCE_CODE_TO_KEY,
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
                    (
                        ParagraphFeature.feature_code.in_(
                            (*LINGUISTIC_COUNT_FIELDS, *LINGUISTIC_SCALAR_FIELDS, *_SENTENCE_FEATURE_CODES)
                        )
                        | ParagraphFeature.feature_code.startswith("word_length:")
                        | ParagraphFeature.feature_code.startswith("pos_count:")
                        | ParagraphFeature.feature_code.startswith("dep_relation:")
                    ),
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
            token_rows: dict[int, dict[str, Any]] = {}
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
                token_rows[ltp_index] = span_rows[-1]

            for event in row["emotion_events"]:
                predicate = token_rows[int(event["predicate_token_index"])]
                if "emotion_polarity" in predicate:
                    raise ValueError("同一词元只能保存一个情绪观测")
                holder = event["holder_token_index"]
                if holder is not None and int(holder) not in token_rows:
                    raise ValueError("情绪持有者必须引用同段词元")
                predicate.update(
                    emotion_polarity=event["polarity"],
                    emotion_negated=event["negated"],
                    emotion_holder_token_index=None if holder is None else int(holder) - 1,
                )

            if int(row["ltp_token_count"]) != len(token_rows):
                raise ValueError("语言词元数必须与词元记录守恒")
            for field in ("word_length_counts", "pos_counts"):
                if sum(row[field].values()) != len(token_rows):
                    raise ValueError("词长和词性计数必须与有效词元数守恒")
            if int(row["dependency_node_count"]) != len(row["dependency_arcs"]):
                raise ValueError("依存节点数必须与依存弧数守恒")
            if sum(row["dependency_relation_counts"].values()) != int(row["dependency_node_count"]):
                raise ValueError("依存关系计数必须与依存节点数守恒")
            for field in LINGUISTIC_COUNT_FIELDS:
                if type(row[field]) is not int or row[field] < 0:
                    raise ValueError("语言结构统计必须为非负整数")
            for field in LINGUISTIC_SCALAR_FIELDS:
                if not isfinite(row[field]) or row[field] < 0:
                    raise ValueError("情绪对照计数必须为非负有限数")

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

            values = {field: ("count_value", row[field]) for field in LINGUISTIC_COUNT_FIELDS}
            values.update({field: ("scalar_value", row[field]) for field in LINGUISTIC_SCALAR_FIELDS})
            for field, prefix in LINGUISTIC_GROUP_PREFIXES.items():
                values.update({prefix + key: ("count_value", count) for key, count in row[field].items()})
            patterns = row["sentence_pattern_counts"]
            values.update({code: ("count_value", patterns.get(key, 0)) for code, key in SENTENCE_CODE_TO_KEY.items()})
            for feature_code, (value_column, value) in values.items():
                feature_rows.append(
                    {
                        "run_id": run_id,
                        "paragraph_id": paragraph_id,
                        "feature_code": feature_code,
                        value_column: value,
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

    def fetch_statistics_aggregates(self, run_id: str) -> dict[str, Any]:
        "读取已保存语言统计的全书、章节和情绪分组汇总"
        from src.storage.repositories.queries.linguistic_statistics import fetch_statistics_aggregates

        return fetch_statistics_aggregates(self.session, run_id)

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

    def fetch_linguistic_sources(
        self, run_id: str, *, after_id: int | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        "读取语言完成段落及其词元、依存弧和句式观测"
        statement = (
            select(
                ParagraphMetric.paragraph_id,
                ParagraphMetric.sentence_count,
                ParagraphMetric.boundary_pos_score_sum,
                ParagraphMetric.boundary_neg_score_sum,
            )
            .where(ParagraphMetric.run_id == run_id, ParagraphMetric.linguistic_completed_at.is_not(None))
            .order_by(ParagraphMetric.paragraph_id)
        )
        if after_id is not None:
            statement = statement.where(ParagraphMetric.paragraph_id > after_id)
        if limit is not None:
            if limit < 1:
                raise ValueError("每批段落数量必须大于 0")
            statement = statement.limit(limit)
        metric_rows = self.session.execute(statement).mappings().all()
        if not metric_rows:
            return {
                "metric_rows": [],
                "paragraph_texts": {},
                "tokens_by_paragraph": {},
                "arcs_by_paragraph": {},
                "token_index_by_span": {},
                "patterns_by_paragraph": {},
            }
        paragraph_ids = [row.paragraph_id for row in metric_rows]

        def scoped(statement, paragraph_column):
            if after_id is None and limit is None:
                return statement
            return statement.where(paragraph_column.in_(paragraph_ids))

        paragraph_texts = {
            int(row.paragraph_id): row.text
            for row in self.session.execute(
                scoped(
                    select(Paragraph.paragraph_id, Paragraph.text).where(Paragraph.run_id == run_id),
                    Paragraph.paragraph_id,
                )
            ).all()
        }
        tokens_by_paragraph: dict[int, Row] = {}
        for row in self.session.execute(
            scoped(
                select(
                    LinguisticSpan.paragraph_id,
                    func.array_agg(aggregate_order_by(LinguisticSpan.token_index, LinguisticSpan.token_index)).label(
                        "token_indices"
                    ),
                    func.array_agg(aggregate_order_by(LinguisticSpan.start_char, LinguisticSpan.token_index)).label(
                        "start_chars"
                    ),
                    func.array_agg(aggregate_order_by(LinguisticSpan.end_char, LinguisticSpan.token_index)).label(
                        "end_chars"
                    ),
                    func.array_agg(aggregate_order_by(LinguisticSpan.raw_pos, LinguisticSpan.token_index)).label(
                        "pos_tags"
                    ),
                )
                .where(LinguisticSpan.run_id == run_id, LinguisticSpan.token_index.is_not(None))
                .group_by(LinguisticSpan.paragraph_id)
                .order_by(LinguisticSpan.paragraph_id),
                LinguisticSpan.paragraph_id,
            )
        ).all():
            tokens_by_paragraph[int(row.paragraph_id)] = row
        token_index_by_span: dict[str, int] = {}
        arcs_by_paragraph: dict[int, Row] = {}
        for arc_row in self.session.execute(
            scoped(
                select(
                    LinguisticSpan.paragraph_id,
                    func.array_agg(aggregate_order_by(LinguisticArc.relation_code, LinguisticArc.source_ordinal)).label(
                        "relation_codes"
                    ),
                    func.array_agg(aggregate_order_by(LinguisticArc.head_span_id, LinguisticArc.source_ordinal)).label(
                        "head_span_ids"
                    ),
                    func.array_agg(aggregate_order_by(LinguisticSpan.span_id, LinguisticArc.source_ordinal)).label(
                        "span_ids"
                    ),
                    func.array_agg(aggregate_order_by(LinguisticSpan.token_index, LinguisticArc.source_ordinal)).label(
                        "dependent_indices"
                    ),
                )
                .select_from(LinguisticArc)
                .join(LinguisticSpan, LinguisticSpan.span_id == LinguisticArc.dependent_span_id)
                .where(LinguisticSpan.run_id == run_id)
                .group_by(LinguisticSpan.paragraph_id)
                .order_by(LinguisticSpan.paragraph_id),
                LinguisticSpan.paragraph_id,
            )
        ).all():
            arcs_by_paragraph[int(arc_row.paragraph_id)] = arc_row
            token_index_by_span.update(
                (str(span_id), int(index))
                for span_id, index in zip(arc_row.span_ids, arc_row.dependent_indices, strict=True)
            )
        patterns_by_paragraph: dict[int, dict[str, int]] = {}
        for pattern_row in self.session.execute(
            scoped(
                select(
                    ParagraphFeature.paragraph_id, ParagraphFeature.feature_code, ParagraphFeature.count_value
                ).where(
                    ParagraphFeature.run_id == run_id, ParagraphFeature.feature_code.in_(_SENTENCE_FEATURE_CODES)
                ),
                ParagraphFeature.paragraph_id,
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
        "短语命中投影：词面按原文切片，匹配方式随行返回"

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
            select(LinguisticSpan.raw_pos, func.count().label("source_total"))
            .where(
                LinguisticSpan.run_id == run_id, LinguisticSpan.token_index.is_not(None),
            )
            .group_by(LinguisticSpan.raw_pos)
        ).all():
            group = pos_mappings.get(str(row.raw_pos), _DEFAULT_POS_GROUP)
            source_counts[group] = source_counts.get(group, 0) + int(row.source_total)

        in_vocab_counts: dict[str, int] = {}
        for vocab_row in self.session.execute(
            select(
                ParagraphFeature.feature_code,
                func.sum(ParagraphFeature.in_vocabulary_token_count).label("in_vocab_total"),
            ).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code.like(f"{_POS_VECTOR_PREFIX}%"),
                ParagraphFeature.in_vocabulary_token_count.is_not(None),
            ).group_by(ParagraphFeature.feature_code)
        ).all():
            group = str(vocab_row.feature_code)[len(_POS_VECTOR_PREFIX) :]
            in_vocab_counts[group] = in_vocab_counts.get(group, 0) + int(vocab_row.in_vocab_total or 0)

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
