"""全书指标纯计算入口：输入数据及业务参数均由调用方显式提供"""

from __future__ import annotations

from src.metrics.aggregate.computers import (
    compute_character_relation_metrics,
    compute_emotion_curve_metrics,
    compute_language_style_metrics,
    compute_narrative_structure_metrics,
)
from src.metrics.aggregate.types import AggregateInputs, AggregateResult


def aggregate_all_metrics(inputs: AggregateInputs, *, small_sample_min_chapters: int) -> AggregateResult:
    return AggregateResult(
        narrative_structure=compute_narrative_structure_metrics(
            inputs.annotation,
            inputs.tension,
            small_sample_min_chapters=small_sample_min_chapters,
        ),
        emotion_curve=compute_emotion_curve_metrics(
            inputs.emotion,
            inputs.annotation,
            inputs.characters,
            small_sample_min_chapters=small_sample_min_chapters,
        ),
        character_relations=compute_character_relation_metrics(
            inputs.relations,
            inputs.characters,
            inputs.total_chars,
        ),
        language_style=compute_language_style_metrics(inputs.text, inputs.dialogue.tones, inputs.style),
    )
