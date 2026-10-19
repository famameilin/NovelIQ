"""编排分析阶段并为阶段事件补全上下文"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

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

        if not skip_stages["skip_preprocess"]:
            await self.stage_executor.run_preprocess(
                source_path,
                run_id,
                session,
                emitter=self._make_stage_emitter(bus, "preprocess", session),
            )
        if not skip_stages["skip_annotate"]:
            await self.stage_executor.run_annotate(
                run_id,
                session,
                novel_id,
                analysis_logger,
                novel_title,
                emitter=self._make_stage_emitter(bus, "annotate", session),
            )
        if not skip_stages["skip_linguistic"]:
            await self.stage_executor.run_linguistic(
                run_id, session, self._make_stage_emitter(bus, "linguistic", session)
            )
        if not skip_stages["skip_aggregate"]:
            await self.stage_executor.run_aggregate(
                run_id, session, self._make_stage_emitter(bus, "aggregate", session)
            )
        if not skip_stages["skip_topic_model"]:
            await self.stage_executor.run_topic_model(
                run_id,
                session,
                num_topics,
                self._make_stage_emitter(bus, "topic-model", session),
            )
        if not skip_stages["skip_diagnose"]:
            await self.stage_executor.run_diagnose(
                run_id,
                session,
                analysis_logger,
                self._make_stage_emitter(bus, "diagnose", session),
            )
