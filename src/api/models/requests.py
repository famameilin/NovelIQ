from pydantic import BaseModel, Field


class ReanalyzeRequest(BaseModel):
    """重新分析请求 - 创建新的分析版本"""

    force_preprocess: bool = Field(default=False, description="强制重新预处理")
    force_annotate: bool = Field(default=False, description="强制重新标注")
    force_aggregate: bool = Field(default=False, description="强制重新聚合")
    force_topic_model: bool = Field(default=False, description="强制重新主题建模")
    force_diagnose: bool = Field(default=False, description="强制重新诊断")
    num_topics: int = Field(default=25, description="主题数量")
    label: str | None = Field(default=None, description="分析版本标签，如 'v2', '修正版'")
