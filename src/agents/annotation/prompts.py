"""
章节标注 Agent 语义写入提示词
"""

from __future__ import annotations

import json

from .schema import ChunkParagraphInfo, DialogueCandidate

# 2026-09-14 处理规则上提系统层（原在【进度账本】注入块
# 逐回合下发；规则是静态行为合同，属系统提示词，注入块只留动态状态）。实测依据
# run a8c29ec8：规则上线后 ch1-3 墙钟 -44%，回合构成变为"判完即写、一批收章"。
# 原"只能一行职责声明"的单行裁决就此废止（读者面 READER_SYSTEM_PROMPT 仍保持单行）。
# 同日删除"首写前必须先 search_graph"硬闸（tools.write_entity），
# 提示词里对应的从属条款一并删净——写入不再被检索回执推后一个回合。
# 2026-09-16 删去"你的思考对后续回合不可见，跨回合预演计划等于下回合从零重推"一句。
# 2026-09-17 回合压缩纪律回填：main 时代系统提示词要求"全部领域于同一回复批量提交，
# 通常 1-2 个回复完成全部写入"，实测 main run fda9e7a7（同书同日）每章只花 1 个写入
# 回合（write_metrics + write_entities + write_relations + write_dialogues + create_event
# 同轮发出）；本分支 09-14 重写的短提示词与 09-15 的程序面规则都丢了这条纪律，
# 实测 run 73d51472 每章 3-4 个写入回合、逐领域一个回合，同书墙钟 2h→8h 主要来自这里。
SYSTEM_PROMPT = (
    "你是小说章节语义标注 Agent，请依据当前提供的小说正文完成语义标注。\n"
    "处理规则：系统每回合注入的【进度账本】是本章已写入状态的权威当前值，已判定条目按本表值执行、"
    "不再回正文重扫；未写入的内容在本回合判完即写、随判随落盘；"
    "引用实体前先确认其已登记（账本实体列可查）。"
    "轮次有硬上限、耗尽即整章失败：检索类调用尽量合并，写入类调用在依赖就绪后于同一回合批量提交"
    "——实体、关系、事件、对话、指标、收尾全部领域通常一个回合写完，不必逐领域等回执。"
)

# 2026-09-11 章内并行（§6）：读者单行职责声明（单行裁决仍适用于读者面）
READER_SYSTEM_PROMPT = (
    "你是小说章节语义标注的读者子代理，请细读分配到的正文片段，"
    "把有正文证据支撑的观察经一次 send_message 一次性上报。"
)

# 2026-09-16 块代理面（CodeAct）单行职责声明：能力合同在 execute_code 的
# description 里（构造器目录 + 语法边界），系统提示词只声明职责
BLOCK_SYSTEM_PROMPT = (
    "你是小说章节语义标注的块代理，请细读分配到的正文片段，"
    "用 execute_code 提交程序，把有正文证据支撑的局部标注构造成块内对象。"
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


# 2026-09-15 程序面（CodeAct）处理规则：只在绑定面收成唯一 execute_code 时下发
PROGRAM_RULES = (
    "程序面规则：每轮只能提交一个 Python 程序（execute_code）来调用工具，工具调用写成"
    "程序里的函数调用语句；变量在本章后续程序里保留（实体 el、事件键、工具返回值都可以"
    "用变量承接，不必靠上下文回忆）。\n"
    "一次程序尽量写完本轮该写的全部内容：同一个程序里连续调用多个工具、写多条记录都可以，"
    "本回合判定的内容本回合写完；只有后一步必须看到前一步回执时才留到下一轮。\n"
    "工具的业务失败只回滚该条并继续执行后面的调用；语法或运行错误会停止程序，已成功的"
    "调用保留——下一轮只补失败的那部分，不要重放整段程序。\n"
    "回执只回报成功条数、新增句柄引用与失败清单；成功记录的明细用检索工具回查。"
)


def build_system_prompt(program_mode: bool = False) -> str:
    """2026-08-30 用于构建只声明章节标注职责的单行系统提示词

    2026-09-04 曾追加"案例编号"检索管道规则，2026-09-05 裁决删除：
    该规则把非案例疑点（如对话说话人）误导进 search_pool 空转至上限
    （第3章 15 轮 40 次检索 0 写入）。编号授权=编号表注入展示即授权
    + 工具层 case_number 校验（未授权编号直接报错自纠）。
    2026-09-15 program_mode=True（单块章程序面）时追加程序面处理规则段——
    按调用方传参决定，不由函数内部读全局开关（两段式写者不传、行为不变）。
    """
    if program_mode:
        return f"{SYSTEM_PROMPT}\n{PROGRAM_RULES}"
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


def _render_paragraph_numbered_text(chunk_text: str, paragraph_info: ChunkParagraphInfo | None) -> str:
    """2026-09-14 段落级监督：按 ChunkParagraphInfo 在每段前注入 ¶<全局段落号> 标记

    号码=全局 paragraph_id（与读者报告 evidence.paragraph_id 同一空间）。
    标记只用于展示，段落文本本体逐字保留；无 paragraph_info 时原样返回。
    """
    if paragraph_info is None:
        return chunk_text
    parts: list[str] = []
    for paragraph_id, text in zip(paragraph_info.paragraph_ids, paragraph_info.texts, strict=True):
        parts.append(f"¶{paragraph_id}\n{text}")
    rendered = "".join(parts)
    return rendered if parts else chunk_text


def build_chunk_message(
    *,
    chunk_index: int,
    chunk_total: int,
    chunk_text: str,
    candidates: list[DialogueCandidate],
    paragraph_info: ChunkParagraphInfo | None = None,
) -> str:
    """2026-08-07 用于向 Agent 提供当前唯一可写 chunk 和有序候选

    2026-08-22事件不再携带段落锚点，移除 ¶N 段落标记注入。
    2026-09-14 段落级监督：¶ 标记以全局段落号回归，write_metrics.labels
    按 ¶ 号提交整段情绪标签（选段标准见该工具 docstring）。
    2026-09-10 候选字段 index 改名 candidate_index，消除与案例编号空间的混同
    （run a83fae3d 思考实测映射推理 1725 次、显式困惑 39 次）。
    2026-09-11 案例改检索制：ActiveCases 区块从编号表降级为通道说明，案例
    编号只由 search_pool 回执产生。
    """
    candidate_views = _candidate_views(candidates)
    label_section = (
        "<ParagraphLabels>\n"
        "请从上方正文中自选 2-3 个段落，随 write_metrics 的 labels 参数提交整段情绪标签"
        "（每项 {paragraph_id, emotion}，paragraph_id 取段首 ¶ 后的数字，emotion 为 -2..2"
        " 整数分值，同 emotional_valence）。"
        "选择权在模型：优先选情绪表达有代表性、或语气/标点有区分度的段落；也允许选 0 分段。\n"
        "</ParagraphLabels>"
        if paragraph_info is not None
        else ""
    )
    sections = [
        f'<CurrentChunk order="{chunk_index}/{chunk_total}">\n'
        f"{_render_paragraph_numbered_text(chunk_text, paragraph_info)}\n"
        "</CurrentChunk>",
        build_case_pool_notice(),
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        label_section,
    ]
    return "\n\n".join(section for section in sections if section)


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
        "载荷按观察类分组（entities/relations/paragraph_labels/dialogues/cases/"
        "event_trees/notes 为数组，metric 为单对象），没有观察的组省略；\n"
        "每条观察必须自带 evidence=[{paragraph_id, quote}]（本块段落内的逐字摘录，"
        "NFC 归一后必须唯一命中），notes 可省略；\n"
        "一律用名字，绝不把案例编号或实体编号写进上报（编号是会话局部句柄，"
        "写者拿不到也不认）；\n"
        "dialogues 的 candidate_index 用本块 <DialogueCandidates> 表里展示的编号"
        "（块内 1 基，不是全章序号）；\n"
        "案例相关只陈述文本侧事实（signal: 新疑点/埋设/加强/坐实/回收/证伪），"
        "可用 search_pool 匹配并原样带上案例描述（matched_case），但不裁决；\n"
        "段落标签不限条数：把本块内值得打标的段落全部上报（paragraph_id 取正文 ¶ 标记），"
        "最终提交哪几段由写者决定；\n"
        "格式或枚举不符也照常送达（回执 warnings 会指出问题），不需要重发；\n"
        "块边界处疑似与相邻块共构的线索用 notes 上报，不做跨块推断。\n"
        "</ReportingContract>",
    ]
    return "\n\n".join(sections)


def build_block_program_message(
    *,
    block_number: int,
    block_total: int,
    paragraph_info: ChunkParagraphInfo,
    boundary_before: tuple[int, str] | None,
    boundary_after: tuple[int, str] | None,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-09-16 块代理面（CodeAct）用于构建块会话唯一一次的正文注入

    正文以段落清单注入（段落 id 即 evidence 锚点）；相邻完整段落作为只读边界
    上下文一并给出（判"事件/线索跨块延续"用，但不能作为本块证据锚点）。
    过程规则（先建提及再引用、一次程序尽量写完本轮的全部内容、失败只回滚该条）在
    execute_code 的 description 里，此处只陈述本块的取值边界与收束方式。
    """
    paragraph_views = "\n".join(
        f'<paragraph id="{paragraph_id}">{text}</paragraph>'
        for paragraph_id, text in zip(paragraph_info.paragraph_ids, paragraph_info.texts, strict=True)
    )
    boundary_parts: list[str] = []
    if boundary_before is not None:
        boundary_parts.append(f'<paragraph id="{boundary_before[0]}" readonly="true">{boundary_before[1]}</paragraph>')
    if boundary_after is not None:
        boundary_parts.append(f'<paragraph id="{boundary_after[0]}" readonly="true">{boundary_after[1]}</paragraph>')
    sections = [
        f'<CurrentBlock block="{block_number}/{block_total}">\n'
        f"{paragraph_views}\n"
        "</CurrentBlock>",
        (
            "<BoundaryContext>\n"
            "相邻块的完整段落，只供你判断事件/线索是否跨块延续，readonly：\n"
            + "\n".join(boundary_parts)
            + "\n</BoundaryContext>"
            if boundary_parts
            else ""
        ),
        build_case_pool_notice(),
        "<DialogueCandidates>\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<BlockScope>\n"
        "你只负责本块：实体提及、关系、对话与段落标签、局部事件与参与者、"
        "有正文依据的块内事件联系、章级指标的局部依据、以及你判不了的待决项。\n"
        "正文与候选都是本块切片：candidate_index 用上面这张表里的编号（块内 1 基）；"
        "evidence 的 paragraph_id 只能取 <CurrentBlock> 里的段落，<BoundaryContext> 的段落不可作证据；"
        "块内引用一律用你自己起的短键（mention 先构造，再在 relation/dialogue/participant 里引用）。\n"
        "身份绑定不是你的职责：mention 只是一个提及（没有编号、没有图节点），"
        "跨块同一个人的合并与新实体登记由章节代理裁决；你只需按本块正文如实构造。\n"
        "判不了的引用、疑似跨块延续的事件、疑似案例线索，用 pending 记下来交给章节代理。\n"
        "本块标注完毕时不再提交程序即可收束会话。\n"
        "</BlockScope>",
    ]
    return "\n\n".join(section for section in sections if section)


def build_chapter_merge_message(
    *,
    block_index_view: str,
    pending_view: str,
    candidates: list[DialogueCandidate],
    block_total: int,
) -> str:
    """2026-09-16 章内并行 CodeAct 用于构建章节代理首条请求（不注入正文）

    块代理的局部标注以句柄索引进场（明细按需 inspect）；正文只经块代理转述，
    章节代理只补全章层面决策。顺序与冲突两条硬口径写在这里：块完成顺序不构成
    任何语义顺序（原文先后不自动推成因果），参与者字段不一致必须显式裁决。
    """
    sections = [
        "<BlockAnnotations>\n"
        f"本章正文由 {block_total} 个块代理并行标注，以下是它们产出的局部对象索引"
        "（handle → 要点）。明细（证据原文、参与者三态、待决详情）用 inspect(handle) 读，"
        "不产生写入。\n"
        f"{block_index_view}\n"
        "</BlockAnnotations>",
        (
            "<PendingItems>\n"
            "各块交上来的待决项（它们自己判不了的部分）：逐条用 decide_pending(handle, decision, note=...) "
            "登记你的处置——绑定到哪个实体、并入哪棵树哪个节点、或判定不成立。\n"
            f"{pending_view}\n"
            "</PendingItems>"
            if pending_view
            else ""
        ),
        "<DialogueCandidates>\n"
        "本章完整候选表（章级编号）。块的对话判定用 merge_dialogues() 一次性编译，"
        "候选编号由系统按本表映射，你不必逐个核对。\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        "<ChapterMerge>\n"
        "你要补全的是章层面决策：\n"
        "1) 绑定：bind(mention=..., el=...) 把块内提及变成正式实体。历史人物给 n（编号），"
        "新实体不给 n。同一个人的多个提及、同名不同人的区分，由你按证据裁决后显式绑定——"
        "系统不按同名自动合并；没绑定的提及在事件与关系里无法引用。\n"
        "2) 关系与对话：import_relation(handle) 逐条编译；merge_dialogues() 一次性编译全部块内判定，"
        "说话人未绑定或跨块引号截断的条目会跳过并列进回执——补完绑定再重跑本构造器即可，可重入。\n"
        "3) 事件：tree(key, description, sources=[...]) 建树根，event(tree, key, description, type=...) "
        "往树里加子事件。块完成顺序不代表事件顺序，原文先后不自动推成因果——跨块先后与因果只能由"
        "你的调用顺序与 type 表达，块内 link 只是线索。同一参与者在多个来源里字段不一致时编译会拒绝"
        "并报出冲突两方，用 participants=[{entityid, role, narrative_role, action, emotion}] 显式裁决"
        "（不许最后写入者覆盖）。\n"
        "4) 指标：metric(summary, emotional_valence, narrative_function, ...) 提交章级摘要与指标，"
        "省略 labels 即自动并入各块段标签（按段号去重）。\n"
        "块代理撞到轮次上限会自然收束，产出可能不完整：按已给出的对象做决策，不要为缺失的部分编造。\n"
        "</ChapterMerge>",
    ]
    return "\n\n".join(section for section in sections if section)


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
        "<ParagraphLabels>\n"
        "请从读者上报的证据中自选 2-3 个段落，随 write_metrics 的 labels 参数提交整段"
        "情绪标签（每项 {paragraph_id, emotion}，paragraph_id 取报告 evidence 里的"
        " paragraph_id，emotion 为 -2..2 整数分值）。"
        "选择由你裁量：优先选情绪表达有代表性、或语气/标点有区分度的段落，"
        "兼顾跨块分布；标签的段落必须有报告证据支撑。\n"
        "</ParagraphLabels>",
    ]
    return "\n\n".join(sections)


__all__ = [
    "BLOCK_SYSTEM_PROMPT",
    "PROGRAM_RULES",
    "READER_SYSTEM_PROMPT",
    "build_block_program_message",
    "build_case_pool_notice",
    "build_chapter_merge_message",
    "build_chunk_message",
    "build_reader_block_message",
    "build_system_prompt",
    "build_writer_chapter_message",
]
