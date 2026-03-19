from pydantic import BaseModel, Field
from typing import Optional


class AnalyzeRequest(BaseModel):
    """
    分析任务请求
    2026-03-11: Claude修改，添加task_id字段，多任务时必须提供

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: 添加语义分块参数支持
    修改内容: 添加 use_semantic_chunking 参数
    """

    task_id: Optional[str] = Field(default=None, description="指定任务ID，多任务时必须提供")
    skip_preprocess: bool = Field(default=False, description="跳过预处理")
    skip_annotate: bool = Field(default=False, description="跳过标注")
    skip_aggregate: bool = Field(default=False, description="跳过聚合")
    skip_topic_model: bool = Field(default=False, description="跳过主题建模")
    skip_diagnose: bool = Field(default=False, description="跳过诊断")
    num_topics: int = Field(default=25, description="主题数量")
    max_chars: int = Field(default=2000, description="每个chunk最大字符数")
    overlap: int = Field(default=200, description="相邻chunk重叠字符数")
    use_semantic_chunking: bool = Field(default=False, description="是否启用语义分块")


class ReanalyzeRequest(BaseModel):
    """重新分析请求 - 创建新的分析版本"""

    force_preprocess: bool = Field(default=False, description="强制重新预处理")
    force_annotate: bool = Field(default=False, description="强制重新标注")
    force_aggregate: bool = Field(default=False, description="强制重新聚合")
    force_topic_model: bool = Field(default=False, description="强制重新主题建模")
    force_diagnose: bool = Field(default=False, description="强制重新诊断")
    num_topics: int = Field(default=25, description="主题数量")
    label: Optional[str] = Field(default=None, description="分析版本标签，如 'v2', '修正版'")
