"""主题聚合查询服务测试（《分析能力扩展路线图》§5.11 / D1-D3）

覆盖：
- JS 散度（以 2 为底、范围 [0,1]）单元语义
- compute_topic_shift_candidates 窗口聚合与候选点
- 全书/章节分布、段落序列、主题-情感（db_session 集成，真实 SQL 聚合）
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.api.services.results_queries.topic_aggregations import (
    aggregate_book_topics,
    aggregate_chapter_topics,
    compute_topic_emotion,
    compute_topic_shift_candidates,
    fetch_paragraph_topic_series,
    jensen_shannon_divergence,
)
from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.storage.repositories import ParagraphRepository, RunRepository
from tests.support.analysis_factories import insert_test_novel

_CHUNK_TEXTS = ["甲。\n乙。\n丙。", "丁。\n戊。\n己。"]


class TestJensenShannonDivergence:
    def test_identical_distributions_zero(self) -> None:
        p = [0.5, 0.5]
        assert jensen_shannon_divergence(p, p) == pytest.approx(0.0, abs=1e-12)

    def test_disjoint_one_hot_reaches_one(self) -> None:
        p = [1.0, 0.0]
        q = [0.0, 1.0]
        assert jensen_shannon_divergence(p, q) == pytest.approx(1.0, abs=1e-12)

    def test_symmetric(self) -> None:
        p = [0.8, 0.1, 0.1]
        q = [0.1, 0.3, 0.6]
        assert jensen_shannon_divergence(p, q) == pytest.approx(
            jensen_shannon_divergence(q, p), abs=1e-12
        )

    def test_within_unit_range(self) -> None:
        p = [0.9, 0.05, 0.05]
        q = [0.05, 0.5, 0.45]
        score = jensen_shannon_divergence(p, q)
        assert 0.0 <= score <= 1.0

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            jensen_shannon_divergence([0.5, 0.5], [1.0])


def _series(points: list[dict]) -> dict:
    return {"points": points}


class TestComputeTopicShiftCandidates:
    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"window_size": 0}, "window_size"),
            ({"min_tokens_per_window": 0}, "min_tokens_per_window"),
            ({"score_threshold": 0}, "score_threshold"),
            ({"score_threshold": 1.1}, "score_threshold"),
            ({"max_candidates": 0}, "max_candidates"),
        ],
    )
    def test_rejects_invalid_overrides(self, overrides: dict[str, int | float], message: str) -> None:
        """2026-08-31 用于验证直接调用无法绕过主题迁移参数边界"""
        parameters: dict[str, int | float] = {
            "window_size": 2,
            "min_tokens_per_window": 1,
            "score_threshold": 0.1,
            "max_candidates": 10,
        }
        parameters.update(overrides)
        with pytest.raises(ValueError, match=message):
            compute_topic_shift_candidates(
                _series(
                    [
                        {"paragraph_id": 0, "start_position": 0, "token_count": 1, "weights": [1.0]},
                        {"paragraph_id": 1, "start_position": 1, "token_count": 1, "weights": [1.0]},
                    ]
                ),
                **parameters,
            )

    def test_insufficient_sample(self) -> None:
        result = compute_topic_shift_candidates(
            _series([]),
            window_size=2,
            min_tokens_per_window=1,
            score_threshold=0.1,
            max_candidates=10,
        )
        assert result["unavailable_reason"] is not None
        assert result["candidates"] == []
        assert result["config"]["window_size"] == 2

    def test_detects_abrupt_distribution_change(self) -> None:
        # 前 4 段全部主题 0、后 4 段全部主题 1；窗口=4 时两窗口 JS=1
        points = [
            {"paragraph_id": i, "start_position": i * 10, "token_count": 5, "weights": [1.0, 0.0]}
            for i in range(4)
        ] + [
            {"paragraph_id": i, "start_position": i * 10, "token_count": 5, "weights": [0.0, 1.0]}
            for i in range(4, 8)
        ]
        result = compute_topic_shift_candidates(
            _series(points),
            window_size=4,
            min_tokens_per_window=10,
            score_threshold=0.3,
            max_candidates=10,
        )
        assert result["unavailable_reason"] is None
        assert len(result["candidates"]) == 1
        candidate = result["candidates"][0]
        assert candidate["score"] == pytest.approx(1.0, abs=1e-6)
        # 候选点位置 = 后窗口首段起始字符
        assert candidate["position"] == 40
        assert candidate["paragraph_start"] == 0
        assert candidate["paragraph_end"] == 3

    def test_threshold_filters_low_scores(self) -> None:
        points = [
            {"paragraph_id": i, "start_position": i * 10, "token_count": 5, "weights": [0.9, 0.1]}
            for i in range(8)
        ]
        result = compute_topic_shift_candidates(
            _series(points),
            window_size=4,
            min_tokens_per_window=10,
            score_threshold=0.3,
            max_candidates=10,
        )
        assert result["candidates"] == []
        assert result["unavailable_reason"] == "no_candidates: 相邻窗口未达到阈值"

    def test_window_token_minimum_skips_sparse_windows(self) -> None:
        points = [
            {"paragraph_id": i, "start_position": i * 10, "token_count": 1, "weights": [1.0, 0.0]}
            for i in range(4)
        ] + [
            {"paragraph_id": i, "start_position": i * 10, "token_count": 1, "weights": [0.0, 1.0]}
            for i in range(4, 8)
        ]
        result = compute_topic_shift_candidates(
            _series(points),
            window_size=4,
            min_tokens_per_window=10,
            score_threshold=0.3,
            max_candidates=10,
        )
        # 每窗口 token 和 = 4 < 10，全部跳过 → 无窗口可比
        assert result["candidates"] == []

    def test_max_candidates_limits(self) -> None:
        points = []
        for block in range(6):
            one_hot = [1.0, 0.0] if block % 2 == 0 else [0.0, 1.0]
            points.extend(
                {"paragraph_id": len(points), "start_position": len(points) * 10, "token_count": 5, "weights": one_hot}
                for _ in range(4)
            )
        result = compute_topic_shift_candidates(
            _series(points),
            window_size=4,
            min_tokens_per_window=10,
            score_threshold=0.3,
            max_candidates=1,
        )
        assert len(result["candidates"]) == 1


class TestTopicAggregations:
    """三表契约 + 曲线数据的真实 SQL 聚合（§5.11）"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)
        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

        chapters = [
            Chunk(index=i, start=i * 500, end=i * 500 + len(text), text=text, chapter_id=i + 1)
            for i, text in enumerate(_CHUNK_TEXTS)
        ]
        from src.storage.repositories import ChapterRepository

        ChapterRepository(db_session).insert_chapter_texts(self.run_id, chapters)
        spans = [replace(span, token_count=2) for span in split_chunk_paragraphs(chapters)]
        ParagraphRepository(db_session).insert_paragraphs(self.run_id, spans)

        self._insert_topic_fixture()

    def _insert_topic_fixture(self) -> None:
        """段落 0..5 = 章1 段0-2 + 章2 段3-5；手工构造完整 2 维分布与状态行"""
        repo = ParagraphRepository(self.db_session)
        repo.insert_topic_model_run(
            self.run_id,
            model_key="gensim-lda",
            library_version="4.4.0",
            pipeline_version="1.0",
            num_topics=2,
            parameters={"num_topics": 2, "passes": 5},
            dictionary_size=20,
            training_document_count=6,
            inference_paragraph_count=6,
            artifact_key=f"models/topic/{self.run_id}",
        )
        # 章1 全主题0、章2 全主题1；inference_token_count 用于加权验证
        tokens = [10, 10, 20, 10, 10, 20]
        distributions = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
        inference_rows = [
            (paragraph_id, 2, tokens[paragraph_id], "complete", None, 1.0)
            for paragraph_id in range(6)
        ]
        repo.insert_paragraph_topic_inferences(self.run_id, inference_rows)
        topic_rows = [
            (paragraph_id, topic_id, distributions[paragraph_id][topic_id])
            for paragraph_id in range(6)
            for topic_id in range(2)
        ]
        repo.insert_paragraph_topics(self.run_id, topic_rows)

        # 情感曲线：段5 net_density 空值，验证分子分母同时排除
        from src.storage.repositories.paragraph_repository import ParagraphCurveRow

        net_densities = [0.5, 0.5, 0.5, -0.5, -0.5, None]
        curve_rows = [
            ParagraphCurveRow(
                paragraph_id=i,
                pos_density=None,
                neg_density=None,
                net_density=net_densities[i],
                smoothed_net_density=None,
                surface_tension=None,
                smoothed_surface_tension=None,
            )
            for i in range(6)
        ]
        repo.insert_paragraph_curves(self.run_id, curve_rows)

    def test_book_aggregate_normalizes_by_per_paragraph_denominator(self) -> None:
        result = aggregate_book_topics(self.run_id, self.db_session)
        assert result["unavailable_reason"] is None
        assert result["token_total"] == 80
        assert result["model"]["num_topics"] == 2
        weights = {entry["topic_id"]: entry["weight"] for entry in result["distribution"]}
        assert weights[0] == pytest.approx(40 / 80, abs=1e-6)
        assert weights[1] == pytest.approx(40 / 80, abs=1e-6)
        assert sum(entry["weight"] for entry in result["distribution"]) == pytest.approx(1.0, abs=1e-6)

    def test_chapter_aggregate_orders_and_normalizes_per_chapter(self) -> None:
        result = aggregate_chapter_topics(self.run_id, self.db_session)
        assert result["unavailable_reason"] is None
        chapters = result["chapters"]
        assert [c["chapter_sequence"] for c in chapters] == [1, 2]
        first = {e["topic_id"]: e["weight"] for e in chapters[0]["distribution"]}
        second = {e["topic_id"]: e["weight"] for e in chapters[1]["distribution"]}
        assert first[0] == pytest.approx(1.0, abs=1e-6)
        assert first[1] == pytest.approx(0.0, abs=1e-6)
        assert second[0] == pytest.approx(0.0, abs=1e-6)
        assert second[1] == pytest.approx(1.0, abs=1e-6)
        assert chapters[0]["token_total"] == 40
        assert chapters[1]["token_total"] == 40

    def test_chapter_aggregate_keeps_chapter_without_topic_rows(self) -> None:
        """2026-08-31 用于验证空推断章节仍按真实章节顺序返回并使用空分布"""
        repo = ParagraphRepository(self.db_session)
        repo.insert_paragraph_topic_inferences(
            self.run_id,
            [
                *((paragraph_id, 2, 10, "complete", None, 1.0) for paragraph_id in range(3)),
                *(
                    (paragraph_id, 2, 0, "empty_after_preprocess", "empty_after_preprocess", None)
                    for paragraph_id in range(3, 6)
                ),
            ],
        )
        repo.insert_paragraph_topics(
            self.run_id,
            [
                (paragraph_id, topic_id, 1.0 if topic_id == 0 else 0.0)
                for paragraph_id in range(3)
                for topic_id in range(2)
            ],
        )

        chapters = aggregate_chapter_topics(self.run_id, self.db_session)["chapters"]

        assert [chapter["chapter_sequence"] for chapter in chapters] == [1, 2]
        assert chapters[1]["token_total"] == 0
        assert chapters[1]["distribution"] is None

    def test_paragraph_series_returns_full_k_dimension(self) -> None:
        result = fetch_paragraph_topic_series(self.run_id, self.db_session)
        assert result["unavailable_reason"] is None
        assert result["num_topics"] == 2
        points = result["points"]
        assert len(points) == 6
        # 按真实字符位置排序（章1 在前）
        assert [p["chapter_id"] for p in points] == [1, 1, 1, 2, 2, 2]
        first = points[0]
        assert first["weights"] == pytest.approx([1.0, 0.0], abs=1e-6)
        assert first["start_position"] >= 0
        assert first["token_count"] == 10

    def test_topic_emotion_weighted_and_excludes_null_paragraphs(self) -> None:
        result = compute_topic_emotion(self.run_id, self.db_session)
        assert result["unavailable_reason"] is None
        by_topic = {e["topic_id"]: e for e in result["emotion"]}
        # 主题0：全部有 net_density 段落，均值 0.5
        assert by_topic[0]["emotion"] == pytest.approx(0.5, abs=1e-6)
        # 主题1：段5 空值排除，分子分母都只剩段3/段4
        assert by_topic[1]["emotion"] == pytest.approx(-0.5, abs=1e-6)

    def test_no_model_contract_returns_unavailable(self) -> None:
        run_repo = RunRepository(self.db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=self.db_session)
        other_run = run_repo.create_run(novel_id=novel_id, source_path="test", title="Other")
        result = aggregate_book_topics(other_run, self.db_session)
        assert result["unavailable_reason"] is not None
        assert result["distribution"] is None
        series = fetch_paragraph_topic_series(other_run, self.db_session)
        assert series["unavailable_reason"] is not None
        emotion = compute_topic_emotion(other_run, self.db_session)
        assert emotion["unavailable_reason"] is not None
