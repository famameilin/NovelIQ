"""主题词查询与工具输出测试"""

from pathlib import Path

from src.agents.diagnosis.tools import _format_topic_rows
from src.topic.artifacts import load_topic_artifact


def test_topic_words_load_with_words(monkeypatch) -> None:
    monkeypatch.setattr(Path, "exists", lambda self: True)

    def fake_load(self, model_dir: Path):
        class FakeWord:
            word = "修炼"

        class FakeModel:
            num_topics = 2
            labels: dict = {0: "修行", 1: "战斗"}

            def get_topic_words(self, topic_id: int, top_n: int = 10):
                return [FakeWord()] if topic_id == 0 else []

        return FakeModel()

    monkeypatch.setattr("src.topic.LDATrainer.load_model", fake_load)
    from src.config.paths import resolve_model_dir

    result = load_topic_artifact(resolve_model_dir("r1"))
    assert result == ({0: ["修炼"], 1: []}, {0: "修行", 1: "战斗"}, None)


def test_topic_words_missing_model_dir() -> None:
    words, labels, reason = load_topic_artifact(Path("__不存在的目录__"))
    assert words == {} and labels == {}
    assert reason is not None and reason.startswith("topic_model_artifact_missing:")


def test_format_topic_rows_with_words() -> None:
    rows = [
        {"topic_id": 23, "weight": 2.0737, "words": ["修炼", "境界"], "label": "修行"},
        {"topic_id": 7, "weight": 1.2, "words": [], "label": None},
    ]
    text = _format_topic_rows(rows)
    assert "修炼" in text
    assert "境界" in text
    assert "topic 23" in text
    assert "2.0737" in text
