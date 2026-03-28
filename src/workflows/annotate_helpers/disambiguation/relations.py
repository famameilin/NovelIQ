"""
关系处理逻辑

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-module-split
说明: 从 disambiguation.py 拆分，包含关系处理相关函数
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from loguru import logger

from src.config import settings


def _dedupe_relations(relations: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """按 (from, to, type) 去重关系并保留顺序。"""
    if not relations:
        return []
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for rel in relations:
        from_name = rel.get("from")
        to_name = rel.get("to")
        rel_type = rel.get("type")
        if not from_name or not to_name or not rel_type:
            continue
        key = (from_name, to_name, rel_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"from": from_name, "to": to_name, "type": rel_type})
    return deduped


def _normalize_relations_with_alias_map(
    relations: list[dict[str, str]] | None,
    alias_map: dict[str, str],
) -> list[dict[str, str]]:
    """按 alias_map 归一关系实体名后去重。"""
    if not relations:
        return []
    normalized: list[dict[str, str]] = []
    for rel in relations:
        from_name = rel.get("from")
        to_name = rel.get("to")
        rel_type = rel.get("type")
        if not from_name or not to_name or not rel_type:
            continue
        normalized.append(
            {
                "from": alias_map.get(from_name, from_name),
                "to": alias_map.get(to_name, to_name),
                "type": rel_type,
            }
        )
    return _dedupe_relations(normalized)


def _merge_relations(
    first: list[dict[str, str]] | None,
    second: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """合并两批关系并去重。"""
    return _dedupe_relations((first or []) + (second or []))


def _extract_retryable_relations(skipped_relations: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Extract retryable relations from skipped results for checkpoint recovery."""
    if not skipped_relations:
        return []

    retryable: list[dict[str, str]] = []
    retryable_reasons = {"from_entity_not_found", "to_entity_not_found"}

    for item in skipped_relations:
        reason = item.get("reason")
        relation = item.get("relation")

        if not isinstance(relation, dict):
            continue

        if reason in retryable_reasons or (isinstance(reason, str) and reason.startswith("insert_error:")):
            retryable.append(relation)

    return _dedupe_relations(retryable)


_INVERSE_RELATION_PAIRS: dict[str, str] = {
    "child_of": "parent_of",
    "parent_of": "child_of",
    "father_of": "son_of",
    "son_of": "father_of",
    "sibling_of": "sibling_of",
    "spouse_of": "spouse_of",
}


def _is_valid_inverse_pair(relations: list[dict[str, str]], from_node: str, to_node: str) -> bool:
    """
    检查两个节点之间的双向关系是否是合法的互逆关系对

    例如：A child_of B 和 B parent_of A 是合法的互逆关系对
    """
    forward_types: set[str] = set()
    backward_types: set[str] = set()

    for rel in relations:
        if rel["from"] == from_node and rel["to"] == to_node:
            forward_types.add(rel["type"])
        elif rel["from"] == to_node and rel["to"] == from_node:
            backward_types.add(rel["type"])

    for fwd_type in forward_types:
        expected_inverse = _INVERSE_RELATION_PAIRS.get(fwd_type)
        if expected_inverse and expected_inverse in backward_types:
            return True

    return False


def detect_cycle_in_relations(
    relations: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[list[str]]]:
    """
    检测关系中的循环依赖

    使用 DFS 检测有向图中的循环。
    注意：合法的双向关系（如 child_of/parent_of）不算作循环。

    创建时间: 2026-03-28
    创建者: TraeAI
    任务: fix-cycle-detection-bug
    修改内容: 区分合法双向关系和矛盾循环

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
                if _is_valid_inverse_pair(relations, neighbor, node):
                    continue
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
        raw_from_name = rel.get("from")
        raw_to_name = rel.get("to")
        rel_type = rel.get("type")
        from_name = alias_map.get(raw_from_name, raw_from_name) if raw_from_name else None
        to_name = alias_map.get(raw_to_name, raw_to_name) if raw_to_name else None

        if not from_name or not to_name or not rel_type:
            skipped_relations.append(
                {
                    "relation": rel,
                    "reason": "missing_fields",
                }
            )
            continue

        if rel_type not in valid_relation_types:
            logger.warning(f"无效的关系类型: {rel_type}, 跳过关系 {rel}")
            skipped_relations.append(
                {
                    "relation": rel,
                    "reason": "invalid_relation_type",
                }
            )
            continue

        from_entity_id = entity_repo.get_entity_id_by_name(novel_id, from_name, run_id)
        to_entity_id = entity_repo.get_entity_id_by_name(novel_id, to_name, run_id)

        if from_entity_id is None:
            from_entity_type = entity_types.get(from_name, "character")
            from_entity_id = entity_repo.insert_entity(
                novel_id=novel_id,
                canonical=from_name,
                entity_type=from_entity_type,
                run_id=run_id,
            )
            if from_entity_id is None:
                skipped_relations.append(
                    {
                        "relation": rel,
                        "reason": "from_entity_creation_failed",
                    }
                )
                continue

        if to_entity_id is None:
            to_entity_type = entity_types.get(to_name, "character")
            to_entity_id = entity_repo.insert_entity(
                novel_id=novel_id,
                canonical=to_name,
                entity_type=to_entity_type,
                run_id=run_id,
            )
            if to_entity_id is None:
                skipped_relations.append(
                    {
                        "relation": rel,
                        "reason": "to_entity_creation_failed",
                    }
                )
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
            skipped_relations.append(
                {
                    "relation": rel,
                    "reason": f"insert_error: {str(e)}",
                }
            )

    if skipped_relations:
        logger.warning(
            f"关系处理完成: 成功 {success_count}, 跳过 {len(skipped_relations)}",
            skipped_relations=skipped_relations,
        )

    return success_count, skipped_relations
