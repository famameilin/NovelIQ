"""所属领域的产物完整性查询，供恢复编排调用

从 diagnosis_reports 报告头、agent_assessments 的标签/名单条目与
event_records 发布事实判定，正文与评分列、组织发布事实分别核对。
"""

from __future__ import annotations

from src.storage import Storage


def has_diagnosis_data(session: Storage, run_id: str) -> bool:
    """检查指定运行是否有完整诊断数据。Args: session/run_id；Returns: 是否存在。"""

    report = session.reads.diagnosis_completion_has_diagnosis_data_1(run_id)
    if report is None:
        return False
    # 正式组织必须已发布：本 run 存在完整事件（生产者执行属于本 run），且报告冻结了身份与结构快照
    published = session.reads.final_diagnosis_completion_has_diagnosis_data_1(run_id)
    if published is None or report.content_snapshot is None or report.structure_snapshot is None:
        return False

    def _has_cast(cast_role: str) -> bool:
        return session.reads.diagnosis_completion_has_cast_1(cast_role, report) is not None

    def _has_label(column) -> bool:
        return session.reads.diagnosis_completion_has_label_1(column, report) is not None

    # 正式诊断必须有焦点结构和三组角色名单，只有旧字段的半成品行不算完成
    if report.focus_structure not in {"single", "dual", "ensemble"}:
        return False
    if not (_has_cast("focus") and _has_cast("main") and _has_cast("core")):
        return False

    return any(
        (
            report.diagnosis is not None,
            report.value_logic_type is not None,
            report.value_logic_reason is not None,
            report.power_stance_score is not None,
            report.power_stance_reason is not None,
            report.common_people_dignity is not None,
            report.dignity_reason is not None,
            report.cultural_depth_score is not None,
            report.cultural_depth_reason is not None,
            report.narrative_arc_type is not None,
            report.theme_color is not None,
            _has_label("genre_label"),
            _has_label("style_label"),
            _has_label("topic_label"),
        )
    )
