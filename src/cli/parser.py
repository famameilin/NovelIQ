"""
CLI 命令解析器

创建时间: 2025-03-11
创建者: TraeAI
任务: 命令行解析

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除向后兼容代码，使用 run_id/session 参数

修改时间: 2026-03-16
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 移除 --db 参数，使用 PostgreSQL 单一数据库
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List
import uuid

from loguru import logger
from sqlalchemy.orm import Session

from src.config import setup_logging
from src.storage.db import get_session
from src.storage.repositories import RunRepository
from src.workflows.diagnose import run_cloud_diagnose
from src.workflows.preprocess import run_preprocess
from src.workflows.annotate import run_annotate
from src.workflows.aggregate import run_aggregate
from src.workflows.diagnose import run_diagnose
from src.workflows.topic import run_topic_model
from src.cli.workflow import run_full_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-qa", description="小说量化分析工具：支持预处理、标注、聚合、诊断等完整工作流"
    )
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="启用INFO级别控制台输出")
    parser.add_argument("-d", "--debug", action="store_true", default=False, help="启用DEBUG级别控制台输出")
    subparsers = parser.add_subparsers(dest="command", required=True, help="可用命令")

    cloud = subparsers.add_parser("cloud-diagnose", help="云端诊断：直接从源文件生成诊断报告（需要云端模型）")
    cloud.add_argument("--source", type=Path, required=True, help="源文件或目录路径")
    cloud.add_argument("--metadata", type=Path, help="元数据文件路径（JSON格式）")
    cloud.add_argument("--cache", type=Path, help="缓存文件路径（可选）")

    preprocess = subparsers.add_parser("preprocess", help="预处理：读取、清洗、分块、计算风格指标")
    preprocess.add_argument("--source", type=Path, required=True, help="源文件或目录路径")
    preprocess.add_argument("--metadata", type=Path, help="元数据文件路径（JSON格式）")
    preprocess.add_argument("--cache", type=Path, help="缓存文件路径（可选）")

    annotate = subparsers.add_parser("annotate", help="标注：使用本地模型对文本块进行语义标注")
    annotate.add_argument("--run-id", type=str, required=True, help="运行ID")
    annotate.add_argument("--resume", action="store_true", default=False, help="断点续标：跳过已标注的块")
    annotate.add_argument("--cache", type=Path, help="缓存文件路径（可选）")

    aggregate = subparsers.add_parser("aggregate", help="聚合：计算情感曲线、节奏曲线、全局统计指标")
    aggregate.add_argument("--run-id", type=str, required=True, help="运行ID")
    aggregate.add_argument("--cache", type=Path, help="缓存文件路径（可选）")

    diagnose = subparsers.add_parser("diagnose", help="诊断：基于聚合数据进行云端诊断分析")
    diagnose.add_argument("--run-id", type=str, required=True, help="运行ID")
    diagnose.add_argument("--cache", type=Path, help="缓存文件路径（可选）")

    topic_model = subparsers.add_parser("topic-model", help="主题建模：使用LDA提取文本主题")
    topic_model.add_argument("--run-id", type=str, required=True, help="运行ID")
    topic_model.add_argument("--num-topics", type=int, default=25, help="主题数量（默认25）")
    topic_model.add_argument("--passes", type=int, default=10, help="训练轮数（默认10）")
    topic_model.add_argument("--iterations", type=int, default=500, help="迭代次数（默认500）")
    topic_model.add_argument("--top-n", type=int, default=5, help="每块保留的主题数（默认5）")
    topic_model.add_argument("--force", action="store_true", default=False, help="强制重新计算")
    topic_model.add_argument("--cache", type=Path, help="缓存文件路径（可选）")

    run_cmd = subparsers.add_parser("run", help="完整工作流：依次执行预处理、标注、聚合、诊断")
    run_cmd.add_argument("--source", type=Path, required=True, help="源文件或目录路径")
    run_cmd.add_argument("--metadata", type=Path, help="元数据文件路径（JSON格式）")
    run_cmd.add_argument("--cache", type=Path, help="缓存文件路径（可选）")
    run_cmd.add_argument("--skip-preprocess", action="store_true", default=False, help="跳过预处理阶段")
    run_cmd.add_argument("--skip-annotate", action="store_true", default=False, help="跳过标注阶段")
    run_cmd.add_argument("--skip-aggregate", action="store_true", default=False, help="跳过聚合阶段")
    run_cmd.add_argument("--skip-diagnose", action="store_true", default=False, help="跳过诊断阶段")

    return parser


def _create_run_id(session: Session, novel_id: str, source_path: Path, title: str | None) -> str:
    run_repo = RunRepository(session)
    return run_repo.create_run(
        novel_id=novel_id,
        source_path=str(source_path),
        title=title,
    )


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=not args.debug, debug=args.debug)

    if args.command == "cloud-diagnose":
        with get_session() as conn:
            run_id = str(uuid.uuid4())[:8]
            analysis = run_cloud_diagnose(
                source_path=args.source,
                run_id=run_id,
                session=conn,
                metadata_path=args.metadata,
                cache_path=args.cache,
            )
            logger.info(json.dumps(analysis.to_dict(), ensure_ascii=False))
        return 0

    if args.command == "preprocess":
        with get_session() as conn:
            run_id = _create_run_id(conn, args.source.stem, args.source, None)
            chunks, chars, elapsed = run_preprocess(
                source_path=args.source,
                run_id=run_id,
                session=conn,
            )
        return 0 if chunks > 0 else 1

    if args.command == "annotate":
        with get_session() as conn:
            success, errors, total = run_annotate(
                run_id=args.run_id,
                session=conn,
                resume=args.resume,
            )
        return 0 if success > 0 else 1

    if args.command == "aggregate":
        with get_session() as conn:
            chunks, emotion_rows, rhythm_rows = run_aggregate(
                run_id=args.run_id,
                session=conn,
            )
        return 0 if chunks > 0 else 1

    if args.command == "diagnose":
        with get_session() as conn:
            analysis = run_diagnose(
                run_id=args.run_id,
                session=conn,
            )
        return 0 if analysis else 1

    if args.command == "topic-model":
        with get_session() as conn:
            chunks, topics = run_topic_model(
                run_id=args.run_id,
                session=conn,
                num_topics=args.num_topics,
                passes=args.passes,
                iterations=args.iterations,
                top_n=args.top_n,
                force=args.force,
            )
        return 0 if chunks > 0 else 1

    if args.command == "run":
        results = run_full_workflow(
            source_path=args.source,
            metadata_path=args.metadata,
            cache_path=args.cache,
            skip_preprocess=args.skip_preprocess,
            skip_annotate=args.skip_annotate,
            skip_aggregate=args.skip_aggregate,
            skip_diagnose=args.skip_diagnose,
        )
        return 0 if all(r.success for r in results) else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
