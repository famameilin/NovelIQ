"""
聚合指标集成测试。
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.aggregate import AggregateResult, aggregate_all_metrics
from src.metrics.aggregate.computers import compute_narrative_structure_metrics
from src.metrics.aggregate.types import AnnotationData, TensionData
from src.storage.repositories import AnnotationRepository, ChunkRepository, StatsRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    dialogue_fact,
    persist_chapter_annotation,
    relation_fact,
)


class TestAggregateAllMetrics:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id, self.run_id = create_run_with_chunks(
            db_session,
            texts=["测试文本“退下”一心一意", "此乃天意也。"],
            chapter_ids=[1, 1],
            title="聚合指标测试",
        )
        self._populate_test_data()

    def _populate_test_data(self) -> None:
        persist_chapter_annotation(
            self.db_session,
            run_id=self.run_id,
            chapter_id=1,
            emotional_valences={0: "mild_positive", 1: "mild_negative"},
            event_types={0: "铺垫", 1: "冲突"},
            pivot_chunks={1},
            cliffhanger_chunks={0},
            characters=[
                character_fact(
                    chunk_id=0,
                    name="主角",
                    action="与反派对峙",
                    role_function="主体",
                    emotion="mild_positive",
                ),
                character_fact(
                    chunk_id=0,
                    name="反派",
                    action="阻拦主角",
                    role_function="反对者",
                    emotion="mild_negative",
                ),
            ],
            dialogues=[
                dialogue_fact(
                    chunk_id=0,
                    content="退下",
                    speaker="主角",
                    tone="愤怒",
                )
            ],
            relations=[
                relation_fact(
                    chunk_id=0,
                    from_name="主角",
                    to_name="反派",
                    relation_type="敌对",
                )
            ],
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_curves "
                "("
                "chunk_id, pos_density, neg_density, net_density, "
                "smoothed_density, tension_proxy, tension_composite, run_id"
                ") "
                "VALUES (0, 0.1, 0.05, 0.05, 0.05, 0.3, 0.25, :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_curves "
                "("
                "chunk_id, pos_density, neg_density, net_density, "
                "smoothed_density, tension_proxy, tension_composite, run_id"
                ") "
                "VALUES (1, 0.02, 0.1, -0.08, -0.06, 0.7, 0.65, :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.commit()

    def test_aggregate_returns_result(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert isinstance(result, AggregateResult)
        assert isinstance(result.narrative_structure, dict)
        assert isinstance(result.emotion_curve, dict)
        assert isinstance(result.character_relations, dict)
        assert isinstance(result.language_style, dict)
        assert isinstance(result.traditional_culture, dict)

    def test_aggregate_narrative_structure(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert "act1_ratio" in result.narrative_structure
        assert "act2_ratio" in result.narrative_structure
        assert "act3_ratio" in result.narrative_structure
        assert "climax_spacing" in result.narrative_structure
        assert "middle_collapse_index" in result.narrative_structure
        assert "cliffhanger_rate" in result.narrative_structure

    def test_aggregate_emotion_curve(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert "emotion_recovery_speed" in result.emotion_curve
        # 2026-08-14 重命名（§13.3）：pivot_moment_density → chapter_pivot_rate
        assert "chapter_pivot_rate" in result.emotion_curve
        assert "positive_ratio" in result.emotion_curve

    def test_aggregate_character_relations(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert "network_density" in result.character_relations
        assert "antagonist_strength_gap" in result.character_relations
        assert "total_changes" in result.character_relations
        assert "average_clustering" in result.character_relations
        assert "num_connected_components" in result.character_relations

    def test_aggregate_language_style(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert "vocab_breadth" in result.language_style
        assert result.language_style["tone_distribution"] == {"愤怒": 1.0}

    def test_aggregate_traditional_culture(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert "idiom_density" in result.traditional_culture
        assert "classical_sentence_ratio" in result.traditional_culture

    def test_compute_narrative_structure_metrics_aligns_annotation_and_tension_by_chunk_id(self) -> None:
        annotation_data = AnnotationData(
            chunk_ids=[0, 1, 2],
            event_types=["铺垫", "转折", "冲突"],
            cliffhangers=[0, 1, 0],
            pivot_moments=[0, 1, 0],
            emotional_valences=["neutral", "neutral", "neutral"],
        )
        tension_data = TensionData(
            chunk_ids=[0, 1, 2],
            tension_composite_scores=[0.1, None, 0.9],
        )

        result = compute_narrative_structure_metrics(annotation_data, tension_data)

        # 2026-08-14 重命名（§13.3）：event_density_{k} → chapter_narrative_function_share_{k}
        assert result["chapter_narrative_function_share_铺垫"] == 0.5
        assert result["chapter_narrative_function_share_冲突"] == 0.5
        assert result["chapter_narrative_function_share_转折"] == 0.0
        assert result["dominant_climax_pos"] == 0.5
