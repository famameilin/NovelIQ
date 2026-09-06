"""LTP 语言结构服务（《分析能力扩展路线图》赛道 C1/C2）

- LtpSession 懒加载 LTP 模型（必须配置本地离线模型目录，不自动联网下载），
  按句切分后批量 pipeline（cws/pos/ner/dep），对外只暴露段落级调用
- analyze_paragraph 为纯函数：输入 LTP 输出与原文，产出段落级结构数据与
  充分统计量（词长/词性/句式/依存），全部守恒可加；不依赖模型实例，
  测试可直接 mock LtpSession.pipeline
- 词性分组映射与句式规则阈值以模块常量声明
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from pathlib import Path

from loguru import logger

from src.config import settings
from src.utils.text_utils import split_sentences

from .schema import (
    LtpDependencyArc,
    LtpEntityCandidate,
    LtpSdpArc,
    LtpToken,
    ParagraphLinguisticResult,
)

#: 词性归一组映射
_POS_GROUP_MAP: dict[str, str] = {
    "n": "noun",
    "nh": "noun",
    "ni": "noun",
    "ns": "noun",
    "nz": "noun",
    "nr": "noun",
    "v": "verb",
    "vn": "verb",
    "a": "adj",
    "an": "adj",
    "d": "adv",
    "r": "pron",
    "m": "num",
    "q": "quantifier",
    "p": "prep",
    "c": "conj",
    "u": "particle",
    "wp": "punct",
    "o": "other",
    "e": "other",
    "i": "other",
    "y": "other",
    "t": "other",
    "nd": "other",
    "nl": "other",
    "ng": "other",
    "vg": "other",
}
_OTHER_POS_GROUP = "other"

#: NER 原始类型到项目归一类型
_ENTITY_TYPE_MAP: dict[str, str] = {
    "Nh": "person",
    "Ni": "org",
    "Ns": "location",
}

#: 复句连词（§B3 版本化阈值）
_COMPOUND_CONJUNCTIONS = ("但是", "虽然", "因为", "如果", "而且", "可是", "然而")
#: 句式长度阈值（字符数，§B3）
_SHORT_SENT_THRESHOLD = 10
_LONG_SENT_THRESHOLD = 30
_SENTENCE_PATTERN_KEYS = ("short", "medium", "long", "compound", "parallel_candidate")


@dataclass(frozen=True)
class LtpPipelineOutput:
    """LTP pipeline 原始输出（mock 测试面）

    2026-09-05 B 批：新增 sdp（语义依存，逐句 dict {'head','dependent','label'}）；
    旧构造（无 sdp）按空列表处理，sdp 未运行时情绪事件为空。
    """

    cws: list[list[str]]
    pos: list[list[str]]
    ner: list[list[tuple[str, str, int, int]]]
    dep: list[dict[str, list]]
    sdp: list[dict[str, list]] = dataclasses_field(default_factory=list)


class LtpSession:
    """懒加载 LTP 模型会话；同一进程只加载一次（CPU 推理）"""

    _instance: LtpSession | None = None

    def __init__(self) -> None:
        ltp_settings = settings.linguistic.ltp
        if not ltp_settings.model_dir:
            raise RuntimeError(
                "LTP 未配置离线模型目录：请设置 LTP_MODEL_DIR（.env）指向本地模型目录"
                "（模型目录仅由环境变量提供，不自动从 HuggingFace 下载）"
            )
        model_dir = Path(ltp_settings.model_dir)
        if not model_dir.is_dir():
            raise FileNotFoundError(f"配置的 LTP 离线模型目录不存在: {model_dir}")
        from ltp import LTP

        # ltp 的 LTP() 按字符串解析模型标识（"目录@url" 语法），传 Path 会 AttributeError
        model_ref = str(model_dir)
        logger.info("加载 LTP 模型: {}", model_ref)
        self._ltp = LTP(model_ref)

    @classmethod
    def get_instance(cls) -> LtpSession:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """测试用：清除懒加载单例"""
        cls._instance = None

    def pipeline(
        self,
        sentences: Sequence[str],
        tasks: Sequence[str],
    ) -> LtpPipelineOutput:
        """批量推理（句子列表），返回结构化的 LTP 原始输出"""
        out = self._ltp.pipeline(list(sentences), tasks=list(tasks), return_dict=True)
        return LtpPipelineOutput(
            cws=out["cws"],
            pos=out["pos"],
            ner=out["ner"],
            dep=out["dep"],
            sdp=out.get("sdp", []),
        )


def _normalize_pos(pos_tag: str) -> str:
    return _POS_GROUP_MAP.get(pos_tag, _OTHER_POS_GROUP)


def _normalize_entity_type(raw_type: str) -> str | None:
    return _ENTITY_TYPE_MAP.get(raw_type)


def _classify_sentence_pattern(sentence: str) -> list[str]:
    """句式模式（§B3）：长度档 + 复句连词 + 排比候选（相邻三句首字符相同由调用方判定）"""
    patterns: list[str] = []
    length = len(sentence)
    if length < _SHORT_SENT_THRESHOLD:
        patterns.append("short")
    elif length < _LONG_SENT_THRESHOLD:
        patterns.append("medium")
    else:
        patterns.append("long")
    if any(conj in sentence for conj in _COMPOUND_CONJUNCTIONS):
        patterns.append("compound")
    return patterns


def _find_cycle_members(heads: dict[int, int]) -> set[int]:
    """沿 head 链找环成员（LTP 正常为树，环仅防御；环成员深度按 1 处理）"""
    members: set[int] = set()
    for node in heads:
        if node in members:
            continue
        seen: list[int] = []
        current = node
        while True:
            head = heads.get(current)
            if head is None or head == 0:
                break
            if head in seen:
                members.update(seen[seen.index(head) :])
                members.add(current)
                break
            if head in members:
                break
            seen.append(current)
            current = head
    return members


def _count_dependency_statistics(
    arcs: list[LtpDependencyArc],
) -> tuple[int, int, int, int, dict[str, int]]:
    """依存统计：节点数、根数、深度和、最大深度、关系计数。

    深度定义：ROOT(head=0) 深度 0，节点深度 = 1 + 其 head 的深度；
    环成员深度按 1、悬空引用按 1 处理（防御，正常树形输出不会出现）。
    """
    node_count = len(arcs)
    root_count = sum(1 for arc in arcs if arc.head_index == 0)
    heads = {arc.dependent_index: arc.head_index for arc in arcs}
    cycle_members = _find_cycle_members(heads)
    depths: dict[int, int] = {}
    relation_counts: dict[str, int] = {}
    depth_sum = 0
    depth_max = 0
    for arc in arcs:
        relation_counts[arc.relation] = relation_counts.get(arc.relation, 0) + 1
        depth = 0
        current = arc.dependent_index
        path: set[int] = set()
        while True:
            head = heads.get(current)
            if head is None or head == 0:
                break
            # 环成员的缓存值是防御值，不作为真实深度复用
            if head in depths and head not in cycle_members and head not in path:
                depth += depths[head] + 1
                break
            if current in cycle_members or current in path:
                depth += 1
                break
            path.add(current)
            current = head
            depth += 1
        depths[arc.dependent_index] = depth
        depth_sum += depth
        if depth > depth_max:
            depth_max = depth
    return node_count, root_count, depth_sum, depth_max, relation_counts


def analyze_paragraph(text: str, output: LtpPipelineOutput) -> ParagraphLinguisticResult:
    """把 LTP 原始输出转换为段落级结构数据与充分统计量（纯函数）。

    NER 的 start/end 是词元索引，这里经 tokens 词元映射为段内字符区间；
    空输出（无句子）返回全零结果。
    """
    sentences = split_sentences(text)
    if not sentences or not output.cws:
        return ParagraphLinguisticResult(
            ltp_token_count=0,
            tokens=[],
            word_length_counts={},
            pos_counts={},
            sentence_count=len(sentences),
            sentence_pattern_counts={},
            dependency_arcs=[],
            dependency_node_count=0,
            dependency_root_count=0,
            dependency_depth_sum=0,
            dependency_depth_max=0,
            dependency_relation_counts={},
            entities=[],
        )

    tokens: list[LtpToken] = []
    flat_pos: list[str] = []
    arcs: list[LtpDependencyArc] = []
    sdp_arcs: list[LtpSdpArc] = []
    entities: list[LtpEntityCandidate] = []

    text_pos = 0
    token_index = 1  # LTP 词元索引 1 起（依存坐标系依赖）
    sentence_starts: list[str] = []
    pattern_keys = dict.fromkeys(_SENTENCE_PATTERN_KEYS, 0)

    for sent_idx, sentence in enumerate(sentences):
        words = output.cws[sent_idx] if sent_idx < len(output.cws) else []
        pos_tags = output.pos[sent_idx] if sent_idx < len(output.pos) else []
        patterns = _classify_sentence_pattern(sentence)
        for pattern in patterns:
            pattern_keys[pattern] = pattern_keys.get(pattern, 0) + 1
        sentence_starts.append(sentence[0] if sentence else "")
        if not words:
            continue

        sent_start = text.find(sentence, text_pos)
        if sent_start < 0:
            sent_start = text_pos
        cursor = sent_start
        sent_arcs = output.dep[sent_idx] if sent_idx < len(output.dep) else None
        # LTP 的 head 是句内坐标（ROOT=0，句内词元 1..n）；dependent_index 是段内全局
        # 坐标，head 侧必须加本句起始偏移才能与 dependent 落在同一空间（跨句错位修复）。
        sent_token_start = token_index
        for word_idx, word in enumerate(words):
            pos_tag = pos_tags[word_idx] if word_idx < len(pos_tags) else "o"
            local_start = cursor
            local_end = cursor + len(word)
            tokens.append(
                LtpToken(
                    token_index=token_index,
                    text=word,
                    local_start_char=local_start,
                    local_end_char=local_end,
                    pos_tag=pos_tag,
                    pos_group=_normalize_pos(pos_tag),
                )
            )
            flat_pos.append(pos_tag)
            cursor = local_end
            if sent_arcs is not None:
                head_list = sent_arcs["head"]
                label_list = sent_arcs["label"]
                if word_idx < len(head_list):
                    head = int(head_list[word_idx])
                    head_index = head if head == 0 else head + sent_token_start - 1
                    arcs.append(
                        LtpDependencyArc(
                            dependent_index=token_index,
                            head_index=head_index,
                            relation=str(label_list[word_idx]),
                        )
                    )
            token_index += 1
        text_pos = sent_start + len(sentence)

        # 2026-09-05 B 批：sdp 语义弧（句内坐标 → 段内全局 token_index，与 dep 同规则）
        sent_sdp = output.sdp[sent_idx] if sent_idx < len(output.sdp) else None
        if sent_sdp:
            sdp_heads = sent_sdp.get("head") or []
            sdp_dependents = sent_sdp.get("dependent") or []
            for label, head_local, dependent_local in zip(
                sent_sdp.get("label") or [], sdp_heads, sdp_dependents, strict=False
            ):
                head_global = int(head_local)
                if head_global > 0:
                    head_global += sent_token_start - 1
                sdp_arcs.append(
                    LtpSdpArc(
                        head_index=head_global,
                        dependent_index=int(dependent_local) + sent_token_start - 1,
                        label=str(label),
                    )
                )

        # NER 词元索引 → 字符区间（该句词元起点 = sent_start + 词元前缀字符和）
        for entity_type, surface, start_idx, _end_idx in output.ner[sent_idx]:
            entity_start = sent_start + sum(len(w) for w in words[:start_idx])
            entities.append(
                LtpEntityCandidate(
                    surface_text=surface,
                    raw_entity_type=entity_type,
                    normalized_entity_type=_normalize_entity_type(entity_type),
                    local_start_char=entity_start,
                    local_end_char=entity_start + len(surface),
                )
            )

    # 排比候选：相邻三句首字符相同
    for i in range(2, len(sentence_starts)):
        if sentence_starts[i - 2] and sentence_starts[i - 2] == sentence_starts[i - 1] == sentence_starts[i]:
            pattern_keys["parallel_candidate"] = pattern_keys.get("parallel_candidate", 0) + 1

    word_length_counts: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5_plus": 0}
    pos_counts: dict[str, int] = {}
    for token in tokens:
        length = len(token.text)
        bucket = "5_plus" if length >= 5 else str(length)
        word_length_counts[bucket] = word_length_counts.get(bucket, 0) + 1
        pos_counts[token.pos_group] = pos_counts.get(token.pos_group, 0) + 1

    node_count, root_count, depth_sum, depth_max, relation_counts = _count_dependency_statistics(arcs)
    return ParagraphLinguisticResult(
        ltp_token_count=len(tokens),
        tokens=tokens,
        word_length_counts=word_length_counts,
        pos_counts=pos_counts,
        sentence_count=len(sentences),
        sentence_pattern_counts=pattern_keys,
        dependency_arcs=arcs,
        dependency_node_count=node_count,
        dependency_root_count=root_count,
        dependency_depth_sum=depth_sum,
        dependency_depth_max=depth_max,
        dependency_relation_counts=relation_counts,
        entities=entities,
        sdp_arcs=sdp_arcs,
    )


def analyze_paragraph_batch(texts: Sequence[str]) -> list[ParagraphLinguisticResult]:
    """按段落批量分析：每段先切句，跨段批量推理 LTP（小模型的 CPU 批量友好）"""
    session = LtpSession.get_instance()
    results: list[ParagraphLinguisticResult] = []
    for text in texts:
        sentences = split_sentences(text)
        if not sentences:
            results.append(
                analyze_paragraph(text, LtpPipelineOutput(cws=[], pos=[], ner=[], dep=[]))
            )
            continue
        output = session.pipeline(sentences, tasks=("cws", "pos", "ner", "dep", "sdp"))
        results.append(analyze_paragraph(text, output))
    return results