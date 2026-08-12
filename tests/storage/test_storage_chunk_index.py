"""
chunk 索引持久化测试

覆盖 src/storage/chunk_index.py 的 write_chunk_index / read_chunk_index 往返。

2026-08-12 创建，补齐该模块 38% 的低覆盖率。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.chunking.chunker import Chunk
from src.chunking.index import build_chunk_index
from src.storage.chunk_index import read_chunk_index, write_chunk_index


def _make_chunks() -> list[Chunk]:
    return [
        Chunk(index=0, start=0, end=100, text="第一章文本", chapter_id=1),
        Chunk(index=1, start=100, end=200, text="第二章文本", chapter_id=2),
    ]


def test_write_read_roundtrip(tmp_path: Path) -> None:
    index = build_chunk_index(_make_chunks())
    path = tmp_path / "index.json"

    write_chunk_index(index, path)

    assert path.exists()
    restored = read_chunk_index(path)
    assert [chunk.index for chunk in restored.chunks] == [chunk.index for chunk in index.chunks]
    assert [chunk.text for chunk in restored.chunks] == [chunk.text for chunk in index.chunks]
    assert [chunk.chapter_id for chunk in restored.chunks] == [chunk.chapter_id for chunk in index.chunks]
    assert [chunk.start for chunk in restored.chunks] == [chunk.start for chunk in index.chunks]
    assert [chunk.end for chunk in restored.chunks] == [chunk.end for chunk in index.chunks]


def test_write_uses_ensure_ascii_false(tmp_path: Path) -> None:
    index = build_chunk_index(_make_chunks())
    path = tmp_path / "index.json"
    write_chunk_index(index, path)
    # 中文原样写入而非 \uXXXX 转义
    assert "第一章文本" in path.read_text(encoding="utf-8")


def test_read_rejects_non_list_json(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        read_chunk_index(path)


def test_read_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_chunk_index(tmp_path / "missing.json")
