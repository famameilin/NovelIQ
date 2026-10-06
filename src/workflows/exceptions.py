"""运行编排异常

说明: 编排与队列读写（src/workflows）、api 的运行态判定都会抛出这些异常，
api 中间件只做 HTTP 映射。2026-10-06 自 src/work/exceptions.py 迁出：编排住在
workflows，异常跟着编排走；api 只依赖 workflows，不再认识 work 队列包。
"""

from __future__ import annotations


class AnalysisError(Exception):
    def __init__(self, novel_id: str | None = None, message: str | None = None):
        self.novel_id = novel_id
        self.message = message or (f"Analysis error for novel: {novel_id}" if novel_id else "Analysis error")
        super().__init__(self.message)


class AnalysisNotCompleteError(Exception):
    def __init__(
        self,
        novel_id: str | None = None,
        message: str | None = None,
        run_status: str | None = None,
    ):
        self.novel_id = novel_id
        self.run_status = run_status
        self.message = message or (
            f"Analysis not complete for novel: {novel_id}" if novel_id else "Analysis not complete"
        )
        super().__init__(self.message)


class NovelNotFoundError(Exception):
    def __init__(self, novel_id: str | None = None, message: str | None = None):
        self.novel_id = novel_id
        self.message = message or (f"Novel not found: {novel_id}" if novel_id else "Novel not found")
        super().__init__(self.message)
