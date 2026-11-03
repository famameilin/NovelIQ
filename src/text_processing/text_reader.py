from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InputDocument:
    text: str
    source_path: Path
    title: str | None = None
    author: str | None = None
    genre: str | None = None


SOURCE_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk")


def decode_text_bytes(content: bytes, encodings: Iterable[str] | None = None) -> str:
    "按候选编码解码文本内容，全部失败时抛 UnicodeDecodeError"
    last_error: Exception | None = None
    for encoding in tuple(encodings) if encodings is not None else SOURCE_ENCODINGS:
        try:
            return content.decode(encoding)
        except Exception as exc:
            last_error = exc
    raise UnicodeDecodeError(str(last_error), b"", 0, 0, "unable to decode") from last_error


def read_text_file(path: Path, encodings: Iterable[str] | None = None) -> str:
    last_error: Exception | None = None
    for encoding in tuple(encodings) if encodings is not None else SOURCE_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except Exception as exc:
            last_error = exc
    raise UnicodeDecodeError(str(last_error), b"", 0, 0, "unable to decode") from last_error


def load_metadata(path: Path | None) -> dict:
    if path is None:
        return {}
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("metadata must be an object")
    return data


def ingest_path(source_path: Path, metadata_path: Path | None = None) -> list[InputDocument]:
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    metadata = load_metadata(metadata_path)
    docs: list[InputDocument] = []
    if source_path.is_file():
        text = read_text_file(source_path)
        docs.append(_build_document(source_path, text, metadata))
        return docs
    for path in sorted(source_path.glob("*.txt")):
        text = read_text_file(path)
        docs.append(_build_document(path, text, metadata))
    return docs


def _build_document(source_path: Path, text: str, metadata: dict) -> InputDocument:
    return InputDocument(
        text=text,
        source_path=source_path,
        title=_pick(metadata, "title"),
        author=_pick(metadata, "author"),
        genre=_pick(metadata, "genre"),
    )


def _pick(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    return value.strip() or None
