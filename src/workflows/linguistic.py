"""语言结构基础数据阶段（《分析能力扩展路线图》§3.1 B/C 赛道）

执行顺序与落库契约：
1. LTP 词法/句法/实体：analyze_paragraph_batch → paragraph_linguistic_features
   （每段一行）+ paragraph_entities（实体候选，非图谱事实）
2. 固定短语：fixed_phrases.txt 词表匹配 → paragraph_phrase_hits
   （draft 词表不计入正式密度，is_metric_hit=false）
3. Word2Vec（可开关）：预训练词向量初始化 + 本书语料微调（warm-start）→
   word2vec_model_runs 契约 + paragraph_pos_embeddings（按词性聚合向量）

同 run 重跑先清后插（仓储层），不允许新旧结果混合；LTP 关闭时词法
阶段跳过（表为空），Word2Vec 关闭时不写契约行。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.api.models.events import StreamEvent
from src.config import settings
from src.config.constants import LEXICON_FILES
from src.linguistic import TrainResult
from src.storage.repositories import ParagraphRepository
from src.storage.repositories.linguistic_repository import LinguisticRepository


async def run_linguistic(
    run_id: str,
    session: Session,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """执行语言结构基础数据阶段，返回 (段落数, 词法特征段落数)。"""
    start_time = time.time()
    paragraph_repo = ParagraphRepository(session)
    ling_repo = LinguisticRepository(session)

    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    if not paragraph_rows:
        logger.warning(f"no paragraphs found for run_id={run_id}")
        return 0, 0

    ltp_settings = settings.linguistic.ltp
    w2v_settings = settings.linguistic.word2vec

    # ------------------------------------------------------------------
    # 1. LTP 词法/句法/实体
    # ------------------------------------------------------------------
    if ltp_settings.enabled:
        from src.linguistic import analyze_paragraph_batch

        logger.info(f"LTP 分析 {len(paragraph_rows)} 个段落...")
        results = analyze_paragraph_batch([row.text for row in paragraph_rows])

        feature_rows: list[dict] = []
        entity_rows: list[dict] = []
        for row, result in zip(paragraph_rows, results, strict=True):
            data = result.to_dict()
            data.update(
                {
                    "run_id": run_id,
                    "paragraph_id": row.paragraph_id,
                    "source_content_hash": row.content_hash,
                }
            )
            feature_rows.append(data)
            for entity in result.entities:
                entity_rows.append(
                    {
                        "run_id": run_id,
                        "paragraph_id": row.paragraph_id,
                        "surface_text": entity.surface_text,
                        "raw_entity_type": entity.raw_entity_type,
                        "normalized_entity_type": entity.normalized_entity_type,
                        "local_start_char": entity.local_start_char,
                        "local_end_char": entity.local_end_char,
                        "confidence": None,
                        "source_kind": "ltp",
                        "source_content_hash": row.content_hash,
                    }
                )
        ling_repo.insert_linguistic_features(run_id, feature_rows)
        ling_repo.insert_entities(run_id, entity_rows)
        logger.info(f"LTP 特征落库：段落={len(feature_rows)} 实体候选={len(entity_rows)}")
    else:
        feature_rows = []
        logger.info("linguistic.ltp.enabled=false，跳过词法/句法/实体")

    # ------------------------------------------------------------------
    # 2. 固定短语匹配（依赖 LTP 词法特征行：§5.5 双向 FK 要求 phrase_hits
    #    同时指向 paragraphs 与 paragraph_linguistic_features）
    # ------------------------------------------------------------------
    if ltp_settings.enabled:
        from src.lexicons import LexiconRegistry
        from src.linguistic import match_fixed_phrases

        registry = LexiconRegistry()
        terms = registry.get(LEXICON_FILES["fixed_phrases"])
        version_hash = registry.version_hash()
        phrase_rows: list[dict] = []
        for row in paragraph_rows:
            hits = match_fixed_phrases(
                row.text,
                terms,
                lexicon_key=LEXICON_FILES["fixed_phrases"],
                lexicon_version_hash=version_hash,
                metric_enabled=True,
            )
            for hit in hits:
                phrase_rows.append(
                    {
                        "run_id": run_id,
                        "paragraph_id": row.paragraph_id,
                        "surface_text": hit.surface_text,
                        "phrase_type": hit.phrase_type,
                        "local_start_char": hit.local_start_char,
                        "local_end_char": hit.local_end_char,
                        "match_kind": hit.match_kind,
                        "lexicon_key": hit.lexicon_key,
                        "lexicon_version_hash": hit.lexicon_version_hash,
                        "is_metric_hit": hit.is_metric_hit,
                        "source_content_hash": row.content_hash,
                    }
                )
        ling_repo.insert_phrase_hits(run_id, phrase_rows)
        logger.info(f"固定短语落库：{len(phrase_rows)} 行（词表 {LEXICON_FILES['fixed_phrases']}）")
    else:
        logger.info("ltp.enabled=false，跳过固定短语")

    # ------------------------------------------------------------------
    # 3. Word2Vec：预训练初始化 + 按书微调（依赖 LTP 词元）
    # ------------------------------------------------------------------
    if w2v_settings.enabled and ltp_settings.enabled:
        from src.linguistic import resolve_pretrained_file
        from src.storage.path_resolver import resolve_project_root

        if not w2v_settings.model_dir:
            raise ValueError("linguistic.word2vec.enabled=true 需要配置 model_dir（预训练词向量目录）")
        model_dir = Path(w2v_settings.model_dir)
        if not model_dir.is_absolute():
            model_dir = resolve_project_root() / model_dir
        pretrained_path, pretrained_binary = resolve_pretrained_file(model_dir)

        token_sequences: list[list[str]] = []
        paragraph_tokens: dict[int, list[dict[str, str]]] = {}
        for row, feature in zip(paragraph_rows, feature_rows, strict=True):
            tokens = [t for t in feature["tokens"] if t.get("text")]
            paragraph_tokens[row.paragraph_id] = tokens
            token_sequences.append([t["text"] for t in tokens])

        train_result, pos_rows_count = _train_and_build(
            run_id,
            ling_repo,
            token_sequences,
            paragraph_tokens,
            paragraph_rows,
            pretrained_path=pretrained_path,
            pretrained_binary=pretrained_binary,
            output_dir=resolve_project_root() / "models" / "word2vec",
        )
        logger.info(
            f"Word2Vec 预训练微调：vocab={train_result.vocabulary_size} "
            f"dim={train_result.embedding_dimension} pos_vectors={pos_rows_count}"
        )
    elif w2v_settings.enabled:
        logger.info("ltp.enabled=false，跳过词向量（按书微调依赖 LTP 词元）")
    else:
        logger.info("linguistic.word2vec.enabled=false，跳过词向量")

    elapsed = time.time() - start_time
    logger.info(f"linguistic completed paragraphs={len(paragraph_rows)} time={elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="linguistic", current=1, total=1, percent=100.0, sub_percent=100.0)
        )
    return len(paragraph_rows), len(feature_rows)


def _train_and_build(
    run_id: str,
    ling_repo: LinguisticRepository,
    token_sequences: list[list[str]],
    paragraph_tokens: dict[int, list[dict[str, str]]],
    paragraph_rows,
    *,
    pretrained_path: Path,
    pretrained_binary: bool,
    output_dir: Path,
) -> tuple[TrainResult, int]:
    """预训练初始化 + 按书微调 + 契约落库 + 词性聚合向量；返回 (TrainResult, pos 向量行数)"""
    from gensim.models import KeyedVectors

    from src.linguistic import build_pos_embeddings, train_book_model

    train_result = train_book_model(
        token_sequences,
        run_id,
        pretrained_path=pretrained_path,
        pretrained_binary=pretrained_binary,
        output_dir=output_dir,
    )
    ling_repo.insert_word2vec_model_run(
        run_id,
        {
            "run_id": run_id,
            "embedding_dimension": train_result.embedding_dimension,
            "vocabulary_size": train_result.vocabulary_size,
            "parameters": train_result.parameters,
            "source_uri": str(pretrained_path),
            "license_name": None,
            "training_corpus_hash": train_result.training_corpus_hash,
            "training_document_count": train_result.training_document_count,
            "training_token_count": train_result.training_token_count,
            "artifact_key": train_result.artifact_key,
            "artifact_sha256": train_result.artifact_sha256,
            "artifact_scope": "run_owned",
        },
    )
    vectors = KeyedVectors.load(str(output_dir / f"{run_id}.model"))
    pos_rows: list[dict] = []
    for row in paragraph_rows:
        tokens = paragraph_tokens.get(row.paragraph_id, [])
        for entry in build_pos_embeddings(
            tokens,
            vectors,
            paragraph_id=row.paragraph_id,
            source_content_hash=row.content_hash,
        ):
            pos_rows.append(
                {
                    "run_id": run_id,
                    "paragraph_id": entry.paragraph_id,
                    "pos_group": entry.pos_group,
                    "embedding_vector": entry.embedding_vector,
                    "source_token_count": entry.source_token_count,
                    "in_vocabulary_token_count": entry.in_vocabulary_token_count,
                    "source_content_hash": entry.source_content_hash,
                }
            )
    ling_repo.insert_pos_embeddings(run_id, pos_rows)
    return train_result, len(pos_rows)
