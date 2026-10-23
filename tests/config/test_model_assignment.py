"""模型权重分配、独立连接和池内诊断选择"""

from typing import Any

import pytest

from src.config.schemas.model import WeightedModelSettings, _parse_model_pool
from src.config.settings import settings
from src.model_pool.configuration import load_task_config
from src.model_pool.selection import select_annotation_model


def _entry(model_id: str = "a", **overrides: Any) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "base_url": f"https://{model_id}.example/v1",
        "api_key": f"key-{model_id}",
        "weight": 1,
        "max_in_flight": 2,
        "context_window_tokens": 128000,
        **overrides,
    }


def test_weighted_assignment_is_stable_and_zero_weight_is_excluded() -> None:
    pool = _parse_model_pool([_entry("a"), _entry("b", weight=3), _entry("disabled", weight=0)])
    selections = [select_annotation_model(str(index), pool) for index in range(4000)]
    assert "disabled" not in selections
    assert 0.7 < selections.count("b") / len(selections) < 0.8
    assert select_annotation_model("task", pool) == select_annotation_model("task", pool)


def test_failed_model_keeps_its_reduced_weight_in_full_candidate_pool() -> None:
    pool = _parse_model_pool([_entry("a", weight=3), _entry("b")])
    selected = [select_annotation_model(str(index), pool, failures={"a": 2}) for index in range(4000)]
    assert 0.45 < selected.count("a") / len(selected) < 0.55
    assert select_annotation_model("alone", pool[:1], failures={"a": 1000}) == "a"


def test_model_below_health_threshold_is_not_selected() -> None:
    pool = _parse_model_pool([_entry("a"), _entry("b")])
    selected = [
        select_annotation_model(str(index), pool, scores={"a": 100, "b": 40})
        for index in range(1000)
    ]
    assert set(selected) == {"a"}


def test_all_models_below_health_threshold_returns_none() -> None:
    pool = _parse_model_pool([_entry("a"), _entry("b")])
    assert select_annotation_model("task", pool, scores={"a": 40, "b": 59.9}) is None


@pytest.mark.parametrize(
    "pool",
    [
        [],
        [_entry(weight=-1)],
        [_entry(weight=0)],
        [_entry(weight=True)],
        [_entry(weight=float("inf"))],
        [_entry(), _entry()],
        [_entry(max_in_flight=0)],
        [_entry(max_in_flight=True)],
        [_entry(max_in_flight=1.5)],
        [_entry(api_key="")],
        [_entry(api_key="key\nother=value")],
        [_entry(base_url="file:///tmp")],
        [_entry(base_url="https://user:secret@host/v1")],
        [_entry(base_url="https://host:bad/v1")],
    ],
)
def test_invalid_pool_is_rejected(pool: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        _parse_model_pool(pool)


def test_selected_models_use_their_own_credentials_and_concurrency(monkeypatch) -> None:
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        _parse_model_pool(
            [
                _entry("a"),
                _entry("b", max_in_flight=5, temperature=0.3, top_p=0.9, max_tokens=2048),
                _entry("diagnostic", weight=0, max_in_flight=1, temperature=0.1),
            ]
        ),
    )
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "diagnostic")
    selected = load_task_config("annotation", model_id="b")
    assert (selected.model, selected.base_url, selected.api_key, selected.max_in_flight) == (
        "b",
        "https://b.example/v1",
        "key-b",
        5,
    )
    # 采样参数跟随选中的池内模型
    assert (selected.temperature, selected.top_p, selected.max_tokens) == (0.3, 0.9, 2048)
    diagnosis = load_task_config("diagnosis")
    assert (diagnosis.model, diagnosis.base_url, diagnosis.api_key, diagnosis.max_in_flight) == (
        "diagnostic",
        "https://diagnostic.example/v1",
        "key-diagnostic",
        1,
    )
    assert (diagnosis.temperature, diagnosis.max_tokens) == (0.1, 131072)
    assert (
        load_task_config("annotation", selection_key="fixed").model
        == load_task_config(
            "annotation",
            selection_key="fixed",
        ).model
    )


def test_missing_diagnosis_selection_does_not_use_annotation_model(monkeypatch) -> None:
    monkeypatch.setattr(settings.models, "model_pool", _parse_model_pool([_entry()]))
    monkeypatch.setattr(settings.models, "diagnosis_model_id", None)
    with pytest.raises(ValueError, match="指定诊断"):
        load_task_config("diagnosis")


def test_empty_pool_and_removed_model_are_not_replaced(monkeypatch) -> None:
    monkeypatch.setattr(settings.models, "model_pool", [])
    with pytest.raises(ValueError, match="正权重"):
        load_task_config("annotation")
    with pytest.raises(ValueError, match="不在模型池"):
        load_task_config("annotation", model_id="removed")


def test_pool_repr_never_includes_api_key() -> None:
    entry = WeightedModelSettings("a", "https://a.example/v1", "secret", context_window_tokens=128000)
    assert "secret" not in repr(entry)


def test_no_separate_continuity_model() -> None:
    assert not hasattr(settings.models, "continuity")
