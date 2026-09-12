"""
章节标注 Agent 语义写入提示词
"""

from __future__ import annotations

import json

from .schema import ChunkParagraphInfo, DialogueCandidate

SYSTEM_PROMPT = "你是小说章节语义标注 Agent，请依据当前提供的小说正文完成语义标注。"

# 2026-09-11 章内并行（§6）：读者单行职责声明（与标注 SYSTEM_PROMPT 同款单行裁决）
READER_SYSTEM_PROMPT = (
    "你是小说章节语义标注的读者子代理，请细读分配到的正文片段，"
    "把有正文证据支撑的观察经一次 send_message 一次性上报。"
)


def _candidate_views(candidates: list[DialogueCandidate]) -> list[dict]:
    """2026-09-11 用于渲染对话候选表（读者块切片与写者全章表共用）"""
    return [
        {
            "candidate_index": index,
            "id": candidate.candidate_key,
            "text": candidate.content,
            "parse_status": candidate.parse_status,
        }
        for index, candidate in enumerate(candidates, start=1)
    ]


def build_system_prompt() -> str:
    """2026-08-30 用于构建只声明章节标注职责的单行系统提示词

    2026-09-04 曾追加"案例编号"检索管道规则，2026-09-05 裁决删除：
    该规则把非案例疑点（如对话说话人）误导进 search_pool 空转至上限
    （第3章 15 轮 40 次检索 0 写入）。编号授权=编号表注入展示即授权
    + 工具层 case_number 校验（未授权编号直接报错自纠）。
    """
    return SYSTEM_PROMPT


def build_case_pool_notice() -> str:
    """2026-09-11 用于声明案例池检索制：案例不进正文注入，只经 search_pool 展示

    历史背景：09-04 曾要求"疑点必须先用 search_pool 检索再解决"，模型把非
    案例问题也塞进检索，第 3 章 15 轮 40 次检索 0 写入死锁；09-05 该流程
    规则被删、改回全量注入编号表。本次改为不注入 + 检索制：执行动作与否
    由模型自行判断，此处只说明通道与编号规则，不规定处理顺序。
    """
    return (
        "<ActiveCases>\n"
        "案例池未随正文注入。用 search_pool 检索活动案例（关键词匹配，或用 "
        'case_type 枚举全部/某类型），检索即授权其编号；案例的解决/关闭一律'
        "使用 search_pool 回执中的 case_number。\n"
        "</ActiveCases>"
    )


def build_chunk_message(
    *,
    chunk_index: int,
    chunk_total: int,
    chunk_text: str,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-08-07 用于向 Agent 提供当前唯一可写 chunk 和有序候选

    2026-08-22事件不再携带段落锚点，移除 ¶N 段落标记注入。
    2026-09-07 句级监督：新增自选句标签区块（提交渠道=write_metrics 的
    sentence_labels 可选参数，不新增工具；选句标准见 write_metrics docstring）。
    2026-09-10 候选字段 index 改名 candidate_index，消除与案例编号空间的混同
    （run a83fae3d 思考实测映射推理 1725 次、显式困惑 39 次）。
    2026-09-11 案例改检索制：ActiveCases 区块从编号表降级为通道说明，案例
    编号只由 search_pool 回执产生。
    """
    candidate_views = [
        {
            "candidate_index": index,
            "id": candidate.candidate_key,
            "text": candidate.content,
            "parse_status": candidate.parse_status,
        }
        for index, candidate in enumerate(candidates, start=1)
    ]
    sections = [
        f'<CurrentChunk order="{chunk_index}/{chunk_total}">\n'
        f"{chunk_text}\n"
        "</CurrentChunk>",
        build_case_pool_notice(),
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<SentenceLabels>\n"
        "请从上方正文中自选 2-3 个完整句子（原样摘录，不改写），随 write_metrics 的 "
        "sentence_labels 参数为每句提交整句情绪标签（emotion 为 -2..2 整数分值，"
        "同 write_metrics.emotional_valence）。选择权在模型："
        "优先选情绪表达有代表性、或语气/标点有区分度的句子；也允许选 0 分句。\n"
        "</SentenceLabels>",
    ]
    return "\n\n".join(sections)


def build_reader_block_message(
    *,
    block_number: int,
    block_total: int,
    paragraph_info: ChunkParagraphInfo,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-09-11 章内并行（§6）用于构建读者唯一一次的正文注入

    正文以段落清单形态注入（paragraph id 即 send_message 证据锚点），候选为本块
    切片；上报合同（一次性/逐字引文/名字/不裁决/句标签不限条数）由 send_message
    工具 docstring 与服务端校验承载，此处只陈述通道与编号边界。
    """
    paragraph_views = "\n".join(
        f'<paragraph id="{paragraph_id}">{text}</paragraph>'
        for paragraph_id, text in zip(paragraph_info.paragraph_ids, paragraph_info.texts, strict=True)
    )
    sections = [
        f'<CurrentSubBlock block="{block_number}/{block_total}">\n'
        f"{paragraph_views}\n"
        "</CurrentSubBlock>",
        build_case_pool_notice(),
        "<DialogueCandidates>\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<ReportingContract>\n"
        "读完本块后，把全部观察经一次 send_message 一次性上报：整个会话只允许调用一次，"
        "载荷按观察类分组（entities/relations/sentence_labels/dialogues/cases/"
        "event_trees/notes 为数组，metric 为单对象），没有观察的组省略；\n"
        "每条观察必须自带 evidence=[{paragraph_id, quote}]（本块段落内的逐字摘录，"
        "NFC 归一后必须唯一命中），notes 可省略；\n"
        "一律用名字，绝不把案例编号或实体编号写进上报（编号是会话局部句柄，"
        "写者拿不到也不认）；\n"
        "案例相关只陈述文本侧事实（signal: 新疑点/埋设/加强/坐实/回收/证伪），"
        "可用 search_pool 匹配并原样带上案例描述（matched_case），但不裁决；\n"
        "句标签不限条数：把本块内值得打标的句子全部上报，最终提交哪几句由写者决定；\n"
        "格式或枚举不符也照常送达（回执 warnings 会指出问题），不需要重发；\n"
        "块边界处疑似与相邻块共构的线索用 notes 上报，不做跨块推断。\n"
        "</ReportingContract>",
    ]
    return "\n\n".join(sections)


def build_writer_chapter_message(
    *,
    reader_reports_view: str,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-09-11 章内并行（§7）用于构建写者首条请求（不注入全章正文）

    一次性报告按块序渲染；正文取证走既有 search_text。写入取值域=报告并集
    ∪已授权历史对象，由服务端准入校验兜底。
    """
    sections = [
        "<ReaderReports>\n"
        "以下是各子块读者的一次性上报（已按块序排列）。你的写入取值域=这些报告的并集"
        "∪已授权历史对象；跨块同一条线索（如前块埋设+后块坐实）合并为一次裁决，"
        "理由用两段引文拼装；对某条观察需要补充正文证据时用 search_text 取证。\n"
        f"{reader_reports_view}\n"
        "</ReaderReports>",
        build_case_pool_notice(),
        "<DialogueCandidates>\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<SentenceLabels>\n"
        "请从读者上报的 sentence_labels 观察中自选 2-3 个句子，随 write_metrics 的 "
        "sentence_labels 参数提交整句情绪标签（emotion 为 -2..2 整数分值）。"
        "选择由你裁量：优先选情绪表达有代表性、或语气/标点有区分度的句子，"
        "兼顾跨块分布；句子必须原样摘录不改写。\n"
        "</SentenceLabels>",
    ]
    return "\n\n".join(sections)


__all__ = [
    "build_case_pool_notice",
    "build_chunk_message",
    "build_reader_block_message",
    "build_system_prompt",
    "build_writer_chapter_message",
    "READER_SYSTEM_PROMPT",
]
