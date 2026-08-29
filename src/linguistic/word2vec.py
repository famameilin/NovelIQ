"""词向量能力（《分析能力扩展路线图》赛道 C3，可开关）

单流水线：公开预训练中文词向量做初始化，再用本书 LTP 词元继续训练
（warm-start 微调）——书内词站在预训练语义底子上微调，预训练未覆盖的
书内新词（人名等）随机初始化后由本书语料训练；模型产物保存为
models/word2vec/{run_id}.model（run 私有 artifact，随 run 删除）。

- POS 聚合向量：按段落、词性分组的词向量均值（word2vec_model_runs 的
  维度约束），覆盖率 = 词表内词数 / 该组原始词数，由查询层计算
- 默认关闭（settings.linguistic.word2vec.enabled=false），开启时预训练
  文件缺失或语料为空则明确报错，不静默回退
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from gensim.models import Word2Vec

from src.config import settings

#: 词列表接口（Word2Vec 训练与查询的输入面）
TokenizedSentence = Sequence[str]

#: 预训练词向量文件后缀 → 是否 word2vec 二进制格式（.bin 二进制，其余按文本解析）
_PRETRAINED_SUFFIXES = {".bin": True, ".vec": False, ".txt": False}


@dataclass(frozen=True)
class TrainResult:
    """按书微调产物摘要（word2vec_model_runs 契约）"""

    embedding_dimension: int
    vocabulary_size: int
    parameters: dict[str, Any]
    training_document_count: int
    training_token_count: int
    training_corpus_hash: str
    artifact_key: str
    artifact_sha256: str


def compute_corpus_hash(sentences: Sequence[TokenizedSentence]) -> str:
    """训练语料摘要：按文档顺序的 token 序列 sha256（内容或顺序变化即变）"""
    digest = hashlib.sha256()
    for sentence in sentences:
        digest.update(" ".join(sentence).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def resolve_pretrained_file(model_dir: Path) -> tuple[Path, bool]:
    """解析预训练词向量文件：目录下按可加载后缀取首个（.bin 二进制 / .vec、.txt 文本）"""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"预训练词向量目录不存在: {model_dir}")
    candidates = sorted(path for path in model_dir.glob("*") if path.suffix in _PRETRAINED_SUFFIXES)
    if not candidates:
        raise FileNotFoundError(f"预训练词向量目录中无可加载的词向量文件: {model_dir}")
    path = candidates[0]
    return path, _PRETRAINED_SUFFIXES[path.suffix]


def read_vector_size(path: Path) -> int:
    """从 word2vec 格式文件头（首行 "词数 维度"）读维度，避免整文件解析"""
    with path.open("rb") as fin:
        header = fin.readline()
    parts = header.split()
    if len(parts) < 2 or not parts[-1].isdigit():
        raise ValueError(f"预训练词向量文件头无法解析维度: {path}（首行 {header[:64]!r}）")
    return int(parts[-1])


def train_book_model(
    sentences: Sequence[TokenizedSentence],
    run_id: str,
    *,
    pretrained_path: Path,
    pretrained_binary: bool = False,
    window: int | None = None,
    min_count: int | None = None,
    epochs: int | None = None,
    output_dir: Path | None = None,
) -> TrainResult:
    """预训练词向量初始化 + 本书语料继续训练（warm-start 微调）

    - 先按本书词表 build_vocab，再用 intersect_word2vec_format 把预训练
      向量写入交集词（lockf=1.0 允许微调更新），预训练未覆盖的书内词
      保持随机初始化由本书语料训练
    - 维度以预训练文件头为准；模型保存到 models/word2vec/{run_id}.model
    - training_token_count 为全部文档的有效词元总数（含重复词元）
    """
    from src.storage.path_resolver import resolve_project_root

    w2v_settings = settings.linguistic.word2vec
    window = window if window is not None else w2v_settings.window
    min_count = min_count if min_count is not None else w2v_settings.min_count
    epochs = epochs if epochs is not None else w2v_settings.epochs

    non_empty = [s for s in sentences if s]
    if not non_empty:
        raise ValueError("Word2Vec 按书训练需要至少一个有词元的文档")
    total_tokens = sum(len(s) for s in non_empty)

    vector_size = read_vector_size(pretrained_path)
    model = Word2Vec(
        vector_size=vector_size,
        window=window,
        min_count=min_count,
        seed=42,
        workers=1,
    )
    model.build_vocab(non_empty)
    # gensim 4.4 的 vectors_lockf 默认 ones(1)（广播），intersect 按词索引赋值会越界，先展开到词表全长；
    # lockf=1.0 表示交集词微调期可更新
    model.wv.vectors_lockf = np.ones(len(model.wv))
    model.wv.intersect_word2vec_format(str(pretrained_path), binary=pretrained_binary, lockf=1.0)
    model.train(non_empty, total_examples=model.corpus_count, epochs=epochs)
    corpus_hash = compute_corpus_hash(non_empty)

    output_dir = output_dir or (resolve_project_root() / "models" / "word2vec")
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"{run_id}.model"
    model.save(str(model_path))

    parameters = {
        "vector_size": vector_size,
        "window": window,
        "min_count": min_count,
        "epochs": epochs,
        "seed": 42,
        "pretrained_file": pretrained_path.name,
    }
    return TrainResult(
        embedding_dimension=int(model.wv.vector_size),
        vocabulary_size=int(len(model.wv)),
        parameters=parameters,
        training_document_count=len(non_empty),
        training_token_count=total_tokens,
        training_corpus_hash=corpus_hash,
        artifact_key=f"models/word2vec/{run_id}.model",
        artifact_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
    )


@dataclass(frozen=True)
class PosEmbeddingRow:
    """段落词性聚合向量行（§5.7）"""

    paragraph_id: int
    pos_group: str
    embedding_vector: list[float] | None
    source_token_count: int
    in_vocabulary_token_count: int
    source_content_hash: str


def build_pos_embeddings(
    paragraph_tokens: Sequence[dict[str, str]],
    vectors,
    *,
    paragraph_id: int,
    source_content_hash: str,
) -> list[PosEmbeddingRow]:
    """按词性分组聚合段落词向量（组内词向量简单平均）。"""
    groups: dict[str, list[str]] = {}
    for token in paragraph_tokens:
        text = token.get("text", "")
        pos_group = token.get("pos_group", "other")
        if text:
            groups.setdefault(pos_group, []).append(text)
    # 兼容 KeyedVectors 与训练产物 Word2Vec（其词表在 .wv）
    wv = vectors.wv if hasattr(vectors, "wv") else vectors
    rows: list[PosEmbeddingRow] = []
    for pos_group, token_texts in groups.items():
        vectors_found: list[list[float]] = []
        for text in token_texts:
            try:
                vectors_found.append([float(v) for v in wv[text]])
            except KeyError:
                continue
        rows.append(
            PosEmbeddingRow(
                paragraph_id=paragraph_id,
                pos_group=pos_group,
                embedding_vector=(
                    [sum(dim) / len(vectors_found) for dim in zip(*vectors_found, strict=True)]
                    if vectors_found
                    else None
                ),
                source_token_count=len(token_texts),
                in_vocabulary_token_count=len(vectors_found),
                source_content_hash=source_content_hash,
            )
        )
    return rows
