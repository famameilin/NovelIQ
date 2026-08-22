"""
CLI topic model 模块测试（段落粒度，设计 §11.1）

创建时间: 2025-03-11
任务: 测试主题建模流程

修改时间: 2026-03-15
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

修改时间: 2026-03-15
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入

修改时间: 2026-03-15
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SessionFactory 依赖

修改时间: 2026-08-14
任务: paragraph-granularity
修改内容: 主题文档使用段落（paragraphs 是唯一事实源），写入 paragraph_topics
"""

import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.preprocess.tokenize import tokenize
from src.storage.repositories import ChapterRepository, ParagraphRepository, RunRepository
from src.workflows.topic import run_topic_model
from tests.support.analysis_factories import insert_test_novel

_TEST_TEXTS = [
    "修仙者在修炼过程中需要不断提升境界，从炼气期到筑基期，再到金丹期和元婴期。"
    "每一次突破都需要大量的灵气和机缘，修炼之路充满艰辛与挑战。",
    "战斗是修仙者不可避免的命运。在仙侠世界中，弱肉强食是永恒的法则。"
    "为了保护自己的宗门和亲人，主角必须不断提升自己的战斗力。",
    "炼丹是修仙者必备的技能之一。通过炼制丹药，可以辅助修炼，提升修为。"
    "炼丹师在仙侠世界中备受尊敬，因为他们掌握着珍贵的炼丹秘术。",
    "法宝是修仙者的重要武器。一把好的法宝可以大幅提升战斗力。主角在冒险中获得了上古传承的法宝，从此踏上了强者之路。",
    "宗门是修仙者的根基。一个强大的宗门可以提供资源和保护。主角所在的宗门虽然没落，但通过努力，逐渐恢复了往日的辉煌。",
    "机缘是修仙者成功的关键。在仙侠世界中，机遇往往决定命运。主角在一次意外中获得了上古传承，从此改变了命运轨迹。",
    "境界是修仙者实力的体现。每个境界之间有着巨大的差距。突破境界需要悟性和机缘，失败意味着修为倒退甚至死亡。",
    "灵气是修仙的基础能量。灵气充沛的地方适合修炼。主角在一处灵气充沛的洞府中闭关修炼，终于突破了瓶颈。",
    "仙侠世界充满了神秘和危险。各种妖兽和魔修潜伏在暗处。主角在历练中不断成长，最终成为一代强者。",
    "传承是修仙者获取功法的重要途径。上古传承往往蕴含着强大的秘术。主角获得的传承让他在修炼之路上事半功倍。",
    "悟道是修仙者追求的终极目标。只有悟道才能飞升仙界。主角在生死之间顿悟，终于踏上了飞升之路。",
]


class TestTopicModel:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_paragraphs(self, paragraph_count: int) -> None:
        """每个章节插入一个段落，构造 paragraphs 唯一事实源测试数据"""
        chapter_repo = ChapterRepository(self.db_session)
        chapters = [
            Chunk(
                index=i,
                start=i * 1000,
                end=i * 1000 + len(_TEST_TEXTS[i % len(_TEST_TEXTS)]),
                text=_TEST_TEXTS[i % len(_TEST_TEXTS)],
                chapter_id=i + 1,
            )
            for i in range(paragraph_count)
        ]
        chapter_repo.insert_chapter_texts(self.run_id, chapters)

        spans = [replace(span, token_count=len(tokenize(span.text))) for span in split_chunk_paragraphs(chapters)]
        ParagraphRepository(self.db_session).insert_paragraphs(self.run_id, spans)

    def _count_paragraph_topics(self) -> int:
        count = self.db_session.execute(
            text("SELECT COUNT(*) FROM paragraph_topics WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        return int(count or 0)

    @pytest.mark.asyncio()
    async def test_topic_model_basic(self) -> None:
        self._create_paragraphs(10)

        paragraphs, topics = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=3,
            passes=5,
            iterations=50,
            top_n=3,
            force=False,
        )
        assert paragraphs == 10
        assert topics == 3
        assert self._count_paragraph_topics() > 0

        # 每段写入 (paragraph_id, topic_id, topic_weight, inference_token_count)
        topic_rows = ParagraphRepository(self.db_session).fetch_paragraph_topics(self.run_id)
        assert len(topic_rows) > 0
        assert all(row.inference_token_count > 0 for row in topic_rows)

        paragraph_rows = ParagraphRepository(self.db_session).fetch_paragraph_rows(self.run_id)
        token_counts = {row.paragraph_id: row.token_count for row in paragraph_rows}
        assert all(row.inference_token_count == token_counts[row.paragraph_id] for row in topic_rows)

    @pytest.mark.asyncio()
    async def test_short_paragraph_is_inferred_but_excluded_from_training(self, monkeypatch) -> None:
        self._create_paragraphs(2)
        paragraph_repo = ParagraphRepository(self.db_session)
        rows = list(paragraph_repo.fetch_paragraph_rows(self.run_id))
        short_row = rows[0]
        self.db_session.execute(
            text(
                "UPDATE paragraphs SET token_count = :token_count "
                "WHERE run_id = :run_id AND paragraph_id = :paragraph_id"
            ),
            {"token_count": 1, "run_id": self.run_id, "paragraph_id": short_row.paragraph_id},
        )

        captured_docs: list[list[list[str]]] = []

        from src.topic.lda_model import LDATrainer

        original_train = LDATrainer.train

        def capture_train(self, tokenized_docs, *args, **kwargs):
            """2026-08-20 捕获实际送入 LDA 训练的段落文档"""
            captured_docs.append(tokenized_docs)
            return original_train(self, tokenized_docs, *args, **kwargs)

        monkeypatch.setattr(LDATrainer, "train", capture_train)
        paragraphs, topics = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=1,
            iterations=10,
            top_n=2,
        )

        assert paragraphs == 2
        assert topics == 2
        assert len(captured_docs) == 1
        assert len(captured_docs[0]) == 1
        topic_rows = paragraph_repo.fetch_paragraph_topics(self.run_id)
        short_topic_rows = [row for row in topic_rows if row.paragraph_id == short_row.paragraph_id]
        assert short_topic_rows
        assert all(row.inference_token_count == 1 for row in short_topic_rows)

    @pytest.mark.asyncio()
    async def test_topic_model_force_rerun(self) -> None:
        self._create_paragraphs(5)

        paragraphs1, topics1 = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=5,
            iterations=50,
            top_n=2,
            force=False,
        )
        assert paragraphs1 == 5
        assert topics1 == 2
        assert self._count_paragraph_topics() > 0

        paragraphs2, topics2 = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=5,
            iterations=50,
            top_n=2,
            force=False,
        )
        assert paragraphs2 == 5
        assert topics2 == 2
        assert self._count_paragraph_topics() > 0

        paragraphs3, topics3 = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=5,
            iterations=50,
            top_n=2,
            force=True,
        )
        assert paragraphs3 == 5
        assert topics3 == 2
        assert self._count_paragraph_topics() > 0

    @pytest.mark.asyncio()
    async def test_topic_model_empty_db(self) -> None:
        paragraphs, topics = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=3,
            passes=5,
            iterations=50,
            top_n=3,
            force=False,
        )
        assert paragraphs == 0
        assert topics == 0
