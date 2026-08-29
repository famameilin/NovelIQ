"""主题模型 artifact 与训练语料的确定性哈希（《分析能力扩展路线图》§5.8）。

artifact_sha256 覆盖模型目录全部文件，training_corpus_hash 覆盖训练域与
推断域的段落内容摘要；二者都要求同一内容重跑得到相同值，内容变化必然
改变哈希，用于重算校验与 artifact GC 审计。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class TopicParagraphRow(Protocol):
    """training_corpus_hash 需要的段落行字段"""

    paragraph_id: int
    content_hash: str


def compute_artifact_directory_sha256(directory: Path) -> str:
    """模型目录确定性清单哈希（§5.8 artifact_sha256）

    对目录下所有文件按相对路径排序，聚合 (relpath, file_sha256) 清单的
    哈希；文件内容或相对路径变化都会改变结果。目录不存在时快速失败，
    不允许对不完整的模型目录生成契约。
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"模型 artifact 目录不存在: {directory}")
    entries: list[tuple[str, str]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel_path = path.relative_to(directory).as_posix()
            entries.append((rel_path, hashlib.sha256(path.read_bytes()).hexdigest()))
    digest = hashlib.sha256()
    for rel_path, file_sha256 in entries:
        digest.update(f"{rel_path}\0{file_sha256}\n".encode())
    return digest.hexdigest()


def compute_training_corpus_hash(paragraph_rows: Sequence[TopicParagraphRow]) -> str:
    """训练语料摘要（§5.8 training_corpus_hash）

    按 paragraph_id 升序拼接 (paragraph_id, content_hash) 生成摘要；
    段落内容或顺序变化即改变哈希。
    """
    digest = hashlib.sha256()
    for row in sorted(paragraph_rows, key=lambda r: r.paragraph_id):
        digest.update(f"{row.paragraph_id}:{row.content_hash}\n".encode())
    return digest.hexdigest()