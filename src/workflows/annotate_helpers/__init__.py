"""标注辅助模块；正式提交只通过 FormalChapterRepository

2026-10-02 恢复章内三子代理编排入口（block_codeact）：超长章的三条职责 subagent
并发由派发方（PipelineAgentExecutor.execute）经 run_chapter_subagents 进入。
"""

from .block_codeact import run_chapter_subagents

__all__ = ["run_chapter_subagents"]
