"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 operations.py 拆分分块相关操作

本模块包含分块相关的数据库操作函数。

修改时间: 2026-03-13
修改者: TraeAI
任务: refactor-core-data-layer-functions
修改内容: 添加 ChunkStyleData 数据类封装风格指标数据，重构 insert_chunk_style 函数支持新旧两种参数形式
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple, Union

from src.chunking.chunker import Chunk


@dataclass(frozen=True)
class ChunkStyleData:
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
    cultural_density: float
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

    def to_tuple(
        self,
    ) -> Tuple[
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
            self.cultural_density,
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
        )


def insert_chunks(conn: sqlite3.Connection, chunks: Sequence[Chunk]) -> None:
    rows = [(chunk.index, None, chunk.start, chunk.text) for chunk in chunks]
    conn.executemany(
        "INSERT INTO chunks (chunk_id, chapter_id, char_offset, text) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def fetch_chunk_texts(conn: sqlite3.Connection) -> List[Tuple[int, str]]:
    cursor = conn.execute("SELECT chunk_id, text FROM chunks ORDER BY chunk_id")
    return cursor.fetchall()


def insert_chunk_style(
    conn: sqlite3.Connection,
    rows: Union[
        Iterable[ChunkStyleData],
        Iterable[
            Tuple[
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
            ]
        ],
    ],
) -> None:
    tuple_rows: List[
        Tuple[
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
        ]
    ] = []
    for row in rows:
        if isinstance(row, ChunkStyleData):
            tuple_rows.append(row.to_tuple())
        else:
            tuple_rows.append(row)
    conn.executemany(
        """
        INSERT INTO chunk_style (
            chunk_id, mtld, ttr, avg_sent_len, sent_len_std, d_value,
            pause_density, fight_density, exclaim_density, dialogue_ratio, question_density,
            sensory_density, metaphor_density, cultural_density,
            function_word_vector,
            category_density_combat, category_density_body, category_density_relation,
            category_density_faction, category_density_command, category_density_action,
            category_density_psychology, category_density_measure, category_density_emotion,
            category_density_color
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple_rows,
    )
    conn.commit()


def insert_chunk_culture(
    conn: sqlite3.Connection,
    rows: Iterable[Tuple[int, float, float, float, float, float, float]],
) -> None:
    conn.executemany(
        """
        INSERT INTO chunk_culture (
            chunk_id, confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        list(rows),
    )
    conn.commit()


def fetch_chunk_styles(conn: sqlite3.Connection) -> List[Tuple[int, float, float, float]]:
    cursor = conn.execute(
        "SELECT chunk_id, dialogue_ratio, sent_len_std, avg_sent_len FROM chunk_style ORDER BY chunk_id"
    )
    return cursor.fetchall()


def insert_chunk_topics(
    conn: sqlite3.Connection,
    rows: Iterable[Tuple[int, int, float]],
) -> None:
    conn.executemany(
        """
        INSERT INTO chunk_topics (chunk_id, topic_id, topic_weight)
        VALUES (?, ?, ?)
        """,
        list(rows),
    )
    conn.commit()


def clear_chunk_topics(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM chunk_topics")
    conn.commit()
