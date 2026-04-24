"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 云端模型客户端模块

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 项目文件结构整理与拆解 - 添加新客户端类导出

修改时间: 2026-03-23
修改者: TraeAI
任务: unify-model-client-architecture
修改内容: 使用统一的 DiagnosisClient（从 src.models.diagnosis 导入）

修改时间: 2026-04-24
任务: fix-cloud-package-import-cycle
修改内容: `build_diagnosis_payload` 改为懒加载导出，避免仅导入 `src.models.cloud.schema`
          时也强制执行 payload -> authority 路径，触发包初始化循环依赖。
"""

from .base import CloudModelClient, NullCloudModelClient, TokenUsageCallback, make_empty_analysis
from .schema import CloudAnalysis


def build_diagnosis_payload(*args, **kwargs):
    """
    创建时间: 2026-04-24
    任务: fix-cloud-package-import-cycle
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
