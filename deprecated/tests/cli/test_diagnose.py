import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.cli.main import run_local_diagnose, run_diagnose
from src.models.cloud import build_diagnosis_payload
from src.storage.sqlite_db import (
    connect_db,
    create_tables,
    insert_chunk_style,
    insert_chunks,
    insert_chunk_annotation,
    insert_chunk_relations,
    fetch_pivot_blocks,
    fetch_high_tension_chunks,
    fetch_relation_changes,
    fetch_foreshadowing_chunks,
    fetch_first_last_chunk_summary,
    fetch_pivot_moments,
)
from src.chunking.chunker import Chunk
from src.models.local.schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    RelationChangeSnapshot,
)

from conftest import FakeClient


class TestRunDiagnose(unittest.TestCase):
    def _create_test_db_with_aggregated_data(self, tmp: str, chunk_count: int) -> Path:
        db_path = Path(tmp) / "test.db"
        conn = connect_db(db_path)
        try:
            create_tables(conn)
            chunks = [Chunk(index=i, start=0, end=100, text=f"测试文本{i}") for i in range(chunk_count)]
            insert_chunks(conn, chunks)
            style_rows = [
                (
                    i, 50.0 + i, 0.5, 20.0 + i, 5.0, 5.0, 0.1, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0,
                    "{}", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                )
                for i in range(chunk_count)
            ]
            insert_chunk_style(conn, style_rows)
            for i in range(chunk_count):
                conn.execute(
                    "INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density) VALUES (?, ?, ?, ?, ?)",
                    (i, 0.1, 0.05, 0.05, 0.05),
                )
                conn.execute(
                    "INSERT INTO rhythm_curve (chunk_id, tension_proxy, tension_composite) VALUES (?, ?, ?)",
                    (i, 0.5, 0.5),
                )
            conn.execute(
                "INSERT INTO global_stats (stat_name, stat_value) VALUES (?, ?)",
                ("emotion_avg", 0.05),
            )
            conn.commit()
        finally:
            conn.close()
        return db_path

    def test_local_diagnose_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_aggregated_data(tmp, 3)
            total_chunks, stats_count = run_local_diagnose(db_path=db_path)
            self.assertEqual(total_chunks, 3)
            self.assertGreater(stats_count, 0)

    def test_local_diagnose_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.db"
            conn = connect_db(db_path)
            create_tables(conn)
            conn.close()
            total_chunks, stats_count = run_local_diagnose(db_path=db_path)
            self.assertEqual(total_chunks, 0)
            self.assertEqual(stats_count, 0)


class TestCloudDiagnose(unittest.TestCase):
    def _create_test_db_with_full_data(self, tmp: str, chunk_count: int = 5) -> Path:
        db_path = Path(tmp) / "test.db"
        conn = connect_db(db_path)
        try:
            create_tables(conn)
            chunks = [Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本，包含一些内容。") for i in range(chunk_count)]
            insert_chunks(conn, chunks)
            style_rows = [
                (
                    i, 50.0 + i, 0.5, 20.0 + i, 5.0, 5.0, 0.1, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0,
                    "{}", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                )
                for i in range(chunk_count)
            ]
            insert_chunk_style(conn, style_rows)
            for i in range(chunk_count):
                conn.execute(
                    "INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density) VALUES (?, ?, ?, ?, ?)",
                    (i, 0.1, 0.05, 0.05 + i * 0.01, 0.05),
                )
                conn.execute(
                    "INSERT INTO rhythm_curve (chunk_id, tension_proxy, tension_composite) VALUES (?, ?, ?)",
                    (i, 0.5, 0.5),
                )
            for i in range(chunk_count):
                annotation = ChunkAnnotation(
                    emotional_valence="positive" if i % 2 == 0 else "negative",
                    event_type="高潮" if i == 2 else ("转折" if i == 1 else "日常"),
                    pivot_moment=(i in [1, 2]),
                    cliffhanger=(i == chunk_count - 1),
                    has_foreshadowing=(i == 0),
                    foreshadowing_type="causal" if i == 0 else "null",
                    foreshadowing_desc="测试伏笔" if i == 0 else "",
                    characters=[
                        CharacterSnapshot(
                            name=f"角色{i}",
                            role_function="protagonist" if i == 0 else "other",
                            action="测试行为",
                            emotion="平静",
                            emotion_score=0,
                        )
                    ],
                    relations=[
                        RelationChangeSnapshot(
                            from_name="角色A",
                            to_name="角色B",
                            type="盟友",
                            change="新建",
                        )
                    ],
                    dialogues=[],
                )
                insert_chunk_annotation(conn, i, annotation)
                if annotation.relations:
                    insert_chunk_relations(conn, i, annotation.relations)
            conn.commit()
        finally:
            conn.close()
        return db_path

    def test_build_diagnosis_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            payload = build_diagnosis_payload(conn, "test_novel")
            conn.close()
            
            self.assertEqual(payload["novel_id"], "test_novel")
            self.assertIn("pivot_blocks", payload)
            self.assertIn("pivot_moments", payload)
            self.assertIn("high_tension_paragraphs", payload)
            self.assertIn("character_relations", payload)
            self.assertIn("foreshadowing_list", payload)
            self.assertIn("first_chapter_summary", payload)
            self.assertIn("last_chapter_summary", payload)
            
            self.assertGreater(len(payload["pivot_blocks"]), 0)
            self.assertGreater(len(payload["pivot_moments"]), 0)
            self.assertGreater(len(payload["foreshadowing_list"]), 0)

    def test_fetch_pivot_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            blocks = fetch_pivot_blocks(conn)
            conn.close()
            self.assertGreater(len(blocks), 0)
            for block in blocks:
                self.assertEqual(len(block), 3)

    def test_fetch_high_tension_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            chunks = fetch_high_tension_chunks(conn, limit=3)
            conn.close()
            self.assertGreater(len(chunks), 0)
            for chunk in chunks:
                self.assertEqual(len(chunk), 3)

    def test_fetch_relation_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            relations = fetch_relation_changes(conn)
            conn.close()
            self.assertGreater(len(relations), 0)
            for rel in relations:
                self.assertEqual(len(rel), 5)

    def test_fetch_foreshadowing_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            chunks = fetch_foreshadowing_chunks(conn)
            conn.close()
            self.assertGreater(len(chunks), 0)

    def test_fetch_first_last_chunk_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            first, last = fetch_first_last_chunk_summary(conn)
            conn.close()
            self.assertGreater(len(first), 0)
            self.assertGreater(len(last), 0)

    def test_fetch_pivot_moments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            conn = connect_db(db_path)
            moments = fetch_pivot_moments(conn)
            conn.close()
            self.assertGreater(len(moments), 0)

    def test_run_diagnose_with_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 5)
            analysis = run_diagnose(
                db_path=db_path,
                cache_path=None,
                client=FakeClient(),
            )
            self.assertIsNotNone(analysis)
            self.assertEqual(analysis.narrative_type, "三幕")
            self.assertEqual(analysis.foreshadow_rate, 0.1)
            
            conn = connect_db(db_path)
            rows = conn.execute("SELECT COUNT(*) FROM cloud_analysis").fetchone()
            conn.close()
            self.assertGreater(rows[0], 0)

    def test_run_diagnose_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_full_data(tmp, 3)
            run_diagnose(
                db_path=db_path,
                cache_path=None,
                client=FakeClient(),
            )
            conn = connect_db(db_path)
            rows = conn.execute("SELECT novel_id, narrative_type, foreshadow_rate FROM cloud_analysis").fetchall()
            conn.close()
            self.assertGreater(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
