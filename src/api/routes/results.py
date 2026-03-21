"""
创建时间: 2026-03-11
创建者: Claude
任务: API 路由 - 结果导出
说明: 提供分析结果导出和查询接口

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 重构为使用 Repository 模式，所有路由添加 run_id 参数支持

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 移除 has_db/get_db_path 等 SQLite 特有方法，使用单一 PostgreSQL 数据库
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.orm import Session

from src.api.exceptions import AnalysisNotCompleteError, NovelNotFoundError
from src.api.models.responses import ResultsWriteResponse
from src.api.routes.results_fetchers import (
    _fetch_emotion_curve,
    _fetch_rhythm_curve,
    _fetch_characters,
    _fetch_topics,
    _fetch_diagnosis,
    _fetch_chunk_styles,
    _fetch_chunk_annotations,
    _fetch_character_relations,
    _fetch_hierarchical_relations,
    _fetch_global_stats,
    _fetch_chunk_cultures,
    _fetch_novel_name,
    _fetch_token_usage_stats,
)
from src.api.routes.results_converters import _convert_aggregate_result
from src.api.services.novel_service import NovelService
from src.config import settings
from src.metrics.aggregate_metrics import aggregate_all_metrics
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    StatsRepository,
    EntityRepository,
)
from src.storage.session import SessionFactory
from src.api.routes.novels import get_novel_service

router = APIRouter(prefix="/novels", tags=["results"])


@router.get(
    "/{novel_id}/results",
    response_model=ResultsWriteResponse,
    summary="导出完整分析结果（复盘与测试用）",
    description="""
📋 **复盘与测试专用接口**

此接口将完整分析数据写入 `outputs/` 目录下的JSON文件，用于：
- 项目复盘与结果审查
- 测试验证与数据对比
- 分析结果归档备份

**参数：**
- task_id: 分析任务ID（8位短UUID，必需）

**返回内容：**
- 写入状态（成功/失败）
- 文件存储路径
- 数据完整性检查结果（缺失字段列表）

**生产环境数据获取请使用专用接口：**
- `GET /{novel_id}/emotion-curve` - 获取情感曲线
- `GET /{novel_id}/rhythm-curve` - 获取节奏曲线
- `GET /{novel_id}/characters` - 获取人物统计
- `GET /{novel_id}/topics` - 获取主题分布
- `GET /{novel_id}/diagnosis` - 获取云端诊断
- `GET /{novel_id}/metrics/*` - 获取各类聚合指标
""",
    responses={
        200: {
            "description": "结果已写入文件",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "分析结果已写入文件",
                        "file_path": "outputs/a1b2c3d4.json",
                        "novel_id": "10960c77",
                        "novel_name": "重明传",
                        "task_id": "a1b2c3d4",
                        "missing_fields": [],
                    }
                }
            },
        },
        400: {
            "description": "分析未完成或数据不完整",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "分析未完成，数据库不存在",
                        "file_path": None,
                        "novel_id": "10960c77",
                        "novel_name": None,
                        "task_id": "a1b2c3d4",
                        "missing_fields": ["emotion_curve", "rhythm_curve"],
                    }
                }
            },
        },
    },
)
async def get_results(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
) -> ResultsWriteResponse:
    """
    2026-03-12: Claude修改，检查任务状态是否为completed，如果任务未完成，抛出AnalysisNotCompleteError
    2026-03-13: TraeAI重构，提取数据获取和响应构建逻辑到独立函数
    2026-03-14: TraeAI重构，使用 Repository 模式

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 移除 has_db/get_db_path 等 SQLite 特有方法

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 修复API参数问题
    修改内容: 将task_id改为run_id，使用完整UUID查询

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: API接口参数统一优化
    修改内容: 将run_id参数改为task_id，内部转换为run_id
    """
    # 从数据库查询运行记录
    from src.storage.db import get_session_factory
    from src.storage.repositories import RunRepository
    from src.storage.id_mapping import task_id_to_run_id

    session_factory = get_session_factory()
    with session_factory() as session:
        # 将task_id转换为run_id
        run_id = task_id_to_run_id(task_id, session.connection())
        run_repo = RunRepository(session)
        run = run_repo.get_run(run_id)
        if not run:
            raise NovelNotFoundError(f"运行记录不存在: {run_id}")
        if run["status"] != "completed":
            raise AnalysisNotCompleteError(f"分析未完成，当前状态: {run['status']}")

    # 使用SQLAlchemy session直接查询数据
    with session_factory() as session:
        stats_repo = StatsRepository(session)
        annotation_repo = AnnotationRepository(session)
        chunk_repo = ChunkRepository(session)
        entity_repo = EntityRepository(session)

        results_data, missing_fields, novel_name = _fetch_all_results_data(
            novel_id, task_id, run_id, stats_repo, annotation_repo, chunk_repo, entity_repo
        )

        file_path = _write_results_to_file(task_id, results_data)

        if missing_fields:
            logger.warning(f"Task {task_id} has missing fields: {missing_fields}")

        return _build_results_response(file_path, novel_id, novel_name, missing_fields)


def _fetch_all_results_data(
    novel_id: str,
    task_id: str,
    run_id: str,
    stats_repo: StatsRepository,
    annotation_repo: AnnotationRepository,
    chunk_repo: ChunkRepository,
    entity_repo: EntityRepository,
) -> Tuple[Dict[str, Any], List[str], Optional[str]]:
    """
    2026-03-13: TraeAI创建，任务refactor-api-layer-functions
    获取所有分析结果数据，返回数据字典、缺失字段列表和小说名称

    2026-03-14: TraeAI修改，任务refactor-routes-use-repository
    修改内容: 重构为使用 Repository 模式

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 移除 db_path 参数

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 添加层级关系导出到JSON功能
    修改内容: 添加 entity_repo 参数，导出层级关系

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: fix-character-alias-inconsistency
    修改内容: 获取 alias_map 并传递给子函数，实现人物外号归一化
    """
    missing_fields: List[str] = []

    # 获取别名映射表，用于人物外号归一化
    alias_map = annotation_repo.fetch_alias_map(run_id)

    emotion_curve = _fetch_emotion_curve(run_id, stats_repo)
    if not emotion_curve:
        missing_fields.append("emotion_curve")

    rhythm_curve = _fetch_rhythm_curve(run_id, stats_repo)
    if not rhythm_curve:
        missing_fields.append("rhythm_curve")

    characters = _fetch_characters(run_id, annotation_repo)
    if not characters:
        missing_fields.append("characters")

    topics = _fetch_topics(run_id, chunk_repo)

    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
    if not diagnosis:
        missing_fields.append("diagnosis")

    chunk_styles = _fetch_chunk_styles(run_id, chunk_repo)
    if not chunk_styles:
        missing_fields.append("chunk_styles")

    chunk_annotations = _fetch_chunk_annotations(run_id, annotation_repo, alias_map)
    if not chunk_annotations:
        missing_fields.append("chunk_annotations")

    character_relations = _fetch_character_relations(run_id, annotation_repo, alias_map)
    hierarchical_relations = _fetch_hierarchical_relations(novel_id, run_id, entity_repo)
    global_stats = _fetch_global_stats(run_id, stats_repo, chunk_repo)

    result = aggregate_all_metrics(run_id, annotation_repo, chunk_repo, stats_repo)
    chunk_cultures = _fetch_chunk_cultures(run_id, chunk_repo)
    narrative_structure, emotion_stats, character_stats, style_stats, culture_stats = _convert_aggregate_result(result)

    token_usage_stats = _fetch_token_usage_stats(run_id, novel_id, stats_repo)
    novel_name = _fetch_novel_name(run_id, novel_id, stats_repo)

    results_data = {
        "task_id": task_id,
        "novel_id": novel_id,
        "novel_name": novel_name,
        "generated_at": datetime.now().isoformat(),
        "total_chunks": global_stats.total_chunks if global_stats else 0,
        "total_chars": global_stats.total_chars if global_stats else 0,
        "emotion_curve": [e.model_dump() for e in emotion_curve],
        "rhythm_curve": [r.model_dump() for r in rhythm_curve],
        "characters": [c.model_dump() for c in characters],
        "topics": [t.model_dump() for t in topics],
        "diagnosis": diagnosis.model_dump() if diagnosis else None,
        "chunk_styles": [s.model_dump() for s in chunk_styles],
        "chunk_annotations": [a.model_dump() for a in chunk_annotations],
        "character_relations": [r.model_dump() for r in character_relations],
        "hierarchical_relations": [r.model_dump() for r in hierarchical_relations],
        "global_stats": global_stats.model_dump() if global_stats else None,
        "chunk_cultures": [c.model_dump() for c in chunk_cultures],
        "aggregate_metrics": {
            "narrative_structure": narrative_structure.model_dump() if narrative_structure else None,
            "emotion_stats": emotion_stats.model_dump() if emotion_stats else None,
            "character_stats": character_stats.model_dump() if character_stats else None,
            "style_stats": style_stats.model_dump() if style_stats else None,
            "culture_stats": culture_stats.model_dump() if culture_stats else None,
        },
        "token_usage_stats": token_usage_stats.model_dump(),
    }

    return results_data, missing_fields, novel_name


def _build_results_response(
    file_path: str, novel_id: str, novel_name: Optional[str], missing_fields: List[str]
) -> ResultsWriteResponse:
    """
    2026-03-13: TraeAI创建，任务refactor-api-layer-functions
    构建结果响应对象
    """
    return ResultsWriteResponse(
        success=True,
        message="分析结果已写入文件",
        file_path=file_path,
        novel_id=novel_id,
        novel_name=novel_name,
        missing_fields=missing_fields if missing_fields else None,
    )


def _write_results_to_file(task_id: str, data: Dict[str, Any]) -> str:
    results_dir = settings.paths.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{task_id}.json"
    file_path = results_dir / filename

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Results written to {file_path}")
    return str(file_path)


def _get_session_and_run_id(task_id: str, novel_service: NovelService) -> Tuple[Optional[Session], Optional[str]]:
    """
    2026-03-14: TraeAI创建，任务refactor-routes-use-repository
    从 task_id 获取数据库连接和 run_id

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 移除 has_db 检查，使用单一 PostgreSQL 数据库

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: API接口参数统一优化
    修改内容: 将task_id转换为run_id返回，处理无效task_id情况
    """
    from src.storage.id_mapping import task_id_to_run_id, TaskIDNotFoundError

    session_factory = SessionFactory(novel_service.upload_dir)
    db_session = session_factory.get_session(task_id)
    try:
        # 将task_id转换为run_id
        run_id = task_id_to_run_id(task_id, db_session.connection)
        return db_session.connection, run_id
    except (ValueError, TaskIDNotFoundError):
        # task_id格式无效或找不到对应的run_id
        db_session.connection.close()
        return None, None


@router.get("/{novel_id}/emotion-curve")
async def get_emotion_curve(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return []
    try:
        stats_repo = StatsRepository(conn)
        return _fetch_emotion_curve(run_id, stats_repo)
    finally:
        conn.close()


@router.get("/{novel_id}/rhythm-curve")
async def get_rhythm_curve(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return []
    try:
        stats_repo = StatsRepository(conn)
        return _fetch_rhythm_curve(run_id, stats_repo)
    finally:
        conn.close()


@router.get("/{novel_id}/characters")
async def get_characters(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return []
    try:
        annotation_repo = AnnotationRepository(conn)
        return _fetch_characters(run_id, annotation_repo)
    finally:
        conn.close()


@router.get("/{novel_id}/topics")
async def get_topics(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return []
    try:
        chunk_repo = ChunkRepository(conn)
        return _fetch_topics(run_id, chunk_repo)
    finally:
        conn.close()


@router.get("/{novel_id}/diagnosis")
async def get_diagnosis(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return None
    try:
        stats_repo = StatsRepository(conn)
        return _fetch_diagnosis(run_id, novel_id, stats_repo)
    finally:
        conn.close()


@router.get("/{novel_id}/metrics/narrative-structure")
async def get_narrative_structure(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return None
    try:
        ann_repo = AnnotationRepository(conn)
        chunk_repo = ChunkRepository(conn)
        stats_repo = StatsRepository(conn)
        result = aggregate_all_metrics(run_id, ann_repo, chunk_repo, stats_repo)
        narrative_structure, _, _, _, _ = _convert_aggregate_result(result)
        return narrative_structure
    finally:
        conn.close()


@router.get("/{novel_id}/metrics/emotion-stats")
async def get_emotion_stats(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return None
    try:
        ann_repo = AnnotationRepository(conn)
        chunk_repo = ChunkRepository(conn)
        stats_repo = StatsRepository(conn)
        result = aggregate_all_metrics(run_id, ann_repo, chunk_repo, stats_repo)
        _, emotion_stats, _, _, _ = _convert_aggregate_result(result)
        return emotion_stats
    finally:
        conn.close()


@router.get("/{novel_id}/metrics/character-stats")
async def get_character_stats(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return None
    try:
        ann_repo = AnnotationRepository(conn)
        chunk_repo = ChunkRepository(conn)
        stats_repo = StatsRepository(conn)
        result = aggregate_all_metrics(run_id, ann_repo, chunk_repo, stats_repo)
        _, _, character_stats, _, _ = _convert_aggregate_result(result)
        return character_stats
    finally:
        conn.close()


@router.get("/{novel_id}/metrics/style-stats")
async def get_style_stats(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return None
    try:
        ann_repo = AnnotationRepository(conn)
        chunk_repo = ChunkRepository(conn)
        stats_repo = StatsRepository(conn)
        result = aggregate_all_metrics(run_id, ann_repo, chunk_repo, stats_repo)
        _, _, _, style_stats, _ = _convert_aggregate_result(result)
        return style_stats
    finally:
        conn.close()


@router.get("/{novel_id}/metrics/culture-stats")
async def get_culture_stats(
    novel_id: str,
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    if conn is None or run_id is None:
        return None
    try:
        ann_repo = AnnotationRepository(conn)
        chunk_repo = ChunkRepository(conn)
        stats_repo = StatsRepository(conn)
        result = aggregate_all_metrics(run_id, ann_repo, chunk_repo, stats_repo)
        _, _, _, _, culture_stats = _convert_aggregate_result(result)
        return culture_stats
    finally:
        conn.close()
