from pydantic import BaseModel, Field
from typing import Optional


class AnalyzeRequest(BaseModel):
    """
    分析任务请求
    创建时间: 2026-03-26
    创建者: TraeAI
    任务: 简化analyze接口参数
    修改内容: 只保留task_id参数
    """

    task_id: Optional[str] = Field(default=None, description="指定任务ID，多任务时必须提供")


class ReanalyzeRequest(BaseModel):
    """重新分析请求 - 创建新的分析版本"""

    force_preprocess: bool = Field(default=False, description="强制重新预处理")
    force_annotate: bool = Field(default=False, description="强制重新标注")
    force_aggregate: bool = Field(default=False, description="强制重新聚合")
    force_topic_model: bool = Field(default=False, description="强制重新主题建模")
    force_diagnose: bool = Field(default=False, description="强制重新诊断")
    num_topics: int = Field(default=25, description="主题数量")
    label: Optional[str] = Field(default=None, description="分析版本标签，如 'v2', '修正版'")
