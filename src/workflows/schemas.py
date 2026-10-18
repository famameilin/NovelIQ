"""重分析请求契约

重新分析的入参模型（既是 HTTP 请求体，也是编排决定跳过哪些阶段的依据）。
任务状态词表在 src/storage/task_status.py，队列与 api 共用同一份。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReanalyzeRequest(BaseModel):
    """重新分析请求"""

    force_preprocess: bool = Field(default=False, description="强制重新预处理")
    force_annotate: bool = Field(default=False, description="强制重新标注")
    force_aggregate: bool = Field(default=False, description="强制重新聚合")
    force_topic_model: bool = Field(default=False, description="强制重新主题建模")
    force_diagnose: bool = Field(default=False, description="强制重新诊断")
    force_linguistic: bool = Field(default=False, description="强制重新语言结构分析")
    num_topics: int = Field(default=25, description="主题数量")
