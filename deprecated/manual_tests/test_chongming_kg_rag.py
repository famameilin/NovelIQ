"""
使用重明传真实数据测试知识图谱和 RAG 模块

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SessionFactory 替代 connect_db/create_tables
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from loguru import logger

from src.config import setup_logging
from src.storage.session import SessionFactory
from src.storage.repositories import EntityRepository, StatsRepository
from src.knowledge import build_character_graph, save_graph_to_db, load_graph_from_db, get_active_nodes_in_range
from src.knowledge.graph import get_all_known_aliases
from src.rag import RAGRetriever


def main():
    setup_logging(debug=True)
    
    db_path = Path("data/uploads/edb29e21_重明传.db")
    if not db_path.exists():
        logger.error(f"数据库不存在: {db_path}")
        return
    
    logger.info("=" * 60)
    logger.info("重明传知识图谱和 RAG 测试")
    logger.info("=" * 60)
    
    session_factory = SessionFactory()
    db_session = session_factory.get_session(init_tables=True)
    conn = db_session.connection
    
    from sqlalchemy import text
    
    cursor = conn.execute(text("SELECT COUNT(*) FROM chunks"))
    chunks_count = cursor.fetchone()[0]
    cursor = conn.execute(text("SELECT COUNT(*) FROM chunk_characters"))
    cc_count = cursor.fetchone()[0]
    cursor = conn.execute(text("SELECT COUNT(*) FROM chunk_relations"))
    cr_count = cursor.fetchone()[0]
    
    logger.info(f"数据统计: chunks={chunks_count}, chunk_characters={cc_count}, chunk_relations={cr_count}")
    
    entity_repo = EntityRepository(conn)
    stats_repo = StatsRepository(conn)
    
    logger.info("\n--- 1. 构建知识图谱 ---")
    G = build_character_graph(entity_repo, "default")
    
    logger.info(f"图谱节点数: {G.number_of_nodes()}")
    logger.info(f"图谱边数: {G.number_of_edges()}")
    
    logger.info("\n示例节点属性:")
    for i, (node, attrs) in enumerate(G.nodes(data=True)):
        if i >= 5:
            break
        logger.info(f"  {node}: first_seen={attrs.get('first_seen')}, last_seen={attrs.get('last_seen')}, aliases={attrs.get('aliases', [])[:3]}")
    
    logger.info("\n示例边属性:")
    for i, (u, v, attrs) in enumerate(G.edges(data=True)):
        if i >= 5:
            break
        logger.info(f"  {u} -> {v}: type={attrs.get('type')}, first_seen={attrs.get('first_seen')}, last_seen={attrs.get('last_seen')}")
    
    logger.info("\n--- 2. 测试活跃节点查询 ---")
    active = get_active_nodes_in_range(G, 0, 50)
    logger.info(f"chunk 0-50 活跃节点: {active[:10]}...")
    
    logger.info("\n--- 3. 测试图谱持久化 ---")
    save_graph_to_db(stats_repo, "default", G, "test_chongming_graph")
    G2 = load_graph_from_db(stats_repo, "default", "test_chongming_graph")
    logger.info(f"加载的图谱节点数: {G2.number_of_nodes() if G2 else 0}")
    
    logger.info("\n--- 4. 测试 RAG 检索 ---")
    retriever = RAGRetriever(conn, "default", G)
    
    aliases = get_all_known_aliases(G)
    logger.info(f"已知别名数量: {len(aliases)}")
    if aliases:
        sample = list(aliases.items())[:5]
        logger.info(f"示例别名: {sample}")
    
    logger.info("\n测试 Level2 图谱约束:")
    result = retriever.retrieve("未知角色", current_chunk=100)
    logger.info(f"  Level2 candidates: {result.level2_candidates[:10]}")
    logger.info(f"  Used levels: {result.used_levels}")
    
    logger.info("\n测试已知别名格式化:")
    formatted = retriever.format_known_aliases_for_prompt()
    if formatted:
        logger.info(f"  格式化结果 (前500字符):\n{formatted[:500]}...")
    
    conn.close()
    
    logger.info("\n" + "=" * 60)
    logger.info("测试完成!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
