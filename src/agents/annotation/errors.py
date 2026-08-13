"""
章节标注 Agent 失败分类
"""


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
    """2026-08-10 用于标记系统不变量被破坏（如 8 个 receipt 齐全但 ready_chunk 缺失），
    直接终止章节，不返回给模型修正"""
