"""
创建时间: 2026-04-26
任务: fix-phase2-setup-pool-followup-findings
说明: 覆盖 diagnosis 工作流日志的正式预期输出标签。

修改时间: 2026-10-16
任务: 全库第三范式改造收尾
修改内容: 实体行上的 is_main_character 旧标记面与 save_main_characters 已退场，
主角名单改为报告作用域的 analysis_assessments 名单行；本测试按其当前等价行为
（run 作用域读取只返回诊断提交的名单，实体上没有可残留的旧主角标记）重写。
"""

from __future__ import annotations

from src.storage.models import GraphEntity
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import add_diagnosis_context


def test_main_character_list_is_report_scoped_without_stale_members(db_session) -> None:
    """诊断提交的主角名单按报告行写入；run 作用域读取只返回本次名单成员，
    未上榜角色（旧主角）不会因历史标记残留出现在名单投影里"""
    from uuid import NAMESPACE_DNS, uuid5

    from src.agents.diagnosis.persistence import save_diagnosis_report
    from src.diagnosis.read import fetch_diagnosis_payload
    from src.diagnosis.schema import AgentAnalysis

    novel_id, run_id = create_run_with_chunks(db_session, texts=["原文"])

    def _entity_id(name: str) -> str:
        # 2026-09-19 id 纪律：entity_id 是 uuid 主键，手工构造必须显式给
        # （与 persistence 同一铸造规则：uuid5(run_scope + 规范名)）
        return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity:{run_id}:{name.casefold()}"))

    db_session.add_all(
        [
            GraphEntity(
                entity_id=_entity_id(name),
                run_id=run_id,
                canonical_name=name,
                entity_type="character",
            )
            for name in ("旧主角", "新主角")
        ]
    )
    session_id, _execution_id = add_diagnosis_context(db_session, run_id)
    db_session.flush()

    # 正式报告条目写入：新主角上榜，旧主角只在评分里（已下榜）
    save_diagnosis_report(
        db_session,
        run_id,
        session_id,
        AgentAnalysis(
            novel_id=novel_id,
            arc_scores={"旧主角": 6.0, "新主角": 9.0},
            main_characters=["新主角"],
            core_cast=["新主角"],
        ),
    )
    db_session.commit()

    payload = fetch_diagnosis_payload(db_session, run_id)
    assert payload is not None
    assert payload["main_characters"] == ["新主角"]
    assert payload["core_cast"] == ["新主角"]
    assert "旧主角" not in payload["main_characters"]
