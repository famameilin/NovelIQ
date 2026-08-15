from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from src.metrics.aggregate.types import AnnotationData, TensionData


def _load_recompute_narrative_structure_module() -> ModuleType:
    """
    创建时间: 2026-05-02
    任务: fix-recompute-narrative-structure-alignment
    说明: `scripts/` 目录不是 Python package；这里按文件路径加载复算脚本模块，
          便于直接验证脚本内部对齐逻辑，而不改项目导入结构。
    """

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "tools" / "recompute_narrative_structure.py"
    spec = importlib.util.spec_from_file_location("test_recompute_narrative_structure_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_aligned_three_act_diagnostics_filters_null_tension_and_aligns_by_chunk_id() -> None:
    """
    创建时间: 2026-05-02
    任务: fix-recompute-narrative-structure-alignment
    说明: 复算脚本必须先按 chunk_id 对齐 annotation 与 tension，
          并跳过 NULL tension；否则会把错位事件喂给三幕分析，或直接触发 TypeError。
    """

    module = _load_recompute_narrative_structure_module()
    annotation_data = AnnotationData(
        chapter_ids=[10, 11, 12, 13],
        event_types=["铺垫", "转折", "铺垫", "冲突"],
        cliffhangers=[0, 1, 0, 1],
        pivot_moments=[0, 1, 0, 0],
        emotional_valences=["neutral", "neutral", "neutral", "neutral"],
    )
    tension_data = TensionData(
        chapter_ids=[11, 13, 10, 12],
        tension_composite_scores=[0.2, 0.9, 0.1, None],
    )

    diagnostics = module._build_aligned_three_act_diagnostics(annotation_data, tension_data)

    assert diagnostics is not None
    assert diagnostics.representative_peak_idx == 2
    assert diagnostics.climax_window_plot_flags == 3
