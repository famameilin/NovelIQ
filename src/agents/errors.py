"""Agent 执行失败与重试分类"""

class AgentError(RuntimeError):
    """Agent 执行链的基础异常"""


class AgentRetryableError(AgentError):
    """模型与工具执行中允许重试的失败"""

