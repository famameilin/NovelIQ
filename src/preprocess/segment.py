from __future__ import annotations

import re


def split_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    blocks = re.split(r"\n{2,}", text)
    return [block.strip() for block in blocks if block.strip()]


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[。！？!?]+|\n+", text)
    return [part.strip() for part in parts if part.strip()]
