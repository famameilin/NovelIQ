"""
知识图谱域异常

说明: 图谱就绪类失败由本域判定并抛出，上层（workflows/agents/metrics/API）按需捕获，
      本域不依赖 API 层
"""

from __future__ import annotations


class GraphReadinessError(RuntimeError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
