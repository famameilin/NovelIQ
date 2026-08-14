"""主题词查询与工具输出测试"""

from pathlib import Path

from src.agents.diagnosis.tools import _format_topic_rows
from src.storage.repositories.diagnosis_repository import _topic_words_from_model_dir


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
    result = _topic_words_from_model_dir(Path("models") / "topic" / "r1")
    assert result == {
        0: (["修炼"], "修行"),
        1: ([], "战斗"),
    }


def test_topic_words_missing_model_dir() -> None:
    assert _topic_words_from_model_dir(Path("__不存在的目录__")) == {}


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
