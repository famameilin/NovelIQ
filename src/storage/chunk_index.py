from __future__ import annotations

import json
from pathlib import Path

from src.chunking.chunker import Chunk
from src.chunking.index import ChunkIndex, build_chunk_index


def write_chunk_index(index: ChunkIndex, path: Path) -> None:
    payload = [
        {
            "index": chunk.index,
            "text": chunk.text,
            "start": chunk.start,
            "end": chunk.end,
            "chapter_title": chunk.chapter_title,
        }
        for chunk in index.chunks
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_chunk_index(path: Path) -> ChunkIndex:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("chunk index must be a list")
    chunks: list[Chunk] = []
    for item in data:
        chunks.append(
            Chunk(
                index=int(item["index"]),
                text=str(item["text"]),
                start=int(item["start"]),
                end=int(item["end"]),
                chapter_title=item.get("chapter_title"),
            )
        )
    return build_chunk_index(chunks)
