import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.cli.main import run_aggregate, run_annotate, run_cloud_diagnose, run_preprocess, run_topic_model
from src.storage.sqlite_db import (
    connect_db,
    create_tables,
    insert_chunk_style,
    insert_chunks,
)
from src.chunking.chunker import Chunk
from src.models.local.schema import ChunkAnnotation

from conftest import FakeClient, FakeLocalModelClient


class TestCli(unittest.TestCase):
    def test_cloud_diagnose_writes_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "novel.txt"
            source_path.write_text("测试文本", encoding="utf-8")
            db_path = Path(tmp) / "novel.db"
            analysis = run_cloud_diagnose(
                source_path=source_path,
                metadata_path=None,
                db_path=db_path,
                cache_path=None,
                client=FakeClient(),
            )
            self.assertEqual(analysis.novel_id, "novel")
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT novel_id FROM cloud_analysis").fetchone()
            conn.close()
            self.assertEqual(row[0], "novel")


class TestAnnotate(unittest.TestCase):
    def _create_test_db(self, tmp: str, chunk_count: int) -> Path:
        db_path = Path(tmp) / "test.db"
        conn = connect_db(db_path)
        create_tables(conn)
        chunks = [Chunk(index=i, start=0, end=10, text=f"测试文本{i}") for i in range(chunk_count)]
        insert_chunks(conn, chunks)
        conn.close()
        return db_path

    def test_annotate_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db(tmp, 3)
            success, errors, total = run_annotate(
                db_path=db_path,
                resume=False,
                cache_path=None,
                client=FakeLocalModelClient(),
            )
            self.assertEqual(success, 3)
            self.assertEqual(errors, 0)
            self.assertEqual(total, 3)
            conn = sqlite3.connect(db_path)
            annotation_count = conn.execute("SELECT COUNT(*) FROM chunk_annotation").fetchone()[0]
            character_count = conn.execute("SELECT COUNT(*) FROM chunk_characters").fetchone()[0]
            relation_count = conn.execute("SELECT COUNT(*) FROM chunk_relations").fetchone()[0]
            dialogue_count = conn.execute("SELECT COUNT(*) FROM chunk_dialogues").fetchone()[0]
            conn.close()
            self.assertEqual(annotation_count, 3)
            self.assertEqual(character_count, 3)
            self.assertEqual(relation_count, 3)
            self.assertEqual(dialogue_count, 3)

    def test_annotate_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db(tmp, 5)
            client = FakeLocalModelClient()
            success1, errors1, total1 = run_annotate(
                db_path=db_path,
                resume=False,
                cache_path=None,
                client=client,
            )
            self.assertEqual(success1, 5)
            conn = sqlite3.connect(db_path)
            conn.execute("DELETE FROM chunk_annotation WHERE chunk_id = 2")
            conn.execute("DELETE FROM chunk_characters WHERE chunk_id = 2")
            conn.execute("DELETE FROM chunk_relations WHERE chunk_id = 2")
            conn.execute("DELETE FROM chunk_dialogues WHERE chunk_id = 2")
            conn.commit()
            conn.close()
            success2, errors2, total2 = run_annotate(
                db_path=db_path,
                resume=True,
                cache_path=None,
                client=client,
            )
            self.assertEqual(success2, 1)
            self.assertEqual(errors2, 0)
            conn = sqlite3.connect(db_path)
            annotation_count = conn.execute("SELECT COUNT(*) FROM chunk_annotation").fetchone()[0]
            conn.close()
            self.assertEqual(annotation_count, 5)

    def test_annotate_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.db"
            conn = connect_db(db_path)
            create_tables(conn)
            conn.close()
            success, errors, total = run_annotate(
                db_path=db_path,
                resume=False,
                cache_path=None,
                client=FakeLocalModelClient(),
            )
            self.assertEqual(success, 0)
            self.assertEqual(errors, 0)
            self.assertEqual(total, 0)

    def test_annotate_disambiguation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db(tmp, 2)
            success, errors, total = run_annotate(
                db_path=db_path,
                resume=False,
                cache_path=None,
                client=FakeLocalModelClient(),
            )
            self.assertEqual(success, 2)
            conn = sqlite3.connect(db_path)
            conn.execute("INSERT INTO chunk_characters (chunk_id, name, role_function, action, emotion, emotion_score) VALUES (1, '张三丰', 'other', 'test', 'test', 0)")
            conn.commit()
            conn.close()
            success2, errors2, total2 = run_annotate(
                db_path=db_path,
                resume=True,
                cache_path=None,
                client=FakeLocalModelClient(),
            )
            conn = sqlite3.connect(db_path)
            names = [row[0] for row in conn.execute("SELECT DISTINCT name FROM chunk_characters").fetchall()]
            conn.close()
            self.assertIn("张三", names)


class TestPreprocess(unittest.TestCase):
    def test_preprocess_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "novel.txt"
            content = "第一章 开始\n\n这是测试文本。包含多个句子。对话：「你好」。"
            source_path.write_text(content, encoding="utf-8")
            db_path = Path(tmp) / "novel.db"
            chunks, chars, elapsed = run_preprocess(
                source_path=source_path,
                metadata_path=None,
                db_path=db_path,
                cache_path=None,
            )
            self.assertGreater(chunks, 0)
            self.assertGreater(chars, 0)
            self.assertGreater(elapsed, 0)
            conn = sqlite3.connect(db_path)
            chunk_rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
            style_rows = conn.execute("SELECT COUNT(*) FROM chunk_style").fetchone()
            conn.close()
            self.assertEqual(chunk_rows[0], chunks)
            self.assertEqual(style_rows[0], chunks)

    def test_preprocess_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "novels"
            source_dir.mkdir()
            (source_dir / "chapter1.txt").write_text("第一章内容。测试文本。", encoding="utf-8")
            (source_dir / "chapter2.txt").write_text("第二章内容。更多文本。", encoding="utf-8")
            db_path = Path(tmp) / "novel.db"
            chunks, chars, elapsed = run_preprocess(
                source_path=source_dir,
                metadata_path=None,
                db_path=db_path,
                cache_path=None,
            )
            self.assertGreater(chunks, 0)
            conn = sqlite3.connect(db_path)
            chunk_rows = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
            conn.close()
            self.assertEqual(chunk_rows[0], chunks)

    def test_preprocess_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "novel.txt"
            source_path.write_text("测试文本内容。", encoding="utf-8")
            metadata_path = Path(tmp) / "metadata.json"
            metadata_path.write_text('{"title": "测试小说", "author": "测试作者"}', encoding="utf-8")
            db_path = Path(tmp) / "novel.db"
            chunks, chars, elapsed = run_preprocess(
                source_path=source_path,
                metadata_path=metadata_path,
                db_path=db_path,
                cache_path=None,
            )
            self.assertGreater(chunks, 0)

    def test_preprocess_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "empty.txt"
            source_path.write_text("", encoding="utf-8")
            db_path = Path(tmp) / "novel.db"
            chunks, chars, elapsed = run_preprocess(
                source_path=source_path,
                metadata_path=None,
                db_path=db_path,
                cache_path=None,
            )
            self.assertEqual(chunks, 0)

    def test_preprocess_style_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "novel.txt"
            content = "第一章 测试\n\n这是测试文本。包含对话：「你好世界」。像梦一样美好。"
            source_path.write_text(content, encoding="utf-8")
            db_path = Path(tmp) / "novel.db"
            chunks, chars, elapsed = run_preprocess(
                source_path=source_path,
                metadata_path=None,
                db_path=db_path,
                cache_path=None,
            )
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT mtld, ttr, avg_sent_len, pause_density, dialogue_ratio, metaphor_density FROM chunk_style LIMIT 1"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertGreater(row[0], 0)
            self.assertGreater(row[1], 0)
            self.assertGreater(row[2], 0)


class TestAggregate(unittest.TestCase):
    def _create_test_db_with_chunks(self, tmp: str, chunk_count: int) -> Path:
        db_path = Path(tmp) / "test.db"
        conn = connect_db(db_path)
        try:
            create_tables(conn)
            chunks = [Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本。包含快乐和悲伤的词语。") for i in range(chunk_count)]
            insert_chunks(conn, chunks)
            style_rows = [
                (
                    i, 50.0 + i, 0.5, 20.0 + i, 5.0, 5.0, 0.1, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0,
                    "{}", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                )
                for i in range(chunk_count)
            ]
            insert_chunk_style(conn, style_rows)
        finally:
            conn.close()
        return db_path

    def test_aggregate_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_chunks(tmp, 5)
            chunks, emotion_rows, rhythm_rows = run_aggregate(db_path=db_path)
            self.assertEqual(chunks, 5)
            self.assertEqual(emotion_rows, 5)
            self.assertEqual(rhythm_rows, 5)
            conn = sqlite3.connect(db_path)
            try:
                emotion_count = conn.execute("SELECT COUNT(*) FROM emotion_curve").fetchone()[0]
                rhythm_count = conn.execute("SELECT COUNT(*) FROM rhythm_curve").fetchone()[0]
                stats_count = conn.execute("SELECT COUNT(*) FROM global_stats").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(emotion_count, 5)
            self.assertEqual(rhythm_count, 5)
            self.assertGreater(stats_count, 0)

    def test_aggregate_emotion_curve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_chunks(tmp, 3)
            run_aggregate(db_path=db_path)
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("SELECT chunk_id, pos_density, neg_density, net_density, smoothed_density FROM emotion_curve ORDER BY chunk_id").fetchall()
            finally:
                conn.close()
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertIsNotNone(row[0])
                self.assertIsInstance(row[1], float)
                self.assertIsInstance(row[2], float)
                self.assertIsInstance(row[3], float)
                self.assertIsInstance(row[4], float)

    def test_aggregate_rhythm_curve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_chunks(tmp, 3)
            run_aggregate(db_path=db_path)
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("SELECT chunk_id, tension_proxy, tension_composite FROM rhythm_curve ORDER BY chunk_id").fetchall()
            finally:
                conn.close()
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertIsNotNone(row[0])
                self.assertIsInstance(row[1], float)
                self.assertIsInstance(row[2], float)

    def test_aggregate_global_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_chunks(tmp, 5)
            run_aggregate(db_path=db_path)
            conn = sqlite3.connect(db_path)
            try:
                stats = conn.execute("SELECT stat_name, stat_value FROM global_stats").fetchall()
            finally:
                conn.close()
            stat_names = [s[0] for s in stats]
            self.assertIn("global_avg_mtld", stat_names)
            self.assertIn("global_avg_ttr", stat_names)
            self.assertIn("global_avg_sent_len", stat_names)
            self.assertIn("emotion_avg", stat_names)
            self.assertIn("emotion_std", stat_names)
            self.assertIn("emotion_max", stat_names)
            self.assertIn("emotion_min", stat_names)
            self.assertIn("rhythm_avg", stat_names)
            self.assertIn("rhythm_std", stat_names)

    def test_aggregate_with_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = connect_db(db_path)
            try:
                create_tables(conn)
                test_chunks = [Chunk(index=i, start=0, end=100, text=f"测试文本{i}") for i in range(3)]
                insert_chunks(conn, test_chunks)
                style_rows = [
                    (
                        i, 50.0, 0.5, 20.0, 5.0, 5.0, 0.1, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0,
                        "{}", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                    )
                    for i in range(3)
                ]
                insert_chunk_style(conn, style_rows)
                from src.storage.sqlite_db import insert_chunk_annotation
                for i in range(3):
                    annotation = ChunkAnnotation(
                        emotional_valence="positive",
                        event_type="高潮" if i == 0 else "日常",
                        pivot_moment=(i == 0),
                        cliffhanger=(i == 2),
                        has_foreshadowing=False,
                        foreshadowing_type="null",
                        foreshadowing_desc="",
                        characters=[],
                        relations=[],
                        dialogues=[],
                    )
                    insert_chunk_annotation(conn, i, annotation)
            finally:
                conn.close()
            chunks, emotion_rows, rhythm_rows = run_aggregate(db_path=db_path)
            self.assertEqual(chunks, 3)
            conn = sqlite3.connect(db_path)
            try:
                rhythm_data = conn.execute("SELECT tension_composite FROM rhythm_curve").fetchall()
            finally:
                conn.close()
            self.assertEqual(len(rhythm_data), 3)

    def test_aggregate_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.db"
            conn = connect_db(db_path)
            try:
                create_tables(conn)
            finally:
                conn.close()
            chunks, emotion_rows, rhythm_rows = run_aggregate(db_path=db_path)
            self.assertEqual(chunks, 0)
            self.assertEqual(emotion_rows, 0)
            self.assertEqual(rhythm_rows, 0)


class TestTopicModel(unittest.TestCase):
    def _create_test_db_with_chunks(self, tmp: str, chunk_count: int) -> Path:
        db_path = Path(tmp) / "test.db"
        conn = connect_db(db_path)
        try:
            create_tables(conn)
            test_texts = [
                "修仙者在修炼过程中需要不断提升境界，从炼气期到筑基期，再到金丹期和元婴期。"
                "每一次突破都需要大量的灵气和机缘，修炼之路充满艰辛与挑战。",
                "战斗是修仙者不可避免的命运。在仙侠世界中，弱肉强食是永恒的法则。"
                "为了保护自己的宗门和亲人，主角必须不断提升自己的战斗力。",
                "炼丹是修仙者必备的技能之一。通过炼制丹药，可以辅助修炼，提升修为。"
                "炼丹师在仙侠世界中备受尊敬，因为他们掌握着珍贵的炼丹秘术。",
                "法宝是修仙者的重要武器。一把好的法宝可以大幅提升战斗力。"
                "主角在冒险中获得了上古传承的法宝，从此踏上了强者之路。",
                "宗门是修仙者的根基。一个强大的宗门可以提供资源和保护。"
                "主角所在的宗门虽然没落，但通过努力，逐渐恢复了往日的辉煌。",
                "机缘是修仙者成功的关键。在仙侠世界中，机遇往往决定命运。"
                "主角在一次意外中获得了上古传承，从此改变了命运轨迹。",
                "境界是修仙者实力的体现。每个境界之间有着巨大的差距。"
                "突破境界需要悟性和机缘，失败意味着修为倒退甚至死亡。",
                "灵气是修仙的基础能量。灵气充沛的地方适合修炼。"
                "主角在一处灵气充沛的洞府中闭关修炼，终于突破了瓶颈。",
                "仙侠世界充满了神秘和危险。各种妖兽和魔修潜伏在暗处。"
                "主角在历练中不断成长，最终成为一代强者。",
                "传承是修仙者获取功法的重要途径。上古传承往往蕴含着强大的秘术。"
                "主角获得的传承让他在修炼之路上事半功倍。",
                "悟道是修仙者追求的终极目标。只有悟道才能飞升仙界。"
                "主角在生死之间顿悟，终于踏上了飞升之路。",
            ]
            chunks = [
                Chunk(
                    index=i,
                    start=0,
                    end=100,
                    text=test_texts[i % len(test_texts)],
                )
                for i in range(chunk_count)
            ]
            insert_chunks(conn, chunks)
        finally:
            conn.close()
        return db_path

    def test_topic_model_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_chunks(tmp, 10)
            chunks, topics = run_topic_model(
                db_path=db_path,
                num_topics=3,
                passes=5,
                iterations=50,
                top_n=3,
                force=False,
                cache_path=None,
            )
            self.assertEqual(chunks, 10)
            self.assertEqual(topics, 3)
            conn = sqlite3.connect(db_path)
            try:
                topic_count = conn.execute("SELECT COUNT(*) FROM chunk_topics").fetchone()[0]
            finally:
                conn.close()
            self.assertGreater(topic_count, 0)

    def test_topic_model_force_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._create_test_db_with_chunks(tmp, 5)
            chunks1, topics1 = run_topic_model(
                db_path=db_path,
                num_topics=2,
                passes=5,
                iterations=50,
                top_n=2,
                force=False,
                cache_path=None,
            )
            self.assertEqual(chunks1, 5)
            chunks2, topics2 = run_topic_model(
                db_path=db_path,
                num_topics=2,
                passes=5,
                iterations=50,
                top_n=2,
                force=False,
                cache_path=None,
            )
            self.assertEqual(chunks2, 0)
            chunks3, topics3 = run_topic_model(
                db_path=db_path,
                num_topics=2,
                passes=5,
                iterations=50,
                top_n=2,
                force=True,
                cache_path=None,
            )
            self.assertEqual(chunks3, 5)

    def test_topic_model_empty_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "empty.db"
            conn = connect_db(db_path)
            try:
                create_tables(conn)
            finally:
                conn.close()
            chunks, topics = run_topic_model(
                db_path=db_path,
                num_topics=3,
                passes=5,
                iterations=50,
                top_n=3,
                force=False,
                cache_path=None,
            )
            self.assertEqual(chunks, 0)
            self.assertEqual(topics, 0)


if __name__ == "__main__":
    unittest.main()
