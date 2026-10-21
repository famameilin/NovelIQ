"""编排分析阶段并为阶段事件补全上下文"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from src.event_bus.notifications import StreamEvent
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
        bus: AnalysisEventBus, stage: str
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
        *,
        skip_states: dict[str, str] | None = None,
    ) -> None:
        """
        执行各分析阶段
        """

        for stage in ("preprocess", "annotate", "linguistic", "aggregate", "topic-model", "diagnose"):
            await bus.emit(StreamEvent(action="stage_state", stage=stage, status="pending"))

        for stage, skip_key, action in (
            ("preprocess", "skip_preprocess", lambda emit: self.stage_executor.run_preprocess(
                source_path, run_id, session, emitter=emit)),
            ("annotate", "skip_annotate", lambda emit: self.stage_executor.run_annotate(
                run_id, session, novel_id, analysis_logger, novel_title, emitter=emit)),
            ("linguistic", "skip_linguistic", lambda emit: self.stage_executor.run_linguistic(run_id, session, emit)),
            ("aggregate", "skip_aggregate", lambda emit: self.stage_executor.run_aggregate(run_id, session, emit)),
            ("topic-model", "skip_topic_model", lambda emit: self.stage_executor.run_topic_model(
                run_id, session, num_topics, emit)),
            ("diagnose", "skip_diagnose", lambda emit: self.stage_executor.run_diagnose(
                run_id, session, analysis_logger, emit)),
        ):
            if skip_stages[skip_key]:
                state = (skip_states or {}).get(stage, "skipped")
                reasons = {"disabled": "配置禁用", "completed": "正式产出已确认",
                    "not_in_scope": "不在本次重分析范围", "skipped": "执行计划跳过，细分原因未记录"}
                await bus.emit(StreamEvent(action="stage_state", stage=stage,
                    status=state, message=reasons[state]))
                continue
            await bus.emit(StreamEvent(action="stage_state", stage=stage, status="running"))
            try:
                await action(self._make_stage_emitter(bus, stage))
            except BaseException as exc:
                import asyncio

                await bus.emit(StreamEvent(action="stage_state", stage=stage,
                    status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                    message=str(exc)))
                raise
            await bus.emit(StreamEvent(action="stage_state", stage=stage, status="completed"))
