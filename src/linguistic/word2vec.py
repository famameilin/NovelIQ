"""词向量能力（《分析能力扩展路线图》赛道 C3，可开关）

单流水线：公开预训练中文词向量做初始化，再用本书 LTP 词元继续训练
（warm-start 微调）——书内词站在预训练语义底子上微调，预训练未覆盖的
书内新词（人名等）随机初始化后由本书语料训练；模型产物保存为
models/word2vec/{run_id}/word2vec.model（run 私有 artifact）。

预训练共享向量由 scripts/tools/convert_word2vec_pretrained.py 一次性
转成 .kv 落盘，运行时直接加载共享 KeyedVectors（进程级只加载一次），
不再重复解析 4.3GB 文本文件。

- POS 聚合向量：按段落、词性分组的词向量均值（word2vec_model_runs 的
  维度约束），覆盖率 = 词表内词数 / 该组原始词数，由查询层计算
- 默认关闭（settings.linguistic.word2vec.enabled=false），开启时预训练
  共享模型缺失或语料为空则明确报错，不静默回退
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from gensim.models import KeyedVectors, Word2Vec

from src.config import settings

#: 词列表接口（Word2Vec 训练与查询的输入面）
TokenizedSentence = Sequence[str]

#: 预训练共享 KeyedVectors 进程级缓存（按绝对路径 key，只加载一次）
_PRETRAINED_CACHE: dict[str, KeyedVectors] = {}
_PRETRAINED_CACHE_LOCK = threading.Lock()

#: 预训练共享模型文件后缀（转换脚本产物）
_KV_SUFFIX = ".kv"


def resolve_shared_pretrained_path(model_dir: Path) -> Path:
    """2026-08-30 用于解析共享模型目录中唯一的 KeyedVectors 主文件"""
    if not model_dir.is_dir():
        raise FileNotFoundError(
            f"预训练共享模型目录不存在: {model_dir}（请先执行 "
            f"python -m scripts.tools.convert_word2vec_pretrained）"
        )
    kv_files = sorted(path.resolve() for path in model_dir.glob(f"*{_KV_SUFFIX}") if path.is_file())
    if not kv_files:
        raise FileNotFoundError(
            f"预训练共享模型目录中没有 .kv 文件: {model_dir}（请先执行 "
            f"python -m scripts.tools.convert_word2vec_pretrained）"
        )
    if len(kv_files) != 1:
        raise ValueError(f"预训练共享模型目录必须恰好包含一个 .kv 文件: {model_dir}（当前 {len(kv_files)} 个）")
    return kv_files[0]


def load_shared_pretrained_vectors(model_dir: Path) -> KeyedVectors:
    """2026-08-30 用于以只读内存映射加载并缓存唯一的共享预训练向量"""
    kv_path = resolve_shared_pretrained_path(model_dir)
    with _PRETRAINED_CACHE_LOCK:
        cached = _PRETRAINED_CACHE.get(str(kv_path))
        if cached is not None:
            return cached
        vectors = KeyedVectors.load(str(kv_path), mmap="r")
        _PRETRAINED_CACHE[str(kv_path)] = vectors
        return vectors


def reset_pretrained_cache() -> None:
    """2026-08-30 用于在测试之间清除共享预训练向量进程级缓存"""
    with _PRETRAINED_CACHE_LOCK:
        _PRETRAINED_CACHE.clear()


@dataclass(frozen=True)
class TrainResult:
    """按书微调产物摘要（word2vec_model_runs 契约）"""

    embedding_dimension: int
    vocabulary_size: int
    parameters: dict[str, Any]
    training_document_count: int
    training_token_count: int
    artifact_key: str


def train_book_model(
    sentences: Sequence[TokenizedSentence],
    run_id: str,
    *,
    pretrained_vectors: KeyedVectors,
    window: int | None = None,
    min_count: int | None = None,
    epochs: int | None = None,
) -> TrainResult:
    """2026-08-30 用于以共享预训练向量初始化并微调 run 私有模型

    - 先按本书词表 build_vocab，再把共享预训练向量按词索引拷贝进交集词
      （全部词可微调，与旧 intersect lockf=1.0 语义等价），预训练未覆盖的
      书内词保持随机初始化由本书语料训练
    - 维度以预训练共享向量为准；模型保存到
      models/word2vec/{run_id}/word2vec.model（run 私有）
    - training_token_count 为全部文档的有效词元总数（含重复词元）
    """
    from src.storage.path_resolver import resolve_run_model_dir

    w2v_settings = settings.linguistic.word2vec
    window = window if window is not None else w2v_settings.window
    min_count = min_count if min_count is not None else w2v_settings.min_count
    epochs = epochs if epochs is not None else w2v_settings.epochs

    non_empty = [s for s in sentences if s]
    if not non_empty:
        raise ValueError("Word2Vec 按书训练需要至少一个有词元的文档")
    total_tokens = sum(len(s) for s in non_empty)

    vector_size = pretrained_vectors.vector_size
    model = Word2Vec(
        vector_size=vector_size,
        window=window,
        min_count=min_count,
        seed=42,
        workers=1,
    )
    model.build_vocab(non_empty)
    # 预训练共享向量按词索引拷贝进交集词；
    # gensim 4.4 的 vectors_lockf 默认 ones(1)（广播），按词索引赋值会越界，先展开到词表全长；
    # 全 1 表示微调期所有词都可更新（与旧 intersect_word2vec_format lockf=1.0 等价）
    model.wv.vectors_lockf = np.ones(len(model.wv))
    for idx, word in enumerate(model.wv.index_to_key):
        if word in pretrained_vectors:
            model.wv.vectors[idx] = pretrained_vectors[word]
    model.train(non_empty, total_examples=model.corpus_count, epochs=epochs)

    run_model_dir = resolve_run_model_dir(run_id, "word2vec")
    run_model_dir.mkdir(parents=True, exist_ok=True)
    model_path = run_model_dir / "word2vec.model"
    model.save(str(model_path))

    parameters = {
        "vector_size": vector_size,
        "window": window,
        "min_count": min_count,
        "epochs": epochs,
        "seed": 42,
        "pretrained_vocabulary_size": len(pretrained_vectors),
    }
    return TrainResult(
        embedding_dimension=int(model.wv.vector_size),
        vocabulary_size=int(len(model.wv)),
        parameters=parameters,
        training_document_count=len(non_empty),
        training_token_count=total_tokens,
        artifact_key=f"models/word2vec/{run_id}/word2vec.model",
    )


@dataclass(frozen=True)
class PosEmbeddingRow:
    """段落词性聚合向量行（§5.7）"""

    paragraph_id: int
    pos_group: str
    embedding_vector: list[float] | None
    source_token_count: int
    in_vocabulary_token_count: int


def build_pos_embeddings(
    paragraph_tokens: Sequence[dict[str, str]],
    vectors,
    *,
    paragraph_id: int,
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
            )
        )
    return rows
