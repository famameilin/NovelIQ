"""章级指标与段落监督标签绑定；不持有队列、模型会话或保存事务"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.fact_graph.inputs import ChapterMetricsInput, ChapterParagraphInfo
from src.fact_graph.outputs import BoundParagraphLabel

from .errors import (
    AnnotationInvariantError,
    AnnotationStageRejection,
)

# 每章监督标签软下限只由章级指标状态维护，低覆盖只告警
_PARAGRAPH_LABEL_MIN_PER_CHAPTER = 2


class ChapterMetricsStateContext(Protocol):
    """只开放此工作状态需要的上下文和引用能力"""

    def _require_writable(self, record: str) -> None: ...

    paragraph_info: ChapterParagraphInfo | None


@dataclass(slots=True)
class ChapterMetricsState:
    metrics_payload: ChapterMetricsInput | None = None
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)

    def apply_metrics(self, ctx: ChapterMetricsStateContext, payload: ChapterMetricsInput) -> None:
        """用于写入当前章 摘要、叙事指标与段落情绪标签（重复提交整域覆盖）

        labels 的 paragraph_id 是段首可见号（正文每段开头的 `N：`），必须属于本章；
        越界段号整次提交拒绝并指明是哪一条标签。落库前按段落坐标映射
        换回全局 paragraph_id（绑定载荷与持久化口径不变）。
        """
        ctx._require_writable("metrics")
        if payload.labels:
            visible_to_global = dict(self._visible_global_pairs(ctx)) if ctx.paragraph_info is not None else {}
            for label in payload.labels:
                if label.paragraph_id not in visible_to_global:
                    preview = ", ".join(str(pid) for pid in sorted(visible_to_global)[:12]) or "（无）"
                    raise AnnotationStageRejection(
                        f"paragraph_id 不属于本章: {label.paragraph_id}",
                        record="metrics",
                        field="paragraph_id",
                        code="out_of_range",
                        expected=f"本章 可标注的段号（正文段首 `N：`）: {preview}"
                        f"{'…' if len(visible_to_global) > 12 else ''}",
                    )
            self.bound_payloads["paragraph_labels"] = [
                BoundParagraphLabel(
                    paragraph_id=visible_to_global[label.paragraph_id],
                    emotion=label.emotion,
                )
                for label in payload.labels
            ]
        else:
            self.bound_payloads["paragraph_labels"] = []
        self.metrics_payload = payload
        self.domain_payloads["metrics"] = payload

    def _visible_global_pairs(self, ctx: ChapterMetricsStateContext) -> list[tuple[int, int]]:
        """用于把段首可见号与全局 paragraph_id 配成对（落库映射的单一来源）"""
        assert ctx.paragraph_info is not None
        return list(zip(ctx.paragraph_info.visible_ids(), ctx.paragraph_info.paragraph_ids, strict=True))

    def metrics_content(self) -> dict[str, Any]:
        """用于回显 write_metrics 提交后的整域生效指标（整域覆盖，以最新回执为准）"""
        if self.metrics_payload is None:
            raise AnnotationInvariantError("write_metrics 回显需要 metrics_payload 已落账")
        return self.metrics_payload.model_dump(mode="json")

    def _paragraph_label_coverage_warnings(self) -> list[str]:
        """2026-09-07 用于在冻结前确定性登记段落级监督覆盖缺口（仅告警不阻断冻结）

        每章 2-3 段为定稿密度（2026-09-14 由句级改段级）；低于 2 段（含空载荷）
        随章留痕，供 linguistic 阶段边界拟合的样本量判断与报告附录展示。
        """
        labels = self.bound_payloads.get("paragraph_labels") or []
        if len(labels) >= _PARAGRAPH_LABEL_MIN_PER_CHAPTER:
            return []
        return [f"情绪标签覆盖: 仅标注 {len(labels)} 段（每章应自选 2-3 段）"]

    def fact_views(self) -> dict[str, Any]:
        """只返回章级指标事实，保持审计与当前生效载荷一致"""
        payloads = self.domain_payloads
        views: dict[str, Any] = {}
        if "metrics" in payloads:
            views["metrics"] = {
                "summary": payloads["metrics"].summary,
                "emotional_valence": str(payloads["metrics"].emotional_valence),
                "narrative_function": str(payloads["metrics"].narrative_function),
            }
        return views
