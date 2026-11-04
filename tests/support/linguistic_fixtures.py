"""语言生成结果与已保存统计的测试夹具"""

from collections import Counter
from types import SimpleNamespace

from sqlalchemy import select

from src.linguistic.ltp_client import POS_GROUP_MAP, _count_dependency_statistics
from src.linguistic.schema import LtpDependencyArc, LtpSdpArc, LtpToken, ParagraphLinguisticResult
from src.linguistic.statistics import build_paragraph_statistics
from src.storage.models import LinguisticSpan, Paragraph, ParagraphFeature, ParagraphMetric
from src.storage.records.linguistic import LINGUISTIC_GROUP_PREFIXES, SENTENCE_CODE_TO_KEY


def generated_linguistic_row(text: str, row: dict) -> dict:
    """从原文和合成 LTP 结构调用正式逐段统计入口"""
    tokens = [
        LtpToken(
            token_index=token["token_index"], text=text[token["local_start_char"]:token["local_end_char"]],
            local_start_char=token["local_start_char"], local_end_char=token["local_end_char"],
            pos_tag=token["pos_tag"], pos_group=POS_GROUP_MAP.get(token["pos_tag"], "other"),
        ) for token in row.get("tokens", [])
    ]
    arcs = [LtpDependencyArc(**arc) for arc in row.get("dependency_arcs", [])]
    nodes, roots, depth_sum, depth_max, relations = _count_dependency_statistics(arcs)
    result = ParagraphLinguisticResult(
        ltp_token_count=len(tokens), tokens=tokens,
        word_length_counts=dict(Counter(
            "5_plus" if len(token.text) >= 5 else str(len(token.text)) for token in tokens
        )),
        pos_counts=dict(Counter(token.pos_group for token in tokens)),
        sentence_count=row.get("sentence_count", 0), sentence_pattern_counts=row.get("sentence_pattern_counts", {}),
        dependency_arcs=arcs, dependency_node_count=nodes, dependency_root_count=roots,
        dependency_depth_sum=depth_sum, dependency_depth_max=depth_max, dependency_relation_counts=relations,
        sdp_arcs=[LtpSdpArc(**arc) for arc in row.get("sdp_arcs", [])],
    )
    return {**row, **build_paragraph_statistics(text, result)}


def saved_linguistic_rows(session, run_id: str) -> list[SimpleNamespace]:
    """读取已保存统计和情绪观测，不从依存弧重新推导"""
    rows = {
        row.paragraph_id: SimpleNamespace(
            paragraph_id=row.paragraph_id, boundary_pos_score_sum=row.boundary_pos_score_sum,
            boundary_neg_score_sum=row.boundary_neg_score_sum, emotion_events=[],
            **{field: {} for field in (*LINGUISTIC_GROUP_PREFIXES, "sentence_pattern_counts")},
        ) for row in session.execute(select(ParagraphMetric).where(
            ParagraphMetric.run_id == run_id, ParagraphMetric.linguistic_completed_at.is_not(None)
        )).scalars()
    }
    for feature in session.execute(select(ParagraphFeature).where(ParagraphFeature.run_id == run_id)).scalars():
        if feature.paragraph_id not in rows:
            continue
        row = rows[feature.paragraph_id]
        code = feature.feature_code
        if code in SENTENCE_CODE_TO_KEY:
            row.sentence_pattern_counts[SENTENCE_CODE_TO_KEY[code]] = feature.count_value
        elif any(code.startswith(prefix) for prefix in LINGUISTIC_GROUP_PREFIXES.values()):
            for field, prefix in LINGUISTIC_GROUP_PREFIXES.items():
                if code.startswith(prefix):
                    getattr(row, field)[code.removeprefix(prefix)] = feature.count_value
        else:
            setattr(row, code, feature.count_value if feature.count_value is not None else feature.scalar_value)
    for observation in session.execute(
        select(LinguisticSpan, Paragraph.text.label("paragraph_text")).join(Paragraph, (
            (Paragraph.run_id == LinguisticSpan.run_id) & (Paragraph.paragraph_id == LinguisticSpan.paragraph_id)
        )).where(LinguisticSpan.run_id == run_id, LinguisticSpan.emotion_polarity.is_not(None))
    ):
        span = observation.LinguisticSpan
        text = observation.paragraph_text
        rows[span.paragraph_id].emotion_events.append({
            "predicate": text[span.start_char:span.end_char], "predicate_token_index": span.token_index + 1,
            "polarity": span.emotion_polarity, "negated": span.emotion_negated,
            "holder_token_index": span.emotion_holder_token_index,
        })
    for row in rows.values():
        row.emotion_event_count = len(row.emotion_events)
    return list(rows.values())
