"审计观察文档的稳定字节编码（模型调用文档与 SSE 发件箱文档同式）"

from __future__ import annotations

import json
from typing import Any

_DOCUMENT_SEPARATORS = (",", ":")


def encode_document(value: Any) -> bytes:
    "把观察到的 JSON 语义值稳定编码为文档字节"
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=_DOCUMENT_SEPARATORS,
        default=str,
    ).encode("utf-8")


def decode_document(blob: bytes) -> Any:
    "把文档字节解码回原 JSON 语义"
    return json.loads(blob.decode("utf-8"))


def encode_text_document(text: str) -> bytes:
    "原始字符串观察（工具原始参数片段）按 UTF-8 原样编码"
    return text.encode("utf-8")


def decode_text_document(blob: bytes) -> str:
    "读回原始字符串观察"
    return blob.decode("utf-8")


__all__ = ["decode_document", "decode_text_document", "encode_document", "encode_text_document"]
