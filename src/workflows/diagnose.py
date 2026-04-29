"""
诊断工作流模块

本文件从 src/cli/diagnose.py 提取核心业务逻辑，作为 workflows 模块的诊断工作流实现



"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config.analysis_logger import AnalysisLogger
from src.models.cloud import build_diagnosis_payload
from src.models.cloud.schema import CloudAnalysis
from src.models.diagnosis import DiagnosisClient
from src.storage.repositories import RunRepository, StatsRepository


def _setup_diagnose_callback(
    cloud_client: DiagnosisClient,
    session: Session,
    novel_id: str,
    run_id: str,
) -> None:
    """
    设置诊断token回调

    从 run_diagnose 中提取，负责设置token使用记录回调
    """

    def _token_usage_callback(
        cb_novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens,
        chunk_id,
    ) -> None:
        try:
            resolved_novel_id = cb_novel_id if cb_novel_id and cb_novel_id != "unknown" else novel_id
            stats_repo = StatsRepository(session)
            stats_repo.insert_token_usage(
                run_id,
                resolved_novel_id,
                task_type,
                call_type,
                model,
                prompt_tokens,
                total_tokens,
                completion_tokens,
                chunk_id,
            )
        except Exception as e:
            logger.warning(f"failed to record token usage: {e}")

    cloud_client._token_usage_callback = _token_usage_callback
    cloud_client._novel_id = novel_id


def _log_diagnosis_results(result: CloudAnalysis) -> None:
    """
    输出诊断结果日志

    从 run_diagnose 中提取，负责输出诊断结果日志
    """
    logger.info("\n=== Diagnosis Summary ===")
    logger.info(f"Novel ID: {result.novel_id}")
    logger.info(f"Genre Labels: {', '.join(result.genre_labels) if result.genre_labels else '[]'}")
    logger.info(f"Style Labels: {', '.join(result.style_labels) if result.style_labels else '[]'}")
    if result.foreshadow_expectation is not None:
        logger.info(f"Foreshadow Expectation: {result.foreshadow_expectation:.2%}")
    if result.value_logic_type:
        logger.info(f"Value Logic Type: {result.value_logic_type}")
    if result.value_logic_reason:
        logger.info(f"Value Logic Reason: {result.value_logic_reason}")
    if result.power_stance_score is not None:
        logger.info(f"Power Stance Score: {result.power_stance_score}/5")
    if result.power_stance_reason:
        logger.info(f"Power Stance Reason: {result.power_stance_reason}")
    if result.common_people_dignity is not None:
        logger.info(f"Common People Dignity: {result.common_people_dignity}/5")
    if result.dignity_reason:
        logger.info(f"Dignity Reason: {result.dignity_reason}")
    if result.diagnosis:
        logger.info(f"\nDiagnosis:\n{result.diagnosis}")


async def run_diagnose(
    run_id: str,
    session: Session,
    client: DiagnosisClient | None = None,
    analysis_logger: AnalysisLogger | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> CloudAnalysis:
    """
    执行诊断流程





    Args:
        run_id: 运行ID
        session: 数据库连接
        client: 诊断客户端
        analysis_logger: 分析日志器

    Returns:
        CloudAnalysis: 诊断分析结果
    """
    run_repo = RunRepository(session)
    run = run_repo.get_run(run_id)
    novel_id = str(run.get("novel_id", "")).strip() if run else ""
    if not novel_id:
        raise ValueError(f"run {run_id} is missing novel_id, cannot build diagnosis payload")

    stats_repo = StatsRepository(session)
    payload = build_diagnosis_payload(session, novel_id, run_id)

    logger.debug(f"built diagnosis payload with keys={sorted(payload.keys())}")

    cloud_client = client or DiagnosisClient(analysis_logger=analysis_logger)

    _setup_diagnose_callback(cloud_client, session, novel_id, run_id=run_id)
    if isinstance(cloud_client, DiagnosisClient):
        result = await cloud_client.diagnose(payload, run_id=run_id)
    else:
        result = await cloud_client.diagnose(payload)

    stats_repo.insert_cloud_analysis(run_id, result)
    logger.debug(f"diagnosis persisted run_id={run_id}")

    _log_diagnosis_results(result)

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="diagnose", current=1, total=1, percent=100.0, sub_percent=100.0)
        )

    return result
