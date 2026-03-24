"""
标注辅助函数模块 - 消歧处理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数，使用 Repository 模式
- 2026-03-15: 移除向后兼容代码，只使用 Repository 模式
- 2026-03-16: 增量消歧只维护内存 alias_map，添加 checkpoint 机制

修改时间: 2026-03-20
修改者: TraeAI
任务: fix-hardcoded-relation-types
修改内容: 移除硬编码的 VALID_HIERARCHICAL_RELATION_TYPES，改为从配置动态读取

说明: 本模块包含人名消歧相关的辅助函数。
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Any

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.models.interfaces import DisambiguationLike
from src.models.local.disambiguation import ExtendedDisambigResult
from src.storage.repositories import AnnotationRepository
from .sentence import build_context_sentences


class DisambiguationMaxRetriesExceededError(Exception):
    """
    消歧重试次数耗尽异常

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 修复导入错误
    说明: 从 phase.py 移动到 disambiguation.py，与消歧逻辑放在一起
    """
    pass

def _save_disambig_checkpoint(
    conn, run_id: str, alias_map: dict[str, str], entity_relations: list[dict[str, str]] | None = None
) -> None:
    """
    保存消歧检查点

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-postgresql-transaction-error
    修改内容: 简化代码，依赖正确的表结构
    """
    try:
        conn.execute(
            text("""
            INSERT INTO disambig_checkpoint (run_id, alias_map, updated_at, entity_relations)
            VALUES (:run_id, :alias_map, :updated_at, :entity_relations)
            ON CONFLICT (run_id) DO UPDATE SET
                alias_map = EXCLUDED.alias_map,
                updated_at = EXCLUDED.updated_at,
                entity_relations = EXCLUDED.entity_relations
        """),
            {
                "run_id": run_id,
                "alias_map": json.dumps(alias_map),
                "updated_at": time.time(),
                "entity_relations": json.dumps(entity_relations) if entity_relations else None,
            },
        )
        conn.commit()
        logger.debug(f"disambig checkpoint saved: {len(alias_map)} entries")
    except Exception as e:
        logger.warning(f"failed to save disambig checkpoint: {e}")


def _load_disambig_checkpoint(conn, run_id: str) -> tuple[dict[str, str] | None, list[dict[str, str]] | None]:
    """
    加载消歧检查点

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-postgresql-transaction-error
    修改内容: 简化代码，依赖正确的表结构

    Returns:
        (alias_map, entity_relations): 别名映射和关系数据
    """
    try:
        result = conn.execute(
            text("SELECT alias_map, entity_relations FROM disambig_checkpoint WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).fetchone()

        if result:
            alias_map = json.loads(result[0]) if result[0] else {}
            entity_relations = json.loads(result[1]) if result[1] else None
            logger.info(f"disambig checkpoint loaded: {len(alias_map)} entries, relations={len(entity_relations) if entity_relations else 0}")
            return alias_map, entity_relations
    except Exception as e:
        logger.warning(f"failed to load disambig checkpoint: {e}")

    return None, None


def _save_disambiguation_interaction(
    client: DisambiguationLike,
    run_id: str | None,
    candidates: list,
    context_sentences: dict,
    result: Any,
    stage_name: str,
    attempt_number: int,
    duration_ms: int,
) -> None:
    """
    保存消歧阶段的模型交互记录

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 添加消歧阶段模型交互记录保存
    """
    if not run_id:
        return

    try:
        import json
        from src.storage.db import get_session_factory
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository
        from src.models.local.disambiguation import build_disambiguate_messages

        Session = get_session_factory()
        session = Session()
        try:
            repo = ModelInteractionRepository(session)

            # 构建消息
            messages = build_disambiguate_messages(candidates, context_sentences, None, None)
            prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # 构建响应内容
            if isinstance(result, ExtendedDisambigResult):
                # ExtendedDisambigResult
                response_dict = {
                    "alias_map": result.alias_map,
                    "entity_types": result.entity_types if hasattr(result, 'entity_types') else {},
                    "entity_relations": result.entity_relations if hasattr(result, 'entity_relations') else [],
                }
            elif isinstance(result, dict):
                response_dict = {"alias_map": result, "entity_types": {}, "entity_relations": []}
            else:
                response_dict = {"alias_map": {}, "entity_types": {}, "entity_relations": []}

            response_text = json.dumps(response_dict, ensure_ascii=False)

            # 提取 thinking_content（如果存在）
            thinking_content = getattr(result, "_thinking_content", None)
            thinking_chars = len(thinking_content) if thinking_content else 0
            has_thinking = bool(thinking_content and thinking_content.strip())

            # 判断是否是云端模型
            is_cloud = client.is_cloud_api()

            repo.save_interaction(
                run_id=run_id,
                chunk_id=None,  # 消歧阶段没有特定 chunk_id
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt_number,
                model_name=client._config.model,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=response_text,
                thinking=thinking_content,
                response_chars=len(response_text),
                thinking_chars=thinking_chars,
                has_thinking=has_thinking,
                status="success",
                duration_ms=duration_ms,
            )
        finally:
            session.close()
    except Exception as e:
        # 检查是否是外键约束错误
        error_str = str(e).lower()
        if "foreignkeyviolation" in error_str or "外键约束" in error_str or "foreign key" in error_str:
            # 外键约束错误是因为 chunk 尚未提交到数据库
            # 这是预期的行为，在并行处理或新 session 中可能看不到主 session 未提交的数据
            logger.debug("Skipping disambiguation interaction save due to foreign key constraint")
        else:
            logger.warning(f"Failed to save disambiguation interaction: {e}")


def _retry_disambig(
    client: DisambiguationLike,
    candidates: list[str] | list[dict],
    context_sentences: dict[str, str],
    alias_keywords: list[str],
    stage_name: str,
    run_id: str | None = None,
) -> Any:
    """
    带重试的消歧调用

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 添加消歧重试逻辑和交互记录保存

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复 disambiguate_characters 调用方式
    修改内容: 使用 client.disambiguate_characters() 方法调用
    """
    max_retries = 3
    last_exception = None

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        try:
            result = client.disambiguate_characters(
                candidates=candidates,
                context_sentences=context_sentences,
                existing_names=alias_keywords if alias_keywords else None,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            # 保存模型交互记录
            _save_disambiguation_interaction(
                client=client,
                run_id=run_id,
                candidates=candidates,
                context_sentences=context_sentences,
                result=result,
                stage_name=stage_name,
                attempt_number=attempt,
                duration_ms=duration_ms,
            )

            return result
        except Exception as e:
            last_exception = e
            duration_ms = int((time.time() - start_time) * 1000)

            # 保存失败的交互记录
            _save_disambiguation_interaction(
                client=client,
                run_id=run_id,
                candidates=candidates,
                context_sentences=context_sentences,
                result={"error": str(e)},
                stage_name=stage_name,
                attempt_number=attempt,
                duration_ms=duration_ms,
            )

            if attempt < max_retries:
                logger.warning(f"{stage_name} failed (attempt {attempt}), retrying: {e}")
                time.sleep(1)
            else:
                logger.error(f"{stage_name} failed after {max_retries} attempts: {e}")
                raise last_exception


def extract_new_names_from_db(
    conn,
    alias_map: dict[str, str],
    run_id: str,
    current_chunk_id: int | None = None,
) -> list[dict[str, int]]:
    """
    从数据库中提取新出现的人名（带频次）

    基于当前 chunk 及之前所有 chunk 的标注结果，提取不在 alias_map 中的新人物名。

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧只提取当前chunk的问题
    修改内容: 从所有已标注的chunk中提取新名字，使用 fetch_chunk_characters_full

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复候选人名没有频次的问题
    修改内容: 返回带频次的字典列表 [{"name": "伯安", "count": 312}, ...]
    """
    from src.storage.repositories import AnnotationRepository
    from collections import Counter

    ann_repo = AnnotationRepository(conn)

    existing_names = set(alias_map.values()) if alias_map else set()

    all_characters = ann_repo.fetch_chunk_characters_full(run_id)

    name_counter: Counter[str] = Counter()
    for char_row in all_characters:
        name = char_row[1] if len(char_row) > 1 else None
        if name and name not in existing_names:
            name_counter[name] += 1

    result = [{"name": name, "count": count} for name, count in name_counter.most_common()]
    return result  # type: ignore[return-value]


def _run_incremental_disambiguation(
    conn,
    alias_map: dict[str, str],
    incremental_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
    chunk_id: int,
    current_idx: int,
    checkpoint_interval: int,
) -> dict[str, str]:
    """
    执行增量消歧

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 移除关系保存逻辑，增量消歧阶段不保存关系（实体尚未创建）

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧间隔逻辑
    修改内容: 只在 checkpoint_interval 间隔时才执行消歧操作

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复增量消歧缺少上下文问题
    修改内容: 构建并传递 context_sentences 给模型
    """
    if (current_idx + 1) % checkpoint_interval != 0:
        return alias_map

    new_names = extract_new_names_from_db(conn, alias_map, run_id, current_chunk_id=chunk_id)

    if not new_names:
        return alias_map

    candidates = new_names

    context_sentences = build_context_sentences(conn, candidates, alias_keywords)

    result = _retry_disambig(
        incremental_disambig_client,
        candidates,
        context_sentences,
        alias_keywords,
        stage_name="incremental disambiguation",
        run_id=run_id,
    )

    if result.alias_map:
        alias_map.update(result.alias_map)
        logger.debug(f"alias_map updated in memory: {len(alias_map)} entries")

        if result.entity_relations:
            logger.debug(f"incremental disambig: skipped {len(result.entity_relations)} relations (will be processed in final disambiguation)")

        _save_disambig_checkpoint(conn, run_id, alias_map)

    return alias_map


def _run_final_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: DisambiguationLike,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
) -> dict[str, str]:
    """
    执行最终消歧

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-entity-relations-not-saved
    修改内容: 调整执行顺序，先创建实体再保存关系；支持恢复时处理未保存的关系
    """
    # 检查是否有未保存的关系数据（系统意外停止后恢复）
    _, pending_relations = _load_disambig_checkpoint(conn, run_id)
    if pending_relations:
        logger.info(f"found {len(pending_relations)} pending relations from checkpoint, will process them")

    existing_names = list(set(alias_map.values())) if alias_map else None

    result = _retry_disambig(
        full_disambig_client,
        existing_names or [],
        {},
        alias_keywords,
        stage_name="final disambiguation",
        run_id=run_id,
    )

    if result.alias_map:
        alias_map.update(result.alias_map)
        logger.info(f"final disambiguation completed: {len(alias_map)} entries")

    # 1. 先创建实体
    if alias_map:
        ann_repo = AnnotationRepository(conn)
        ann_repo.update_character_names(run_id, alias_map, novel_id=novel_id)
        logger.info(f"character names updated in annotations: {len(alias_map)} entries")

    # 2. 再保存关系（实体必须先创建）
    # 优先处理 checkpoint 中未保存的关系（恢复场景）
    relations_to_process = pending_relations if pending_relations else result.entity_relations
    if relations_to_process:
        success_count, skipped = _process_entity_relations(
            conn, novel_id, run_id, relations_to_process, result.entity_types, result.alias_map
        )
        logger.info(f"final disambig: processed {success_count} hierarchical relations")

    # 保存 checkpoint，同时保存关系数据（用于系统意外停止后恢复）
    _save_disambig_checkpoint(conn, run_id, alias_map, result.entity_relations)

    return alias_map


def _run_cloud_disambiguation(
    conn,
    alias_map: dict[str, str],
    cloud_disambig_client: DisambiguationLike | None,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
) -> dict[str, str]:
    """执行云端消歧（如果需要）"""
    if not cloud_disambig_client:
        return alias_map

    existing_names = list(set(alias_map.values())) if alias_map else None

    result = _retry_disambig(
        cloud_disambig_client,
        existing_names or [],
        {},
        alias_keywords,
        stage_name="cloud disambiguation",
        run_id=run_id,
    )

    if isinstance(result, dict):
        alias_map.update(result)
    elif hasattr(result, 'alias_map'):
        alias_map.update(result.alias_map)

    logger.info(f"cloud disambiguation completed: {len(alias_map)} entries")

    return alias_map


def run_disambiguation(
    conn,
    alias_map: dict[str, str],
    full_disambig_client: DisambiguationLike,
    cloud_disambig_client: DisambiguationLike | None,
    alias_keywords: list[str],
    novel_id: str,
    run_id: str,
) -> dict[str, str]:
    """
    执行消歧流程（增量 + 最终 + 云端）

    这是供外部调用的统一接口。
    """
    alias_map = _run_final_disambiguation(
        conn, alias_map, full_disambig_client, alias_keywords, novel_id, run_id
    )

    if cloud_disambig_client:
        alias_map = _run_cloud_disambiguation(
            conn, alias_map, cloud_disambig_client, alias_keywords, novel_id, run_id
        )

    return alias_map


def detect_cycle_in_relations(
    relations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[list[str]]]:
    """
    检测关系中的循环依赖

    使用 DFS 检测有向图中的循环。

    Args:
        relations: 关系列表，每个关系包含 from, to, type 字段

    Returns:
        (valid_relations, skipped_relations, cycle_paths):
            有效关系列表、被跳过的关系列表、完整的循环路径列表
    """
    if not relations:
        return [], [], []

    graph = defaultdict(list)
    for rel in relations:
        graph[rel["from"]].append(rel["to"])

    visited = set()
    rec_stack = set()
    cycle_nodes = set()
    cycle_paths: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in graph[node]:
            if neighbor not in visited:
                if dfs(neighbor, path + [node]):
                    return True
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor) if neighbor in path else 0
                full_cycle = path[cycle_start:] + [node, neighbor]
                cycle_nodes.update(full_cycle)
                cycle_paths.append(full_cycle)
                return True

        rec_stack.remove(node)
        return False

    for node in list(graph.keys()):
        if node not in visited:
            dfs(node, [])

    valid_relations: list[dict[str, str]] = []
    skipped_relations: list[dict[str, str]] = []

    for rel in relations:
        if rel["from"] in cycle_nodes or rel["to"] in cycle_nodes:
            skipped_relations.append(rel)
        else:
            valid_relations.append(rel)

    return valid_relations, skipped_relations, cycle_paths


def _process_entity_relations(
    conn,
    novel_id: str,
    run_id: str,
    entity_relations: list[dict[str, str]],
    entity_types: dict[str, str],
    alias_map: dict[str, str],
) -> tuple[int, list[dict[str, Any]]]:
    """
    处理实体间的层级关系

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 将消歧结果中的关系写入数据库

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-hardcoded-relation-types
    修改内容: 从配置读取有效关系类型，而非硬编码

    Args:
        conn: 数据库连接
        novel_id: 小说ID
        run_id: 运行ID
        entity_relations: 关系列表
        entity_types: 实体类型映射
        alias_map: 别名映射

    Returns:
        (success_count, skipped_relations): 成功写入的关系数量、被跳过的关系列表
    """
    from src.storage.repositories import EntityRepository

    if not entity_relations:
        return 0, []

    entity_repo = EntityRepository(conn)

    valid_relations, cycle_skipped, cycle_paths = detect_cycle_in_relations(entity_relations)

    if cycle_paths:
        logger.warning(
            "检测到循环依赖关系",
            cycle_paths=cycle_paths,
            skipped_count=len(cycle_skipped),
        )

    success_count = 0
    skipped_relations: list[dict[str, Any]] = list(cycle_skipped)

    valid_relation_types = set(settings.analysis.valid_hierarchical_relation_types)

    for rel in valid_relations:
        from_name = rel.get("from")
        to_name = rel.get("to")
        rel_type = rel.get("type")

        if not from_name or not to_name or not rel_type:
            skipped_relations.append({
                "relation": rel,
                "reason": "missing_fields",
            })
            continue

        if rel_type not in valid_relation_types:
            logger.warning(f"无效的关系类型: {rel_type}, 跳过关系 {rel}")
            skipped_relations.append({
                "relation": rel,
                "reason": "invalid_relation_type",
            })
            continue

        from_entity_id = entity_repo.get_entity_id_by_name(novel_id, from_name, run_id)
        to_entity_id = entity_repo.get_entity_id_by_name(novel_id, to_name, run_id)

        if from_entity_id is None:
            skipped_relations.append({
                "relation": rel,
                "reason": "from_entity_not_found",
            })
            continue

        if to_entity_id is None:
            skipped_relations.append({
                "relation": rel,
                "reason": "to_entity_not_found",
            })
            continue

        try:
            entity_repo.insert_entity_relation(
                novel_id=novel_id,
                from_entity=from_entity_id,
                to_entity=to_entity_id,
                rel_type=rel_type,
                rel_category="hierarchical",
                run_id=run_id,
            )
            success_count += 1
        except Exception as e:
            logger.error(f"插入关系失败: {rel}, 错误: {e}")
            skipped_relations.append({
                "relation": rel,
                "reason": f"insert_error: {str(e)}",
            })

    if skipped_relations:
        logger.warning(
            f"关系处理完成: 成功 {success_count}, 跳过 {len(skipped_relations)}",
            skipped_relations=skipped_relations,
        )

    return success_count, skipped_relations
