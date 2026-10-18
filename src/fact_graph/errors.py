"""跨层共用的失败类型

图谱就绪类失败由事实图判定并抛出，编排（workflows）、指标（metrics）与传输（api）
都要按类型捕获它；类型放共用层，上层判断失败原因时不必 import 事实图。
"""

from __future__ import annotations


class GraphReadinessError(RuntimeError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
