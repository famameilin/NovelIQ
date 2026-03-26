from __future__ import annotations

import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.cli.commands import (
    run_preprocess,
    run_annotate,
    run_aggregate,
    run_topic_model,
    run_diagnose,
)
from src.storage.sqlite_db import connect_db, create_tables
from src.metrics.aggregate_metrics import aggregate_all_metrics


def analyze_chongmingzhuan():
    source_path = project_root / "data" / "novel" / "重明传.txt"
    db_path = project_root / "data" / "uploads" / "重明传.db"
    output_path = project_root / "重明传.json"
    
    if not source_path.exists():
        logger.error(f"Source file not found: {source_path}")
        return
    
    logger.info(f"开始分析《重明传》...")
    logger.info(f"源文件: {source_path}")
    logger.info(f"数据库: {db_path}")
    logger.info(f"Chunk大小: 500字")
    
    if db_path.exists():
        logger.info(f"删除现有数据库...")
        db_path.unlink()
        topic_model_dir = db_path.parent / f"{db_path.stem}_topic_model"
        if topic_model_dir.exists():
            import shutil
            shutil.rmtree(topic_model_dir)
    
    logger.info("\n=== 阶段1: 预处理 ===")
    total_chunks, total_chars, elapsed = run_preprocess(
        source_path=source_path,
        db_path=db_path,
        max_chars=500,
        overlap=50,
    )
    logger.info(f"预处理完成: {total_chunks} chunks, {total_chars} 字符, {elapsed:.2f}s")
    
    logger.info("\n=== 阶段2: 标注 ===")
    success_count, error_count, total = run_annotate(
        db_path=db_path,
        resume=True,
    )
    logger.info(f"标注完成: 成功 {success_count}, 失败 {error_count}, 总计 {total}")
    
    logger.info("\n=== 阶段3: 聚合 ===")
    total_chunks, emotion_rows, rhythm_rows = run_aggregate(db_path=db_path)
    logger.info(f"聚合完成: {total_chunks} chunks, {emotion_rows} 情感曲线, {rhythm_rows} 节奏曲线")
    
    logger.info("\n=== 阶段4: 主题模型 ===")
    total_chunks, num_topics = run_topic_model(
        db_path=db_path,
        num_topics=10,
        passes=10,
        iterations=500,
    )
    logger.info(f"主题模型完成: {total_chunks} chunks, {num_topics} 主题")
    
    logger.info("\n=== 阶段5: 诊断 ===")
    try:
        result = run_diagnose(db_path=db_path)
        logger.info(f"诊断完成: {result.narrative_type}")
    except Exception as e:
        logger.warning(f"诊断阶段跳过: {e}")
    
    logger.info("\n=== 获取分析结果 ===")
    results = fetch_results(db_path)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    logger.info(f"\n结果已保存到: {output_path}")
    return results


def fetch_results(db_path: Path) -> dict:
    conn = connect_db(db_path)
    try:
        results = {}
        
        cursor = conn.execute("SELECT COUNT(*), SUM(LENGTH(text)) FROM chunks")
        row = cursor.fetchone()
        results["total_chunks"] = row[0] if row else 0
        results["total_chars"] = int(row[1]) if row and row[1] else 0
        
        cursor = conn.execute("""
            SELECT chunk_id, pos_density, neg_density, net_density, smoothed_density
            FROM emotion_curve ORDER BY chunk_id
        """)
        results["emotion_curve"] = [
            {
                "chunk_id": row[0],
                "pos_density": row[1],
                "neg_density": row[2],
                "net_density": row[3],
                "smoothed_density": row[4],
            }
            for row in cursor.fetchall()
        ]
        
        cursor = conn.execute("""
            SELECT chunk_id, tension_proxy, tension_composite
            FROM rhythm_curve ORDER BY chunk_id
        """)
        results["rhythm_curve"] = [
            {
                "chunk_id": row[0],
                "tension_proxy": row[1],
                "tension_composite": row[2],
            }
            for row in cursor.fetchall()
        ]
        
        cursor = conn.execute("""
            SELECT name, COUNT(*) as count, role_function, AVG(emotion_score) as avg_score
            FROM chunk_characters
            GROUP BY name
            ORDER BY count DESC
            LIMIT 50
        """)
        results["characters"] = [
            {
                "name": row[0],
                "appearance_count": row[1],
                "role_function": row[2] or "unknown",
                "avg_emotion_score": row[3],
            }
            for row in cursor.fetchall()
        ]
        
        cursor = conn.execute("""
            SELECT topic_id, SUM(topic_weight) as total_weight
            FROM chunk_topics
            GROUP BY topic_id
            ORDER BY total_weight DESC
        """)
        results["topics"] = [
            {
                "topic_id": row[0],
                "weight": row[1],
            }
            for row in cursor.fetchall()
        ]
        
        cursor = conn.execute("""
            SELECT chunk_id, emotional_valence, event_type, pivot_moment, 
                   cliffhanger, has_foreshadowing, foreshadowing_type, foreshadowing_desc
            FROM chunk_annotation ORDER BY chunk_id
        """)
        results["chunk_annotations"] = [
            {
                "chunk_id": row[0],
                "emotional_valence": row[1],
                "event_type": row[2],
                "pivot_moment": bool(row[3]) if row[3] is not None else None,
                "cliffhanger": bool(row[4]) if row[4] is not None else None,
                "has_foreshadowing": bool(row[5]) if row[5] is not None else None,
                "foreshadowing_type": row[6],
                "foreshadowing_desc": row[7],
            }
            for row in cursor.fetchall()
        ]
        
        cursor = conn.execute("""
            SELECT chunk_id, mtld, ttr, avg_sent_len, d_value, 
                   pause_density, fight_density, dialogue_ratio, 
                   sensory_density, metaphor_density, cultural_density
            FROM chunk_style ORDER BY chunk_id
        """)
        results["chunk_styles"] = [
            {
                "chunk_id": row[0],
                "mtld": row[1],
                "ttr": row[2],
                "avg_sent_len": row[3],
                "d_value": row[4],
                "pause_density": row[5],
                "fight_density": row[6],
                "dialogue_ratio": row[7],
                "sensory_density": row[8],
                "metaphor_density": row[9],
                "cultural_density": row[10],
            }
            for row in cursor.fetchall()
        ]
        
        cursor = conn.execute("SELECT stat_name, stat_value FROM global_stats")
        results["global_stats"] = {row[0]: row[1] for row in cursor.fetchall()}
        
        try:
            agg_result = aggregate_all_metrics(conn)
            results["aggregate_metrics"] = {
                "narrative_structure": agg_result.narrative_structure,
                "emotion_curve": agg_result.emotion_curve,
                "character_relations": agg_result.character_relations,
                "language_style": agg_result.language_style,
                "traditional_culture": agg_result.traditional_culture,
            }
        except Exception as e:
            logger.warning(f"Failed to compute aggregate metrics: {e}")
            results["aggregate_metrics"] = None
        
        cursor = conn.execute("SELECT * FROM cloud_analysis ORDER BY rowid DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            import json as json_mod
            results["diagnosis"] = {
                "novel_id": row[0] if len(row) > 0 else None,
                "foreshadow_rate": row[1] if len(row) > 1 else None,
                "arc_scores": json_mod.loads(row[2]) if len(row) > 2 and row[2] else None,
                "narrative_type": row[3] if len(row) > 3 else None,
                "topic_labels": json_mod.loads(row[4]) if len(row) > 4 and row[4] else None,
                "diagnosis": row[5] if len(row) > 5 else None,
                "value_logic_type": row[6] if len(row) > 6 else None,
                "value_logic_reason": row[7] if len(row) > 7 else None,
                "power_stance_score": row[8] if len(row) > 8 else None,
                "power_stance_reason": row[9] if len(row) > 9 else None,
                "common_people_dignity": row[10] if len(row) > 10 else None,
                "dignity_reason": row[11] if len(row) > 11 else None,
            }
        
        return results
    finally:
        conn.close()


if __name__ == "__main__":
    analyze_chongmingzhuan()
