
from .base import CloudModelClient, NullCloudModelClient, TokenUsageCallback, make_empty_analysis
from .schema import CloudAnalysis


def build_diagnosis_payload(*args, **kwargs):
    """
    说明: 保持 `src.models.cloud.build_diagnosis_payload` 兼容导出，
          但将真正的 payload 模块导入延迟到调用时，避免包导入阶段循环依赖。
    """
    from .payload import build_diagnosis_payload as _build_diagnosis_payload

    return _build_diagnosis_payload(*args, **kwargs)

__all__ = [
    "CloudAnalysis",
    "CloudModelClient",
    "NullCloudModelClient",
    "TokenUsageCallback",
    "build_diagnosis_payload",
    "make_empty_analysis",
]
