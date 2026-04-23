"""
CLI topic model 模块测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试主题建模流程

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SessionFactory 依赖
"""

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk
from src.storage.models import Novel
from src.storage.repositories import ChunkRepository, RunRepository
from src.workflows.topic import run_topic_model


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation。

    创建时间: 2026-04-23
    任务: 修复 pytest ForeignKeyViolation
    """
    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


class TestTopicModel:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, self.novel_id)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_chunks(self, chunk_count: int) -> None:
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
            "境界是修仙者实力的体现。每个境界之间有着巨大的差距。突破境界需要悟性和机缘，失败意味着修为倒退甚至死亡。",
            "灵气是修仙的基础能量。灵气充沛的地方适合修炼。主角在一处灵气充沛的洞府中闭关修炼，终于突破了瓶颈。",
            "仙侠世界充满了神秘和危险。各种妖兽和魔修潜伏在暗处。主角在历练中不断成长，最终成为一代强者。",
            "传承是修仙者获取功法的重要途径。上古传承往往蕴含着强大的秘术。主角获得的传承让他在修炼之路上事半功倍。",
            "悟道是修仙者追求的终极目标。只有悟道才能飞升仙界。主角在生死之间顿悟，终于踏上了飞升之路。",
        ]
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [
            Chunk(
                index=i,
                start=0,
                end=100,
                text=test_texts[i % len(test_texts)],
            )
            for i in range(chunk_count)
        ]
        chunk_repo.insert_chunks(self.run_id, chunks)

    @pytest.mark.asyncio()
    async def test_topic_model_basic(self) -> None:
        self._create_chunks(10)

        chunks, topics = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=3,
            passes=5,
            iterations=50,
            top_n=3,
            force=False,
        )
        assert chunks == 10
        assert topics == 3

        topic_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_topics WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert topic_count > 0

    @pytest.mark.asyncio()
    async def test_topic_model_force_rerun(self) -> None:
        self._create_chunks(5)

        chunks1, topics1 = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=5,
            iterations=50,
            top_n=2,
            force=False,
        )
        assert chunks1 == 5
        assert topics1 == 2

        topic_count1 = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_topics WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert topic_count1 > 0

        chunks2, topics2 = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=5,
            iterations=50,
            top_n=2,
            force=False,
        )
        assert chunks2 == 5

        topic_count2 = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_topics WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert topic_count2 > 0

        chunks3, topics3 = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=2,
            passes=5,
            iterations=50,
            top_n=2,
            force=True,
        )
        assert chunks3 == 5
        assert topics3 == 2

    @pytest.mark.asyncio()
    async def test_topic_model_empty_db(self) -> None:
        chunks, topics = await run_topic_model(
            run_id=self.run_id,
            session=self.db_session,
            num_topics=3,
            passes=5,
            iterations=50,
            top_n=3,
            force=False,
        )
        assert chunks == 0
        assert topics == 0
