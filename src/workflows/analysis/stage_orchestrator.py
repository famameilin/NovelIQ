"""
分析阶段编排

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（analysis_service.py → analysis/ 子模块）
说明: 从 src/api/services/analysis_service.py 拆出阶段 emitter 构造（_make_stage_emitter）
与阶段编排执行（_execute_analysis_stages），以混入形式提供给 AnalysisService，
行为保持不变；取消检查经 TaskClaimMixin 继承链访问。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from src.config import settings
from src.sse.events import StreamEvent
from src.work.events import AnalysisEventBus
from src.workflows.analysis.task_claim import TaskClaimMixin

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
        bus: AnalysisEventBus,
        stage: str,
        session: Session,
    ) -> Callable[[StreamEvent], Awaitable[None]]:
        """创建阶段 emitter：自动补全 stage 上下文，并在发事件前提交编排器 session

        2026-10-03 死锁修复（run 08f9ba42 实证）：编排器 session 的事务跨阶段存活，
        阶段内写入（如 topic 表 INSERT 对 analysis_runs 行取的外键 FOR KEY SHARE、
        以及任何显式行锁）与 emit 路径 to_thread 的 UPDATE analysis_runs 行锁互斥——
        编排器协程 await 自己事务堵住的 UPDATE 即永久死锁（topic INSERT 后 emit
        complete 挂死 14+ 分钟，后端 CPU 归零）。emitter 先 commit 再 emit：
        本阶段已完成写入对其它连接可见，行锁随提交释放，emit 永不被自己事务阻塞。
        expire_on_commit=False，已加载 ORM 对象不会失效。
        """

        async def emitter(event: StreamEvent) -> None:
            session.commit()
            if not event.stage:
                # 用 dataclass replace 补全 stage，避免手动重建丢失字段
                from dataclasses import replace

                event = replace(event, stage=stage)
            await bus.emit(event)

        return emitter

    async def _execute_analysis_stages(
        self,
        bus: AnalysisEventBus,
        session: Session,
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

        # ── 预处理 ──
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

        # ── 标注 ──
        if not skip_stages["skip_annotate"]:
            # 查询 章节 总数，让前端知道进度规模
            total_chapters = 0
            try:
                from src.storage.repositories import ChapterRepository

                chapter_repo = ChapterRepository(session)
                total_chapters = chapter_repo.count_chapters(run_id)
            except Exception as exc:
                logger.warning(
                    "Failed to count chapters before annotate stage, "
                    "falling back to total=0: task_id={} run_id={} error={}",
                    task_id,
                    run_id,
                    exc,
                )

            await bus.emit_stage_start(
                "annotate",
                message="开始标注分析",
                percent=settings.progress.annotate.start,
                total=total_chapters,
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

        # ── 语言结构基础数据 ──
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

        # ── 聚合 ──
        if not skip_stages["skip_aggregate"]:
            await bus.emit_stage_start("aggregate", message="开始数据聚合", percent=settings.progress.aggregate.start)

            await self.stage_executor.run_aggregate(
                run_id, session, self._make_stage_emitter(bus, "aggregate", session), is_cancelled=is_cancelled
            )
            await bus.emit_stage_complete("aggregate")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 主题建模 ──
        if not skip_stages["skip_topic_model"]:
            await bus.emit_stage_start(
                "topic-model", message="开始主题建模", percent=settings.progress.topic_model.start
            )

            await self.stage_executor.run_topic_model(
                run_id, session, num_topics, self._make_stage_emitter(bus, "topic-model", session),
                is_cancelled=is_cancelled,
            )
            await bus.emit_stage_complete("topic-model")

        if self._is_cancelled(task_id):
            await self.error_handler.handle_cancel(task_id, novel_id, session, run_id, analysis_logger, bus)
            return

        # ── 诊断 ──
        if not skip_stages["skip_diagnose"]:
            await bus.emit_stage_start("diagnose", message="开始诊断报告", percent=settings.progress.diagnose.start)
            await self.stage_executor.run_diagnose(
                run_id, session, analysis_logger, self._make_stage_emitter(bus, "diagnose", session),
                is_cancelled=is_cancelled,
            )
            await bus.emit_stage_complete("diagnose")
