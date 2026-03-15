from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u3000", " ").replace("\t", " ")
    normalized = re.sub(r"[ ]{2,}", " ", normalized)
    return normalized.strip()


def strip_empty_lines(text: str) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join([line for line in lines if line])
