"""编排分析阶段并为阶段事件补全上下文"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.sse.events import StreamEvent
from src.storage import Storage
from src.workflows.analysis.task_claim import TaskClaimMixin
from src.workflows.progress import AnalysisEventBus

if TYPE_CHECKING:
    from src.config.analysis_logger import AnalysisLogger
    from src.workflows.analysis.error_handler import AnalysisErrorHandler
    from src.workflows.analysis.stage_executor import StageExecutor


class StageOrchestratorMixin(TaskClaimMixin):
    """阶段编排混入（宿主需提供 error_handler/stage_executor）"""

    error_handler: AnalysisErrorHandler
    stage_executor: StageExecutor

    @staticmethod
    def _make_stage_emitter(
        bus: AnalysisEventBus, stage: str, session: Storage
    ) -> Callable[[StreamEvent], Awaitable[None]]:
        """为缺少阶段标识的事件补全上下文，再交给事件总线"""

        async def emitter(event: StreamEvent) -> None:
            if not event.stage:
                from dataclasses import replace

                event = replace(event, stage=stage)
            await bus.emit(event)

        return emitter

    async def _execute_analysis_stages(
        self,
        bus: AnalysisEventBus,
        session: Storage,
        run_id: str,
        source_path: Path,
        novel_id: str,
        novel_title: str | None,
        analysis_logger: AnalysisLogger | None,
        skip_stages: dict[str, bool],
        num_topics: int,
    ) -> None:
        """
        执行各分析阶段
        """
        task_id = bus.task_id

        def is_cancelled() -> bool:
            return self._is_cancelled(task_id)

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return
        if not skip_stages["skip_preprocess"]:
            await bus.emit_stage_start("preprocess", message="开始预处理", percent=settings.progress.preprocess.start)
            await self.stage_executor.run_preprocess(
                source_path,
                run_id,
                session,
                emitter=self._make_stage_emitter(bus, "preprocess", session),
                is_cancelled=is_cancelled,
            )
            await bus.emit_stage_complete("preprocess")
        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return
        if not skip_stages["skip_annotate"]:
            total_chapters = 0
            try:
                pass
                chapter_repo = session.chapters
                total_chapters = chapter_repo.count_chapters(run_id)
            except Exception as exc:
                logger.warning(
                    (
                        "Failed to count chapters before annotate stage, falling back to total=0: tas"
                        "k_id={} run_id={} error={}"
                    ),
                    task_id,
                    run_id,
                    exc,
                )
            await bus.emit_stage_start(
                "annotate", message="开始标注分析", percent=settings.progress.annotate.start, total=total_chapters
            )
            await self.stage_executor.run_annotate(
                run_id,
                session,
                novel_id,
                analysis_logger,
                novel_title,
                emitter=self._make_stage_emitter(bus, "annotate", session),
                is_cancelled=is_cancelled,
            )
            await bus.emit_stage_complete("annotate")
        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return
        if not skip_stages["skip_linguistic"]:
            await bus.emit_stage_start(
                "linguistic", message="开始语言结构分析", percent=settings.progress.linguistic.start
            )
            await self.stage_executor.run_linguistic(
                run_id, session, self._make_stage_emitter(bus, "linguistic", session), is_cancelled=is_cancelled
            )
            await bus.emit_stage_complete("linguistic")
        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return
        if not skip_stages["skip_aggregate"]:
            await bus.emit_stage_start("aggregate", message="开始数据聚合", percent=settings.progress.aggregate.start)
            await self.stage_executor.run_aggregate(
                run_id, session, self._make_stage_emitter(bus, "aggregate", session), is_cancelled=is_cancelled
            )
            await bus.emit_stage_complete("aggregate")
        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return
        if not skip_stages["skip_topic_model"]:
            await bus.emit_stage_start(
                "topic-model", message="开始主题建模", percent=settings.progress.topic_model.start
            )
            await self.stage_executor.run_topic_model(
                run_id,
                session,
                num_topics,
                self._make_stage_emitter(bus, "topic-model", session),
                is_cancelled=is_cancelled,
            )
            await bus.emit_stage_complete("topic-model")
        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return
        if not skip_stages["skip_diagnose"]:
            await bus.emit_stage_start("diagnose", message="开始诊断报告", percent=settings.progress.diagnose.start)
            await self.stage_executor.run_diagnose(
                run_id,
                session,
                analysis_logger,
                self._make_stage_emitter(bus, "diagnose", session),
                is_cancelled=is_cancelled,
            )
            await bus.emit_stage_complete("diagnose")
