from __future__ import annotations

import re

from src.text_processing.tokenize import Tokenizer, get_tokenizer, tokenize


def normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u3000", " ").replace("\t", " ")
    normalized = re.sub(r"[ ]{2,}", " ", normalized)
    return normalized.strip()


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


__all__ = [
    "normalize_text",
    "split_paragraphs",
    "split_sentences",
    "Tokenizer",
    "get_tokenizer",
    "tokenize",
]
