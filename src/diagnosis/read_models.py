"""诊断查询的领域结果，不依赖 HTTP 响应"""

from pydantic import Field

from src.diagnosis.patch import AgentAnalysisPatch


class DiagnosisReadResult(AgentAnalysisPatch):
    """诊断结果响应 = 诊断契约字段 + 读侧派生的三项统计

    字段集与 src/storage/diagnosis_payload.py 的 AgentAnalysisPatch 一致（同一契约，
    响应侧仅追加读侧派生字段），避免两处手写契约漂移。
    """

    foreshadow_expectation: float | None = Field(
        default=None,
        description=("伏笔回收预期，基于 setup thread ledger 加权估算的近似值，取值范围 0-1，不是严格全文事实回收率。"),
    )
    arc_scores: dict[str, float] | None = None
    genre_labels: list[str] | None = None
    style_labels: list[str] | None = None
    topic_labels: dict[str, str] | None = None
    emotion_avg: float | None = None
    lexicon_zero_hit_share: float | None = None
