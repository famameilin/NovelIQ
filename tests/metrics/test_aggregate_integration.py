"""
Aggregate metrics integration tests.
"""

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.aggregate import AggregateResult, aggregate_all_metrics
from src.storage.repositories import AnnotationRepository, ChunkRepository, RunRepository, StatsRepository


class TestAggregateAllMetrics:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

        self._populate_test_data()

    def _populate_test_data(self) -> None:
        self.db_session.execute(
            text("INSERT INTO chunks (chunk_id, text, run_id) VALUES (0, '测试文本一心一意', :run_id)"),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text("INSERT INTO chunks (chunk_id, text, run_id) VALUES (1, '此乃天意也。', :run_id)"),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_annotation "
                "(chunk_id, event_type, cliffhanger, pivot_moment, emotional_valence, run_id) "
                "VALUES (0, '铺垫', 1, 0, 'mild_positive', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_annotation "
                "(chunk_id, event_type, cliffhanger, pivot_moment, emotional_valence, run_id) "
                "VALUES (1, '冲突', 0, 1, 'mild_negative', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_characters "
                "(chunk_id, name, role_function, action_type, emotion_score, run_id) "
                "VALUES (0, '主角', '主体', '对话', 'mild_positive', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_characters "
                "(chunk_id, name, role_function, action_type, emotion_score, run_id) "
                "VALUES (0, '反派', '反对者', '战斗', 'mild_negative', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_relations "
                "(chunk_id, from_char, to_char, type, change, run_id) "
                "VALUES (0, '主角', '反派', '敌对', '强化', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_dialogues (chunk_id, speaker, tone, run_id) "
                "VALUES (0, '主角', '强硬', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_curves "
                "(chunk_id, pos_density, neg_density, net_density, smoothed_density, tension_proxy, tension_composite, run_id) "
                "VALUES (0, 0.1, 0.05, 0.05, 0.05, 0.3, 0.25, :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text(
                "INSERT INTO chunk_curves "
                "(chunk_id, pos_density, neg_density, net_density, smoothed_density, tension_proxy, tension_composite, run_id) "
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
        assert "pivot_moment_density" in result.emotion_curve
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
        assert result.language_style["tone_distribution"] == {"强硬": 1.0}

    def test_aggregate_traditional_culture(self) -> None:
        ann_repo = AnnotationRepository(self.db_session)
        chunk_repo = ChunkRepository(self.db_session)
        stats_repo = StatsRepository(self.db_session)
        result = aggregate_all_metrics(self.run_id, ann_repo, chunk_repo, stats_repo)
        assert "idiom_density" in result.traditional_culture
        assert "classical_sentence_ratio" in result.traditional_culture
