"""
主题查询组装器测试

覆盖 src/api/services/results_queries/topics.py 的 _fetch_topics：
- 无模型文件时降级（words 为空则过滤）
- 模型文件存在时填充词表/标签并归一化权重
- 模型加载异常时降级为警告

2026-08-12 创建，补齐该模块 17% 的低覆盖率。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.api.services.results_queries.topics import _fetch_topics


def _make_row(topic_id: int, total_weight: float) -> SimpleNamespace:
    return SimpleNamespace(topic_id=topic_id, total_weight=total_weight)


def _make_repo(rows: list[SimpleNamespace]) -> MagicMock:
    repo = MagicMock()
    repo.fetch_chunk_topics_agg.return_value = rows
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
    # 权重归一化：100 / (100 + 50)
    assert first.weight == round(100.0 / 150.0, 6)
    assert second.topic_id == 1
    assert second.label == "成长主题"
    assert second.weight == round(50.0 / 150.0, 6)


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
