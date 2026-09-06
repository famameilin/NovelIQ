"""语言结构基础数据阶段（《分析能力扩展路线图》§3.1 B/C 赛道）

执行顺序与落库契约：
1. LTP 词法/句法/实体/语义：analyze_paragraph_batch（cws/pos/ner/dep/sdp）→
   paragraph_linguistic_features（每段一行）+ paragraph_entities（实体候选，非图谱事实）
2. 固定短语：fixed_phrases.txt 词表匹配 → paragraph_phrase_hits
   （draft 词表不计入正式密度，is_metric_hit=false）
3. 情绪事件与 mNEG 修正（2026-09-05 B 批，2026-09-05 ltp.enabled 时生效）：
   情绪词典只做谓词极性候选标记，持有者/对象/否定/程度取 sdp 的 AGT/DATV/
   mNEG/mDEPD；mNEG 接管词典否定翻转后回写 paragraph_metrics 情绪计数并
   整卷重算段落曲线（对照计数留痕在 paragraph_linguistic_features）
4. Word2Vec（可开关）：预训练词向量初始化 + 本书语料微调（warm-start）→
   word2vec_model_runs 契约 + paragraph_pos_embeddings（按词性聚合向量）

同 run 重跑先清后插（仓储层），不允许新旧结果混合；LTP 关闭时词法
阶段跳过（表为空），Word2Vec 关闭时不写契约行。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from gensim.models import KeyedVectors, Word2Vec
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
    *,
    batch_size: int = 128,
) -> tuple[int, int]:
    """2026-08-30 用于执行语言结构阶段并返回段落数与词法特征段落数

    batch_size 控制每批处理的段落数并限制阶段内存峰值
    """
    start_time = time.time()
    paragraph_repo = ParagraphRepository(session)
    ling_repo = LinguisticRepository(session)

    ltp_settings = settings.linguistic.ltp
    w2v_settings = settings.linguistic.word2vec

    # 分批处理控制内存峰值：段落文本、LTP 输出、feature/entity/phrase 行都只保留当前批，
    # 不随全书段落数线性增长。Word2Vec 需要全书词元训练，token_sequences 仍全量累积。
    total_paragraphs = paragraph_repo.count_paragraphs(run_id)
    if total_paragraphs == 0:
        logger.warning(f"no paragraphs found for run_id={run_id}")
        return 0, 0
    total_feature_paragraphs = 0
    token_sequences: list[list[str]] = []
    paragraph_tokens: dict[int, list[dict[str, str]]] = {}

    if ltp_settings.enabled:
        from src.lexicons import LexiconRegistry
        from src.lexicons.tables import NEGATIVE_TERMS, POSITIVE_TERMS
        from src.linguistic import (
            analyze_paragraph_batch,
            extract_emotion_events,
            match_fixed_phrases,
            mneg_corrected_counts,
        )

        registry = LexiconRegistry()
        terms = registry.get(LEXICON_FILES["fixed_phrases"])

        # 2026-09-05 B 批：词典情绪计数对照基线（命中集与 preprocess 同源，
        # 读 paragraph_metrics 现值作为窗口规则口径）
        lexicon_counts = {
            int(metric_row.paragraph_id): (
                float(metric_row.positive_weight_sum or 0.0),
                float(metric_row.negative_weight_sum or 0.0),
            )
            for metric_row in paragraph_repo.fetch_paragraph_metrics(run_id)
        }
        # mNEG 修正回写清单（paragraph_id → 修正后计数）
        mneg_corrections: list[dict[str, float | int]] = []

        last_id: int | None = None
        first_batch = True
        while True:
            batch = paragraph_repo.fetch_paragraph_rows_batch(
                run_id, after_id=last_id, limit=batch_size
            )
            if not batch:
                break
            last_id = batch[-1].paragraph_id

            logger.info(
                f"LTP 分析 {len(batch)} 个段落（游标 after={last_id}）..."
            )
            results = analyze_paragraph_batch([row.text for row in batch])

            feature_rows: list[dict] = []
            entity_rows: list[dict] = []
            for row, result in zip(batch, results, strict=True):
                data = result.to_dict()
                # 2026-09-05 B 批：词典极性候选标记 × sdp 结构 → 情绪事件 + mNEG 修正计数
                events = extract_emotion_events(result, POSITIVE_TERMS, NEGATIVE_TERMS)
                mneg_pos, mneg_neg = mneg_corrected_counts(
                    row.text,
                    result.tokens,
                    result.sdp_arcs,
                    POSITIVE_TERMS,
                    NEGATIVE_TERMS,
                )
                lexicon_pos, lexicon_neg = lexicon_counts.get(int(row.paragraph_id), (0.0, 0.0))
                data["emotion_events"] = [event.to_dict() for event in events]
                data["emotion_event_count"] = len(events)
                data["emotion_pos_event_count"] = sum(1 for event in events if event.polarity == "positive")
                data["emotion_neg_event_count"] = sum(1 for event in events if event.polarity == "negative")
                data["lexicon_pos_count"] = lexicon_pos
                data["lexicon_neg_count"] = lexicon_neg
                data["mneg_pos_count"] = mneg_pos
                data["mneg_neg_count"] = mneg_neg
                data.update(
                    {
                        "run_id": run_id,
                        "paragraph_id": row.paragraph_id,
                    }
                )
                feature_rows.append(data)
                mneg_corrections.append(
                    {
                        "paragraph_id": int(row.paragraph_id),
                        "mneg_pos": mneg_pos,
                        "mneg_neg": mneg_neg,
                    }
                )
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
                        }
                    )
                # Word2Vec 按书微调需要全书词元序列，逐批累积
                tokens = [t for t in data["tokens"] if t.get("text")]
                paragraph_tokens[row.paragraph_id] = tokens
                token_sequences.append([t["text"] for t in tokens])

            ling_repo.insert_linguistic_features(run_id, feature_rows, clear_first=first_batch)
            ling_repo.insert_entities(run_id, entity_rows, clear_first=first_batch)
            total_feature_paragraphs += len(feature_rows)
            logger.info(
                f"LTP 特征落库：段落={len(feature_rows)} 实体候选={len(entity_rows)}"
            )

            # 固定短语匹配：词表命中 + 四字候选（依赖 LTP 词法特征行）
            # 2026-09-05 C 批：draft 词表（body_reaction/colloquial 扩表候选）
            # 同扫描，命中行 is_metric_hit=false——审定门，不计入正式密度
            phrase_rows: list[dict] = []
            draft_terms: dict[str, list[str]] = {
                LEXICON_FILES["body_reaction_draft"]: registry.get(LEXICON_FILES["body_reaction_draft"]),
                LEXICON_FILES["colloquial_expansion_draft"]: registry.get(
                    LEXICON_FILES["colloquial_expansion_draft"]
                ),
            }
            for row in batch:
                hits = match_fixed_phrases(
                    row.text,
                    terms,
                    lexicon_key=LEXICON_FILES["fixed_phrases"],
                    metric_enabled=False,
                )
                for draft_key, draft_list in draft_terms.items():
                    hits.extend(
                        match_fixed_phrases(
                            row.text,
                            draft_list,
                            lexicon_key=draft_key,
                            metric_enabled=False,
                            four_char_candidate_enabled=False,
                        )
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
                            "is_metric_hit": hit.is_metric_hit,
                        }
                    )
            ling_repo.insert_phrase_hits(run_id, phrase_rows, clear_first=first_batch)
            logger.info(f"固定短语落库：{len(phrase_rows)} 行（词表 {LEXICON_FILES['fixed_phrases']}）")
            first_batch = False

        if total_paragraphs == 0:
            logger.warning(f"no paragraphs found for run_id={run_id}")
            return 0, 0
        logger.info(f"LTP 全库完成：段落={total_paragraphs} 词法特征段落={total_feature_paragraphs}")

        # 2026-09-05 B 批：mNEG 接管词典否定翻转——回写 paragraph_metrics 情绪
        # 计数并按新分子整卷重算段落曲线（聚合/曲线/零信号占比随之切换口径）
        corrected = _apply_mneg_correction(session, run_id, paragraph_repo, mneg_corrections)
        if corrected:
            logger.info(f"mNEG 情绪修正回写：{corrected} 段（sdp 否定辖域替代窗口规则），段落曲线已重算")
    else:
        logger.info("linguistic.ltp.enabled=false，跳过词法/句法/实体与固定短语")

    # ------------------------------------------------------------------
    # Word2Vec：预训练初始化 + 按书微调（依赖 LTP 词元）
    # ------------------------------------------------------------------
    if w2v_settings.enabled and ltp_settings.enabled:
        from src.linguistic import load_shared_pretrained_vectors, resolve_shared_pretrained_path
        from src.storage.path_resolver import resolve_project_root

        if not w2v_settings.model_dir:
            raise ValueError("linguistic.word2vec.enabled=true 需要配置 model_dir（预训练共享模型目录）")
        model_dir = Path(w2v_settings.model_dir)
        if not model_dir.is_absolute():
            model_dir = resolve_project_root() / model_dir
        pretrained_path = resolve_shared_pretrained_path(model_dir)
        pretrained_vectors = load_shared_pretrained_vectors(model_dir)

        train_result, pos_rows_count = _train_and_build(
            run_id,
            ling_repo,
            token_sequences,
            paragraph_tokens,
            pretrained_vectors=pretrained_vectors,
            pretrained_source=str(pretrained_path),
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
    logger.info(f"linguistic completed paragraphs={total_paragraphs} time={elapsed:.2f}s")

    if emitter:
        await emitter(
            StreamEvent(action="complete", stage="linguistic", current=1, total=1, percent=100.0, sub_percent=100.0)
        )
    return total_paragraphs, total_feature_paragraphs


def _apply_mneg_correction(
    session: Session,
    run_id: str,
    paragraph_repo: ParagraphRepository,
    corrections: list[dict[str, float | int]],
) -> int:
    """2026-09-05 B 批：mNEG 情绪修正回写（sdp 否定辖域接管窗口规则）

    命中集与 preprocess 完全一致（同一 get_emotion_spans 短语匹配），唯一差异
    是翻转判定由 sdp mNEG 决定；回写 paragraph_metrics 两列后按新分子整卷重算
    段落曲线（compute_paragraph_curves 与 preprocess 同一函数，LOWESS 参数同源），
    聚合层 emotion_avg / lexicon_zero_hit_share 与前端曲线随之切换口径。
    """
    if not corrections:
        return 0

    from sqlalchemy import bindparam, update
    from sqlalchemy.sql.schema import Table as SaTable

    from src.storage.models import ParagraphMetric
    from src.workflows.paragraph_curves import compute_paragraph_curves

    # Core 表对象（绕开 ORM 按主键批量更新拦截）；synchronize_session=False 同理
    metric_table = cast(SaTable, ParagraphMetric.__table__)
    statement = (
        update(metric_table)
        .where(
            metric_table.c.run_id == bindparam("b_run_id"),
            metric_table.c.paragraph_id == bindparam("b_paragraph_id"),
        )
        .values(
            positive_weight_sum=bindparam("b_pos"),
            negative_weight_sum=bindparam("b_neg"),
        )
    )
    params = [
        {
            "b_run_id": run_id,
            "b_paragraph_id": row["paragraph_id"],
            "b_pos": float(row["mneg_pos"]),
            "b_neg": float(row["mneg_neg"]),
        }
        for row in corrections
    ]
    session.execute(statement, params, execution_options={"synchronize_session": False})

    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    metric_rows = paragraph_repo.fetch_paragraph_metrics(run_id)
    total_chars = sum(int(row.char_count or 0) for row in paragraph_rows)
    curve_rows = compute_paragraph_curves(paragraph_rows, metric_rows, total_chars)
    paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
    return len(params)


def _train_and_build(
    run_id: str,
    ling_repo: LinguisticRepository,
    token_sequences: list[list[str]],
    paragraph_tokens: dict[int, list[dict[str, str]]],
    *,
    pretrained_vectors: KeyedVectors,
    pretrained_source: str,
) -> tuple[TrainResult, int]:
    """2026-08-30 用于完成预训练微调落库并构建词性聚合向量"""
    from src.linguistic import build_pos_embeddings, train_book_model
    from src.storage.path_resolver import resolve_run_model_dir

    train_result = train_book_model(
        token_sequences,
        run_id,
        pretrained_vectors=pretrained_vectors,
    )
    ling_repo.insert_word2vec_model_run(
        run_id,
        {
            "run_id": run_id,
            "embedding_dimension": train_result.embedding_dimension,
            "vocabulary_size": train_result.vocabulary_size,
            "parameters": train_result.parameters,
            "source_uri": pretrained_source,
            "license_name": None,
            "training_document_count": train_result.training_document_count,
            "training_token_count": train_result.training_token_count,
            "artifact_key": train_result.artifact_key,
            "artifact_scope": "run_owned",
        },
    )
    run_model_dir = resolve_run_model_dir(run_id, "word2vec")
    vectors = Word2Vec.load(str(run_model_dir / "word2vec.model"))
    pos_rows: list[dict] = []
    for paragraph_id, tokens in paragraph_tokens.items():
        for entry in build_pos_embeddings(
            tokens,
            vectors,
            paragraph_id=paragraph_id,
        ):
            pos_rows.append(
                {
                    "run_id": run_id,
                    "paragraph_id": entry.paragraph_id,
                    "pos_group": entry.pos_group,
                    "embedding_vector": entry.embedding_vector,
                    "source_token_count": entry.source_token_count,
                    "in_vocabulary_token_count": entry.in_vocabulary_token_count,
                }
            )
    ling_repo.insert_pos_embeddings(run_id, pos_rows)
    return train_result, len(pos_rows)
