"""
测试知识图谱和 RAG 模块的日志输出

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 Repository 替代 operations 函数

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SessionFactory 替代 connect_db/create_tables
"""
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from loguru import logger

from src.config import setup_logging
from src.storage.session import SessionFactory
from src.storage.repositories import (
    EntityRepository,
    ChunkRepository,
    AnnotationRepository,
    StatsRepository,
)
from src.chunking.chunker import Chunk
from src.knowledge import build_character_graph, save_graph_to_db, load_graph_from_db
from src.rag import RAGRetriever
import networkx as nx


def make_chunk(idx: int, text: str = "测试文本") -> Chunk:
    return Chunk(index=idx, start=0, end=len(text), text=text)


def main():
    setup_logging(debug=True)

    tmp = tempfile.TemporaryDirectory()

    logger.info("=" * 60)
    logger.info("测试知识图谱和 RAG 模块日志")
    logger.info("=" * 60)

    session_factory = SessionFactory(Path(tmp.name))
    db_session = session_factory.get_session("test_run", init_tables=True)
    conn = db_session.connection
    run_id = "test_run"

    chunk_repo = ChunkRepository(conn)
    entity_repo = EntityRepository(conn)
    ann_repo = AnnotationRepository(conn)
    stats_repo = StatsRepository(conn)

    logger.info("\n--- 1. 插入测试数据 ---")
    chunk_repo.insert_chunks([make_chunk(0, "李玄修炼"), make_chunk(5, "陈峰协助李玄")], run_id)

    ann_repo.insert_chunk_characters(
        run_id,
        0,
        [
            type("obj", (object,), {"name": "李玄", "role_function": "protagonist", "action": "修炼", "emotion": "平静", "emotion_score": 0})(),
        ],
    )
    ann_repo.insert_chunk_characters(
        run_id,
        5,
        [
            type("obj", (object,), {"name": "陈峰", "role_function": "helper", "action": "协助", "emotion": "坚定", "emotion_score": 1})(),
        ],
    )
    ann_repo.insert_chunk_relations(
        run_id,
        5,
        [
            type("obj", (object,), {"from_name": "李玄", "to_name": "陈峰", "type": "盟友", "change": "新建"})(),
        ],
    )

    entity_id = entity_repo.insert_entity("test_novel", "李玄", "character", first_chunk=0, description="青云宗弟子", run_id=run_id)
    entity_repo.insert_entity_alias(entity_id, "那人", "pronoun", 3)
    logger.info("测试数据插入完成")

    logger.info("\n--- 2. 测试知识图谱构建 ---")
    G = build_character_graph(entity_repo, run_id, "test_novel")
    logger.info(f"图谱节点数: {G.number_of_nodes()}, 边数: {G.number_of_edges()}")

    logger.info("\n--- 3. 测试图谱持久化 ---")
    save_graph_to_db(stats_repo, run_id, G, "test_graph")
    G2 = load_graph_from_db(stats_repo, run_id, "test_graph")
    logger.info(f"加载的图谱节点数: {G2.number_of_nodes() if G2 else 0}")

    logger.info("\n--- 4. 测试 RAG 检索 ---")
    test_graph = nx.Graph()
    test_graph.add_node(
        "李玄",
        canonical_name="李玄",
        aliases=["那人"],
        first_seen=0,
        last_seen=5,
        active_chunks=[0, 3, 5],
    )

    retriever = RAGRetriever(conn, "test_novel", test_graph, run_id=run_id)

    logger.info("\n测试 Level1 精确匹配:")
    result1 = retriever.retrieve("那人", current_chunk=5)
    logger.info(f"  结果: level1_hit={result1.level1_hit}, canonical={result1.canonical_name}")

    logger.info("\n测试 Level2 图谱约束:")
    result2 = retriever.retrieve("未知别名", current_chunk=5)
    logger.info(f"  结果: level2_candidates={result2.level2_candidates}")

    logger.info("\n测试已知别名格式化:")
    formatted = retriever.format_known_aliases_for_prompt()
    logger.info(f"  格式化结果:\n{formatted}")

    conn.close()
    tmp.cleanup()

    logger.info("\n" + "=" * 60)
    logger.info("所有测试完成!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
