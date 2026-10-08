"""流式展示失败的错误契约，不触发模型重试"""


class StreamEmitError(RuntimeError):
    """2026-08-12 用于区分 SSE 推送失败与模型输出流中断：推送失败不触发模型请求重试"""
