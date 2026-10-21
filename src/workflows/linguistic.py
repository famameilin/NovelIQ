"""语言结构基础数据阶段

执行顺序与落库契约（逐段事实落 paragraph_spans / paragraph_arcs /
paragraph_features / paragraph_metrics）：
1. LTP 词法/句法/实体/语义：analyze_paragraph_batch（cws/pos/ner/dep/sdp）→
   paragraph_spans 词元行（token_index/raw_pos）+ paragraph_arcs
   （dep:*/sdp:*，source_ordinal 保留源顺序）+ paragraph_features 的五类
   句式计数行；完成事实与共享句数写 paragraph_metrics
   （linguistic_completed_at/sentence_count）；NER 候选写 paragraph_spans
   的 raw_entity_type 行（非图谱事实；词面与归一类型读取投影）
2. 固定短语：唯一 fixed_phrases 词表匹配 → paragraph_spans 的
   phrase_match_kind 行（lexicon/four_char_candidate）+ 完成事实
   （phrase_completed_at）；词表来源与计量合同登记在 runs
3. 情绪事件与 mNEG 修正（ltp.enabled 时生效）：
   情绪词典只做谓词极性候选标记，持有者/对象/否定/程度取 sdp 的 AGT/DATV/
   mNEG/mDEPD；mNEG 接管词典否定翻转后回写 paragraph_metrics 情绪计数并
   整卷重算段落曲线（词典窗口规则基线与 mNEG 对照计数由读取投影按同一
   正式词元/弧重算，不落第二份可违反守恒的副本）
4. Word2Vec（可开关）：预训练词向量初始化 + 本书语料微调（warm-start）→
   runs 的 w2v_* 实际构建列 + paragraph_features 的 pos_vector 行

同 run 重跑先清后插（仓储层），不允许新旧结果混合；LTP 关闭时词法
阶段跳过（各语言关系为空），Word2Vec 关闭时不写 w2v_* 列。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from gensim.models import KeyedVectors, Word2Vec
from loguru import logger

from src.config import settings
from src.event_bus.notifications import StreamEvent
from src.lexicons.constants import LEXICON_FILES
from src.linguistic import TrainResult
from src.linguistic.queries import fetch_paragraph_labels
from src.storage import Storage
from src.storage.contracts.stores import LinguisticStore, ParagraphStore
from src.utils.cancellation import finish_thread_step


async def run_linguistic(
    run_id: str,
    session: Storage,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    *,
    batch_size: int = 128,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int]:
    """执行语言结构阶段并返回段落数与词法特征段落数

    batch_size 控制每批处理的段落数并限制阶段内存峰值
    取消在每个段落批边界生效：LTP 批推理是线程内重活，不能安全硬中断
    """
    from src.utils.cancellation import check_cancelled

    start_time = time.time()
    paragraph_repo = session.paragraphs
    ling_repo = session.linguistic

    ltp_settings = settings.linguistic.ltp
    w2v_settings = settings.linguistic.word2vec

    # 分批处理控制内存峰值：段落文本、LTP 输出、特征/实体/短语行都只保留当前批，
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

        # B 批：词典情绪计数对照基线（命中集与 preprocess 同源，
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
        saved_paragraphs = 0
        while True:
            check_cancelled(is_cancelled)
            batch = paragraph_repo.fetch_paragraph_rows_batch(run_id, after_id=last_id, limit=batch_size)
            if not batch:
                break
            last_id = batch[-1].paragraph_id

            logger.info(f"LTP 分析 {len(batch)} 个段落（游标 after={last_id}）...")
            # LTP 批推理移出事件循环（run 08f9ba42 实证 30s API 尖峰）：
            # 128 段/批的 cws/pos/ner/dep/sdp 是重 CPU 同步调用，直接在事件循环上
            # 跑会冻结整个 API（状态端点/SSE 全部无响应）。批间 await 串行化模型
            # 访问，无并发推理风险。
            results = await finish_thread_step(asyncio.to_thread(analyze_paragraph_batch, [row.text for row in batch]))

            feature_rows: list[dict] = []
            entity_rows: list[dict] = []
            for row, result in zip(batch, results, strict=True):
                data = result.to_dict()
                # B 批：词典极性候选标记 × sdp 结构 → 情绪事件 + mNEG 修正计数
                events = extract_emotion_events(result, POSITIVE_TERMS, NEGATIVE_TERMS)
                mneg_pos, mneg_neg = mneg_corrected_counts(
                    row.text,
                    result.tokens,
                    result.sdp_arcs,
                    POSITIVE_TERMS,
                    NEGATIVE_TERMS,
                )
                lexicon_pos, lexicon_neg = lexicon_counts.get(int(row.paragraph_id), (0.0, 0.0))
                # 派生量（事件/计数）不落库，由读取投影按同一正式词元/弧重算；
                # 这里只用于 mNEG 回写清单
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
                    # 3NF：只写候选区间与原始类型；词面按原文切片、
                    # 归一类型按固定映射、来源与空 confidence 按语言合同投影
                    entity_rows.append(
                        {
                            "run_id": run_id,
                            "paragraph_id": row.paragraph_id,
                            "raw_entity_type": entity.raw_entity_type,
                            "local_start_char": entity.local_start_char,
                            "local_end_char": entity.local_end_char,
                        }
                    )
                # Word2Vec 按书微调需要全书词元序列，逐批累积
                tokens = [t for t in data["tokens"] if t.get("text")]
                paragraph_tokens[row.paragraph_id] = tokens
                token_sequences.append([t["text"] for t in tokens])

            total_feature_paragraphs += len(feature_rows)
            logger.info(f"LTP 事实落库：段落={len(feature_rows)} 实体候选={len(entity_rows)}")

            # 固定短语匹配：唯一 fixed_phrases 词表的词表命中 + 四字候选
            # （依赖 LTP 词元行；词表来源/计量合同登记在运行行）
            fixed_phrase_key = LEXICON_FILES["fixed_phrases"]
            phrase_rows: list[dict] = []
            for row in batch:
                hits = match_fixed_phrases(
                    row.text,
                    terms,
                    lexicon_key=fixed_phrase_key,
                    metric_enabled=False,
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

            # 短语完成事实覆盖本批全部段落（含零命中：完成≠有命中）
            ling_repo.save_batch(
                run_id,
                feature_rows,
                entity_rows,
                phrase_rows,
                [int(row.paragraph_id) for row in batch],
                clear_first=first_batch,
            )
            logger.info(f"固定短语落库：{len(phrase_rows)} 行（词表 {fixed_phrase_key}）")
            first_batch = False
            saved_paragraphs += len(batch)
            if emitter:
                await emitter(
                    StreamEvent(
                        action="progress",
                        sub_stage="语言特征保存",
                        current=saved_paragraphs,
                        total=total_paragraphs,
                        unit="段落",
                        status="running",
                    )
                )

        logger.info(f"LTP 全库完成：段落={total_paragraphs} 词法特征段落={total_feature_paragraphs}")

        # B 批：mNEG 接管词典否定翻转——回写 paragraph_metrics 情绪
        # 计数并按新分子整卷重算段落曲线（聚合/曲线/零信号占比随之切换口径）
        corrected = _apply_mneg_correction(session, run_id, paragraph_repo, mneg_corrections)
        if corrected:
            logger.info(f"mNEG 情绪修正回写：{corrected} 段（sdp 否定辖域替代窗口规则），段落曲线已重算")
    else:
        logger.info("linguistic.ltp.enabled=false，跳过词法/句法/实体与固定短语")

    # ------------------------------------------------------------------
    # 段落级监督（按书边界）：全书自选段标签现算该书线性边界，
    # 逐段打分回写 paragraph_metrics 的两列边界观测。不依赖 LTP——向量源是
    # paragraph_features 的 semantic_vector 行（preprocess 落库），故挂在
    # ltp 闸门之外；标签不足或类别单一时无边界（两列 NULL），不伪造。
    check_cancelled(is_cancelled)
    boundary_rows = _apply_paragraph_boundary_scores(session, run_id, paragraph_repo, ling_repo)
    if boundary_rows:
        logger.info(f"段落级边界打分回写：{boundary_rows} 段获得分值（样本来自标注 agent 自选段标签）")

    # ------------------------------------------------------------------
    # Word2Vec：预训练初始化 + 按书微调（依赖 LTP 词元）
    # ------------------------------------------------------------------
    if w2v_settings.enabled and ltp_settings.enabled:
        from src.config.paths import resolve_project_root
        from src.linguistic import load_shared_pretrained_vectors, resolve_shared_pretrained_path

        check_cancelled(is_cancelled)
        if not w2v_settings.model_dir:
            raise ValueError("linguistic.word2vec.enabled=true 需要配置 model_dir（预训练共享模型目录）")
        model_dir = Path(w2v_settings.model_dir)
        if not model_dir.is_absolute():
            model_dir = resolve_project_root() / model_dir
        pretrained_path = resolve_shared_pretrained_path(model_dir)
        pretrained_vectors = load_shared_pretrained_vectors(model_dir)

        # Word2Vec 训练（gensim CPU 重活，分钟级）同样移出事件循环；
        # 编排器 session 只被本协程使用，跨线程顺序访问安全（事件循环 await 期间不触碰）
        if emitter:
            await emitter(
                StreamEvent(action="progress", sub_stage="词向量训练", status="running", message="训练进度未记录")
            )
        train_result, pos_rows_count = await finish_thread_step(
            asyncio.to_thread(
                _train_and_build,
                run_id,
                ling_repo,
                token_sequences,
                paragraph_tokens,
                pretrained_vectors=pretrained_vectors,
                pretrained_source=str(pretrained_path),
            )
        )
        if emitter:
            await emitter(StreamEvent(action="progress", sub_stage="词向量训练", status="completed"))
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


def _apply_paragraph_boundary_scores(
    session: Storage,
    run_id: str,
    paragraph_repo: ParagraphStore,
    ling_repo: LinguisticStore,
) -> int:
    """段落级监督（按书边界）：全书自选段标签 → 岭回归边界 → 逐段打分

    链路：agent_assessments 逐段情绪标签读全书标签 → paragraph_features 的
    semantic_vector 行取全书段落向量（preprocess 落库）→ fit_emotion_boundary
    现算该书线性边界 → 全书逐段打分回写 paragraph_metrics 的
    boundary_pos_score_sum / boundary_neg_score_sum；跨书曲线口径不同不可比。

    边界无效（标签 <2 或全同分值）、段落向量缺失时返回 0，两列维持 NULL，不伪造。
    """
    import numpy as np

    from src.linguistic import fit_emotion_boundary

    labels = fetch_paragraph_labels(session, run_id)
    if len(labels) < 2:
        logger.info("段落边界跳过：自选段标签不足 2 条（无法拟合边界），两列保持 NULL")
        return 0

    vectors_by_id: dict[int, np.ndarray] = {
        paragraph_id: np.asarray(vector, dtype=np.float64)
        for paragraph_id, vector in ling_repo.fetch_semantic_vectors(run_id).items()
    }
    if not vectors_by_id:
        logger.info("段落边界跳过：本 run 无段落语义向量（paragraph_features 未就绪），两列保持 NULL")
        return 0
    fit_labels = [label for label in labels if label["paragraph_id"] in vectors_by_id]
    if len(fit_labels) < 2:
        logger.info("段落边界跳过：自选段标签能对上段落向量的不足 2 条，两列保持 NULL")
        return 0
    boundary = fit_emotion_boundary(
        np.stack([vectors_by_id[label["paragraph_id"]] for label in fit_labels]),
        [int(label["emotion"]) for label in fit_labels],
    )
    if boundary is None:
        logger.info("段落边界跳过：标签分值无变化（全同情绪），无边界可学，两列保持 NULL")
        return 0

    expected_dim = len(boundary.weights)
    updates: list[tuple[int, float, float]] = []
    for row in paragraph_repo.fetch_paragraph_rows(run_id):
        paragraph_id = int(row.paragraph_id)
        vector = vectors_by_id.get(paragraph_id)
        if vector is None or vector.shape[0] != expected_dim:
            # 与旧口径一致：无向量段落按 0 贡献（两侧皆零），不写 NULL 之外的伪造值
            pos_sum = neg_sum = 0.0
        else:
            score = boundary.score(vector)
            pos_sum = float(score) if score > 0 else 0.0
            neg_sum = float(-score) if score < 0 else 0.0
        updates.append((paragraph_id, pos_sum, neg_sum))

    return ling_repo.insert_boundary_scores(run_id, updates)


def _apply_mneg_correction(
    session: Storage,
    run_id: str,
    paragraph_repo: ParagraphStore,
    corrections: list[dict[str, float | int]],
) -> int:
    """mNEG 情绪修正回写（sdp 否定辖域接管窗口规则）

    命中集与 preprocess 完全一致（同一 get_emotion_spans 短语匹配），唯一差异
    是翻转判定由 sdp mNEG 决定；回写 paragraph_metrics 两列后按新分子整卷重算
    段落曲线（compute_paragraph_curves 与 preprocess 同一函数，LOWESS 参数同源）。
    """
    if not corrections:
        return 0

    from src.workflows.paragraph_curves import compute_paragraph_curves

    # Core 表对象（绕开 ORM 按主键批量更新拦截）；synchronize_session=False 同理
    params = [
        {
            "b_run_id": run_id,
            "b_paragraph_id": row["paragraph_id"],
            "b_pos": float(row["mneg_pos"]),
            "b_neg": float(row["mneg_neg"]),
        }
        for row in corrections
    ]
    session.linguistic.apply_mneg(params)

    paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
    metric_rows = paragraph_repo.fetch_paragraph_metrics(run_id)
    total_chars = sum(int(row.char_count or 0) for row in paragraph_rows)
    curve_rows = compute_paragraph_curves(paragraph_rows, metric_rows, total_chars)
    paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
    return len(params)


def _train_and_build(
    run_id: str,
    ling_repo: LinguisticStore,
    token_sequences: list[list[str]],
    paragraph_tokens: dict[int, list[dict[str, str]]],
    *,
    pretrained_vectors: KeyedVectors,
    pretrained_source: str,
) -> tuple[TrainResult, int]:
    """完成预训练微调落库并构建词性聚合向量"""
    from src.config.paths import resolve_run_model_dir
    from src.linguistic import build_pos_embeddings, train_book_model

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
            "window_size": train_result.window_size,
            "min_count": train_result.min_count,
            "epochs": train_result.epochs,
            "pretrained_vocabulary_size": train_result.pretrained_vocabulary_size,
            "source_uri": pretrained_source,
            "license_name": None,
            "training_document_count": train_result.training_document_count,
            "training_token_count": train_result.training_token_count,
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
            # source_token_count 不再是存储列：读取侧由正式词元 + 版本分组投影
            pos_rows.append(
                {
                    "run_id": run_id,
                    "paragraph_id": entry.paragraph_id,
                    "pos_group": entry.pos_group,
                    "embedding_vector": entry.embedding_vector,
                    "in_vocabulary_token_count": entry.in_vocabulary_token_count,
                }
            )
    ling_repo.insert_pos_embeddings(run_id, pos_rows)
    return train_result, len(pos_rows)
