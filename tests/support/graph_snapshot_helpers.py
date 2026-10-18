from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.diagnosis.schema import AgentAnalysis
from src.storage import new_id
from src.storage.models import Novel


def insert_graph_test_novel(db_session, novel_id: str) -> None:
    """为 graph snapshot contract 测试补 novels 主表记录"""

    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


def insert_graph_test_chunks(db_session, run_id: str, chunk_ids: range) -> None:
    "为 graph relation event 测试补齐 chapters 外键依赖（-2：chunks 表已合并）"
    from src.storage.repositories import ChapterRepository
    from src.text_processing.models import Chunk

    ChapterRepository(db_session).insert_chapter_texts(
        run_id,
        [
            Chunk(
                index=chunk_id,
                chapter_id=chunk_id + 1,
                start=0,
                end=len(f"chunk-{chunk_id}"),
                text=f"chunk-{chunk_id}",
            )
            for chunk_id in chunk_ids
        ],
    )
    db_session.commit()


def insert_focus_contract_agent_analysis(
    db_session,
    *,
    novel_id: str,
    run_id: str,
    focus_characters: Sequence[str],
    main_characters: Sequence[str] | None = None,
    core_cast: Sequence[str] | None = None,
    topic_labels: Mapping[str, str] | None = None,
    diagnosis: str = "测试用焦点合同 diagnosis",
) -> str:
    """
    用正式诊断发布链写入一条最小合法诊断报告（焦点合同与"诊断存在"事实的数据源）

    名单与评分引用的角色必须先有本 run 的正式 character 实体，否则发布链拒绝；
    返回正式报告 report_id。
    """

    from src.storage.repositories.organization_writes import register_diagnosis_session
    from tests.support.event_tree_fixtures import ensure_character
    from tests.support.storage_fixtures import insert_report_fixture

    focus_names = list(focus_characters)
    main_names = list(main_characters or focus_names)
    core_names = list(core_cast or main_names)
    arc_names = list(dict.fromkeys([*focus_names, *main_names, *core_names]))
    arc_scores = {name: float(9 - index * 0.5) for index, name in enumerate(arc_names)}

    for name in arc_names:
        ensure_character(db_session, run_id=run_id, name=name)

    analysis = AgentAnalysis(
        novel_id=novel_id,
        arc_scores=arc_scores,
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels=dict(topic_labels or {"0": "关系命运"}),
        diagnosis=diagnosis,
        focus_structure="single" if len(focus_names) == 1 else "dual" if len(focus_names) == 2 else "ensemble",
        focus_characters=focus_names,
        main_characters=main_names,
        core_cast=core_names,
    )
    session_id = new_id()
    register_diagnosis_session(db_session, run_id=run_id, session_id=session_id)
    report_id = insert_report_fixture(db_session, run_id, session_id, analysis)
    db_session.commit()
    return report_id


def insert_partial_diagnosis(db_session, *, run_id: str, diagnosis: str) -> str:
    """用正式发布链写入只有正文的诊断报告（标签/名单/评分缺失的真实部分结果）"""

    from src.storage.repositories.organization_writes import register_diagnosis_session
    from tests.support.storage_fixtures import insert_report_fixture

    session_id = new_id()
    register_diagnosis_session(db_session, run_id=run_id, session_id=session_id)
    report_id = insert_report_fixture(db_session, run_id, session_id, AgentAnalysis(diagnosis=diagnosis))
    db_session.commit()
    return report_id
