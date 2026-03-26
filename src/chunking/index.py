from __future__ import annotations

from dataclasses import dataclass

from .chunker import Chunk


@dataclass(frozen=True)
class ChunkIndex:
    chunks: list[Chunk]

    def total(self) -> int:
        return len(self.chunks)

    def get(self, index: int) -> Chunk:
        return self.chunks[index]

    def validate(self) -> None:
        expected = list(range(len(self.chunks)))
        actual = [chunk.index for chunk in self.chunks]
        if actual != expected:
            raise ValueError("chunk indices are not contiguous")
        for chunk in self.chunks:
            if chunk.start >= chunk.end:
                raise ValueError("chunk range is invalid")


def build_chunk_index(chunks: list[Chunk]) -> ChunkIndex:
    reindexed = [
        Chunk(
            index=idx,
            text=chunk.text,
            start=chunk.start,
            end=chunk.end,
            chapter_title=chunk.chapter_title,
        )
        for idx, chunk in enumerate(chunks)
    ]
    index = ChunkIndex(reindexed)
    index.validate()
    return index
