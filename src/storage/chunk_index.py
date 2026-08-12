from __future__ import annotations

import json
from pathlib import Path

from src.chunking.index import ChunkIndex, build_chunk_index


def write_chunk_index(index: ChunkIndex, path: Path) -> None:
    payload = [
        {
            "index": chunk.index,
            "text": chunk.text,
            "start": chunk.start,
            "end": chunk.end,
            "chapter_id": chunk.chapter_id,
        }
        for chunk in index.chunks
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_chunk_index(path: Path) -> ChunkIndex:
    from src.chunking.chunker import Chunk

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("chunk index must be a list")
    chunks: list[Chunk] = []
    for item in data:
        chapter_id = item.get("chapter_id")
        if chapter_id is None:
            raise ValueError(
                "chunk index 文件格式不兼容：缺少 chapter_id 键（可能是旧版 "
                "chapter_title 格式索引），请删除旧索引文件并重新构建 chunk index"
            )
        chunks.append(
            Chunk(
                index=int(item["index"]),
                text=str(item["text"]),
                start=int(item["start"]),
                end=int(item["end"]),
                chapter_id=int(chapter_id),
            )
        )
    return build_chunk_index(chunks)
