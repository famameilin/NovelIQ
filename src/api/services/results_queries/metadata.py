"""
结果元数据查询组装器。

说明: 承载 global_stats、token_usage、novel_name、角色别名等辅助查询逻辑。
"""

from __future__ import annotations

from loguru import logger

from src.api.models.responses import (
    GlobalStats,
    TokenUsageByModel,
    TokenUsageByTask,
    TokenUsageStats,
    TokenUsageSummary,
)
from src.storage.repositories import AnnotationRepository, ChunkRepository, DiagnosisRepository, StatsRepository


def _fetch_global_stats(run_id: str, stats_repo: StatsRepository, chunk_repo: ChunkRepository) -> GlobalStats | None:
    """获取全局统计数据。"""
    stats = stats_repo.fetch_global_stats_dict(run_id)
    total_chunks, total_chars = chunk_repo.fetch_chunk_counts(run_id)

    if not stats and total_chunks == 0:
        return None
    return GlobalStats(
        total_chunks=total_chunks,
        total_chars=total_chars,
        avg_mtld=stats.get("avg_mtld") or stats.get("global_avg_mtld"),
        avg_ttr=stats.get("avg_ttr") or stats.get("global_avg_ttr"),
        avg_sent_len=stats.get("avg_sent_len") or stats.get("global_avg_sent_len"),
        rhythm_avg=stats.get("rhythm_avg"),
        rhythm_std=stats.get("rhythm_std"),
        rhythm_max=stats.get("rhythm_max"),
        rhythm_min=stats.get("rhythm_min"),
        global_avg_sent_len=stats.get("global_avg_sent_len"),
        global_avg_ttr=stats.get("global_avg_ttr"),
    )


def _fetch_novel_name(run_id: str, novel_id: str, stats_repo: StatsRepository) -> str | None:
    """获取小说名称。"""
    return stats_repo.fetch_novel_title(novel_id, run_id)


def _fetch_token_usage_stats(run_id: str, novel_id: str, stats_repo: StatsRepository) -> TokenUsageStats:
    """获取 token 使用统计。"""
    try:
        stats = stats_repo.fetch_token_usage_stats(run_id, novel_id)
        summary = TokenUsageSummary(
            call_count=stats["summary"]["call_count"],
            total_prompt_tokens=stats["summary"]["total_prompt_tokens"],
            total_completion_tokens=stats["summary"]["total_completion_tokens"],
            total_tokens=stats["summary"]["total_tokens"],
            accounting_method=stats["summary"].get("accounting_method", "estimated"),
            coverage_status=stats["summary"].get("coverage_status", "complete"),
        )
        by_task = {
            task: TokenUsageByTask(
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
            )
            for task, data in stats["by_task"].items()
        }
        by_call_type = {
            call_type: TokenUsageByTask(
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
            )
            for call_type, data in stats.get("by_call_type", {}).items()
        }
        by_model = {
            model: TokenUsageByModel(
                call_count=data["call_count"],
                total_tokens=data["total_tokens"],
            )
            for model, data in stats["by_model"].items()
        }
        return TokenUsageStats(
            summary=summary,
            by_task=by_task,
            by_call_type=by_call_type,
            by_model=by_model,
            coverage_gaps=list(stats.get("coverage_gaps", [])),
        )
    except Exception as exc:
        logger.warning(f"Failed to fetch token usage stats: {exc}")
        return TokenUsageStats()


def _fetch_known_characters(run_id: str, annotation_repo: AnnotationRepository) -> list[str]:
    """获取已知角色列表（规范名）。"""
    repo = DiagnosisRepository(annotation_repo.session)
    known_characters, _ = repo.fetch_character_disambig_data(run_id)
    return known_characters


def _fetch_alias_merges_only(run_id: str, annotation_repo: AnnotationRepository) -> dict[str, str]:
    """获取别名映射（只包含 alias != canonical）。"""
    repo = DiagnosisRepository(annotation_repo.session)
    _, alias_merges = repo.fetch_character_disambig_data(run_id)
    return alias_merges
