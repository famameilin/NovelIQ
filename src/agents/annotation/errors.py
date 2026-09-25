"""
章节标注 Agent 失败分类
"""

from __future__ import annotations

from typing import Any


class AnnotationAgentError(RuntimeError):
    """2026-08-05 用于统一章节标注 Agent 的基础异常"""


class AnnotationRetryableError(AnnotationAgentError):
    """2026-08-05 用于标记模型工具图执行或修正耗尽类可重试错误"""


class AnnotationInputError(AnnotationAgentError):
    """2026-08-05 用于标记章节输入与身份不合法的直接失败"""


class AnnotationAuthorizationError(AnnotationAgentError):
    """2026-08-05 用于标记检索读取授权不合法的直接失败"""


class AnnotationProtocolError(AnnotationRetryableError):
    """2026-08-05 用于标记 Agent 违反当前阶段工具时序的运行失败"""


class AnnotationInvariantError(AnnotationAgentError):
    """2026-08-10 用于标记系统不变量被破坏（如已收尾但 ready_chapter 缺失），
    直接终止章节，不返回给模型修正"""


class AnnotationStageRejection(AnnotationInputError):
    """2026-09-13 小调用改造：把单条写入/收尾失败表达成可定位的结构化回执

    普通错误只指向一个语义单元（record/field/code/expected），模型只需重调该记录，
    不再返回整树或要求整批重交。record 形如 t1/e2/participant/17、entity/张三、
    dialogue/3；extra 承载领域级附加信息（如本回合失败记录清单、默认处理候选序号）。
    """

    def __init__(
        self,
        message: str,
        *,
        record: str | None = None,
        field: str | None = None,
        code: str | None = None,
        expected: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.record = record
        self.field = field
        self.code = code
        self.expected = expected
        self.extra = dict(extra or {})

    def receipt(self) -> dict[str, Any]:
        """2026-09-13 用于渲染模型可见的结构化拒绝回执（只带定位字段，不重复合同）"""
        body: dict[str, Any] = {"status": "rejected"}
        for key, value in (
            ("record", self.record),
            ("field", self.field),
            ("code", self.code),
            ("expected", self.expected),
        ):
            if value is not None:
                body[key] = value
        body.update(self.extra)
        body["message"] = str(self)
        return body
