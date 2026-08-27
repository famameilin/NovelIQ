"""
主题查询组装器测试

覆盖 src/api/services/results_queries/topics.py 的 _fetch_topics：
- 聚合源为 ParagraphRepository.fetch_paragraph_topics_agg（token 加权，§11.1），
  归一化使用 weighted_total
- 无模型文件时降级（words 为空则过滤）
- 模型文件存在时填充词表/标签并归一化权重
- 模型加载异常时降级为警告

2026-08-12 创建，补齐该模块 17% 的低覆盖率。
Paragraph-only 主题结果：fetch_paragraph_topics_agg 使用 weighted_total。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.api.services.results_queries.topics import _fetch_topics, _validate_agg_row


def _make_row(topic_id: int, weighted_total: float) -> SimpleNamespace:
    return SimpleNamespace(topic_id=topic_id, weighted_total=weighted_total)


def _make_repo(rows: list[SimpleNamespace]) -> MagicMock:
    repo = MagicMock()
    repo.fetch_paragraph_topics_agg.return_value = rows
    return repo


def _make_trainer_with_model() -> MagicMock:
    model = MagicMock()
    model.num_topics = 2
    model.get_topic_words.side_effect = [
        [SimpleNamespace(word="修炼"), SimpleNamespace(word="境界")],
        [SimpleNamespace(word="成长"), SimpleNamespace(word="历练")],
    ]
    model.labels = {0: "修炼主题", 1: "成长主题"}

    trainer = MagicMock()
    trainer.load_model.return_value = model
    return trainer


def test_fetch_topics_without_model_dir_returns_empty() -> None:
    repo = _make_repo([_make_row(0, 100.0)])
    # models/topic/{run_id} 目录不存在（默认行为）
    result = _fetch_topics("run-no-model", repo)
    assert result == []


def test_fetch_topics_with_model_fills_words_labels_and_normalizes() -> None:
    repo = _make_repo([_make_row(0, 100.0), _make_row(1, 50.0)])
    trainer = _make_trainer_with_model()

    with (
        patch.object(Path, "exists", return_value=True),
        patch("src.topic.LDATrainer", return_value=trainer),
    ):
        result = _fetch_topics("run-1", repo)

    assert len(result) == 2
    first, second = result
    assert first.topic_id == 0
    assert list(first.words) == ["修炼", "境界"]
    assert first.label == "修炼主题"
    # 权重归一化：weighted_total / sum(weighted_total) = 100 / (100 + 50)
    assert first.weight == round(100.0 / 150.0, 6)
    assert second.topic_id == 1
    assert second.label == "成长主题"
    assert second.weight == round(50.0 / 150.0, 6)


def test_fetch_topics_uses_paragraph_aggregation_source() -> None:
    """2026-08-20 验证主题查询只调用段落聚合源"""
    repo = _make_repo([])
    _fetch_topics("run-source", repo)
    repo.fetch_paragraph_topics_agg.assert_called_once_with("run-source")


def test_fetch_topics_model_load_failure_degrades() -> None:
    repo = _make_repo([_make_row(0, 100.0)])
    trainer = MagicMock()
    trainer.load_model.side_effect = FileNotFoundError("model missing")

    with (
        patch.object(Path, "exists", return_value=True),
        patch("src.topic.LDATrainer", return_value=trainer),
    ):
        result = _fetch_topics("run-broken", repo)

    # 加载失败 → words 为空 → 该主题被过滤
    assert result == []


def test_fetch_topics_empty_rows_returns_empty() -> None:
    repo = _make_repo([])
    assert _fetch_topics("run-empty", repo) == []


def test_fetch_topics_model_dir_anchored_at_project_root() -> None:
    """
    2026-08-13 P2：模型目录必须基于项目根推导（以 config/settings.json 为锚点），
    而不是相对 CWD 解析，避免服务启动目录不同导致词表/标签加载静默降级。
    """
    from src.storage.path_resolver import resolve_model_dir

    repo = _make_repo([_make_row(0, 100.0)])
    trainer = _make_trainer_with_model()

    with (
        patch.object(Path, "exists", return_value=True),
        patch("src.topic.LDATrainer", return_value=trainer),
    ):
        result = _fetch_topics("run-anchored", repo)

    assert len(result) == 1
    loaded_dir = trainer.load_model.call_args.args[0]
    assert loaded_dir == resolve_model_dir("run-anchored")


def test_validate_agg_row_rejects_missing_fields() -> None:
    """2026-08-20 验证聚合结果缺字段时快速失败"""
    with pytest.raises(RuntimeError, match="缺少"):
        _validate_agg_row(SimpleNamespace(topic_id=1))


@pytest.mark.parametrize("weighted_total", [float("nan"), float("inf"), -1.0])
def test_validate_agg_row_rejects_invalid_weight(weighted_total: float) -> None:
    """2026-08-20 验证聚合权重必须是非负有限数"""
    with pytest.raises(RuntimeError, match="weighted_total"):
        _validate_agg_row(SimpleNamespace(topic_id=1, weighted_total=weighted_total))
