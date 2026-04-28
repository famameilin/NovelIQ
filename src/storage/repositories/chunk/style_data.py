"""
分块风格数据类

移除 cultural_density 字段

将 imagery_lexicon_density 并入 ChunkStyleData，移除独立 culture 兼容写入链路
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkStyleData:
    """
    分块风格数据类

    封装分块风格指标数据，从 chunk_ops.py 迁移

    移动到独立模块

    移除 cultural_density 字段
    """

    chunk_id: int
    mtld: float
    ttr: float
    avg_sent_len: float
    sent_len_std: float
    d_value: float
    pause_density: float
    fight_density: float
    exclaim_density: float
    dialogue_ratio: float
    question_density: float
    sensory_density: float
    metaphor_density: float
    function_word_vector: str
    category_density_combat: float
    category_density_body: float
    category_density_relation: float
    category_density_faction: float
    category_density_command: float
    category_density_action: float
    category_density_psychology: float
    category_density_measure: float
    category_density_emotion: float
    category_density_color: float
    imagery_lexicon_density: float | None = None

    def to_tuple(
        self,
    ) -> tuple[
        int,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        str,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float | None,
    ]:
        return (
            self.chunk_id,
            self.mtld,
            self.ttr,
            self.avg_sent_len,
            self.sent_len_std,
            self.d_value,
            self.pause_density,
            self.fight_density,
            self.exclaim_density,
            self.dialogue_ratio,
            self.question_density,
            self.sensory_density,
            self.metaphor_density,
            self.function_word_vector,
            self.category_density_combat,
            self.category_density_body,
            self.category_density_relation,
            self.category_density_faction,
            self.category_density_command,
            self.category_density_action,
            self.category_density_psychology,
            self.category_density_measure,
            self.category_density_emotion,
            self.category_density_color,
            self.imagery_lexicon_density,
        )

    def to_dict(self, run_id: str) -> dict:
        """转换为字典格式，用于 bulk_insert_mappings"""
        return {
            "chunk_id": self.chunk_id,
            "mtld": self.mtld,
            "ttr": self.ttr,
            "avg_sent_len": self.avg_sent_len,
            "sent_len_std": self.sent_len_std,
            "d_value": self.d_value,
            "pause_density": self.pause_density,
            "fight_density": self.fight_density,
            "exclaim_density": self.exclaim_density,
            "dialogue_ratio": self.dialogue_ratio,
            "question_density": self.question_density,
            "sensory_density": self.sensory_density,
            "metaphor_density": self.metaphor_density,
            "function_word_vector": self.function_word_vector,
            "category_density_combat": self.category_density_combat,
            "category_density_body": self.category_density_body,
            "category_density_relation": self.category_density_relation,
            "category_density_faction": self.category_density_faction,
            "category_density_command": self.category_density_command,
            "category_density_action": self.category_density_action,
            "category_density_psychology": self.category_density_psychology,
            "category_density_measure": self.category_density_measure,
            "category_density_emotion": self.category_density_emotion,
            "category_density_color": self.category_density_color,
            "imagery_lexicon_density": self.imagery_lexicon_density,
            "run_id": run_id,
        }
