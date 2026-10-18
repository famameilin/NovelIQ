"""领域约束触发器：标准 PK/FK/UNIQUE/CHECK 表达不了的跨表规则在数据库层落地

安装入口 install_domain_constraints(engine)：init_db 与测试夹具在建表后调用；
全部语句可重复执行（CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS + CREATE）。

规则清单（与冻结模型注释一一对应）：
1. chapter_annotations：每 work 至多一份正式成功记录（经 execution→work 推导）
2. diagnosis_reports：每 run 至多一份正式发布（经 session→run 推导）
3. paragraph_topics / paragraph_metrics：只有推断状态 complete 的段落可写主题行；
   主题行必须是完整 0..K-1 覆盖且权重和为 1；complete 与主题行数互相一致
4. conflict_records：每条冲突至少两条独立陈述
5. organization_checks：结构对无序唯一（不得反向重复）
6. event_revisions：阶段序号从 0 连续
7. narrative_links 包含关系无环；narrative_groups 父链无环且父线只能是线
8. source_evidence：段号属于所有者所在 run 的段落且区间合法
9. case_entries：交付的接受序号在 run 内唯一
10. 跨表同 run：关系端点、声明参与者、对话说话人、评估条目、伏笔动作、
    冲突陈述、事件版本、叙事链路、组织核对、图谱事实引用
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import text

# 公共推导函数：run 直接读执行行自身的归属（invocation 的 run_id 或 session 的 session_run_id），
# 不经 work 链；work 支路只在程序回执的身份上求值

_HELPER_FUNCTIONS = (
    """
CREATE OR REPLACE FUNCTION dc_execution_run_id(p_execution_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT COALESCE(run_id, session_run_id)
      INTO v_run
      FROM executions
     WHERE execution_id = p_execution_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_work_run_id(p_work_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT COALESCE(w.annotation_run_id, w.program_run_id,
                    (SELECT se.session_run_id FROM executions se
                      WHERE se.execution_id = w.diagnosis_session_id))
      INTO v_run
      FROM work_items w
     WHERE w.work_id = p_work_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_entity_run_id(p_entity_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT run_id INTO v_run FROM graph_entities WHERE entity_id = p_entity_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_declaration_run_id(p_declaration_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT dc_execution_run_id(ca.execution_id) INTO v_run
      FROM event_declarations d
      JOIN chapter_annotations ca ON ca.record_id = d.record_id
     WHERE d.declaration_id = p_declaration_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_complete_event_run_id(p_event_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT dc_execution_run_id(ce.producer_execution_id) INTO v_run
      FROM complete_events ce
     WHERE ce.event_id = p_event_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_group_run_id(p_group_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT dc_execution_run_id(g.producer_execution_id) INTO v_run
      FROM narrative_groups g
     WHERE g.group_id = p_group_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_require_same_run(p_expected text, p_actual text, p_label text) RETURNS void AS $dc$
BEGIN
    IF p_expected IS NOT NULL AND p_actual IS NOT NULL AND p_expected <> p_actual THEN
        RAISE EXCEPTION '跨运行引用: % 属于 run=%，所属生产链 run=%', p_label, p_actual, p_expected
            USING ERRCODE = 'foreign_key_violation';
    END IF;
END
$dc$ LANGUAGE plpgsql
""",
)

# ---------------------------------------------------------------------------
# 规则 1：每 work 至多一份正式章节标注记录
# ---------------------------------------------------------------------------

_CHAPTER_ANNOTATION_PER_WORK = (
    """
CREATE OR REPLACE FUNCTION dc_chapter_annotation_per_work() RETURNS trigger AS $dc$
DECLARE
    v_work text;
    v_count integer;
BEGIN
    SELECT e.work_id INTO v_work FROM executions e WHERE e.execution_id = NEW.execution_id;
    IF v_work IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO v_count
      FROM chapter_annotations ca
      JOIN executions e ON e.execution_id = ca.execution_id
     WHERE e.work_id = v_work;
    IF v_count > 1 THEN
        RAISE EXCEPTION '每 work 至多一份正式章节标注记录: work_id=%, records=%', v_work, v_count
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_chapter_annotation_per_work ON chapter_annotations",
    """
CREATE CONSTRAINT TRIGGER trg_dc_chapter_annotation_per_work
    AFTER INSERT OR UPDATE ON chapter_annotations
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_chapter_annotation_per_work()
""",
)

# ---------------------------------------------------------------------------
# 规则 2：每 run 至多一份正式诊断发布
# ---------------------------------------------------------------------------

_DIAGNOSIS_REPORT_PER_RUN = (
    """
CREATE OR REPLACE FUNCTION dc_diagnosis_report_per_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
    v_count integer;
BEGIN
    v_run := dc_execution_run_id(NEW.session_id);
    IF v_run IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO v_count
      FROM diagnosis_reports dr
     WHERE dc_execution_run_id(dr.session_id) = v_run;
    IF v_count > 1 THEN
        RAISE EXCEPTION '每 run 至多一份正式诊断发布: run_id=%, reports=%', v_run, v_count
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_diagnosis_report_per_run ON diagnosis_reports",
    """
CREATE CONSTRAINT TRIGGER trg_dc_diagnosis_report_per_run
    AFTER INSERT OR UPDATE ON diagnosis_reports
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_diagnosis_report_per_run()
""",
)

# ---------------------------------------------------------------------------
# 规则 3：段落主题完整 K 维分布（前向形状 + 延迟覆盖 + 状态互证）
# ---------------------------------------------------------------------------

_PARAGRAPH_TOPIC_REQUIRES_COMPLETE = (
    """
CREATE OR REPLACE FUNCTION dc_paragraph_topic_requires_complete() RETURNS trigger AS $dc$
DECLARE
    v_status text;
    v_k integer;
BEGIN
    SELECT pm.inference_status INTO v_status
      FROM paragraph_metrics pm
     WHERE pm.run_id = NEW.run_id AND pm.paragraph_id = NEW.paragraph_id;
    IF v_status IS DISTINCT FROM 'complete' THEN
        RAISE EXCEPTION '只有推断状态为 complete 的段落可写主题行: run=%, paragraph=%, status=%',
            NEW.run_id, NEW.paragraph_id, COALESCE(v_status, '(无指标行)')
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT ar.lda_num_topics INTO v_k FROM analysis_runs ar WHERE ar.run_id = NEW.run_id;
    IF v_k IS NULL THEN
        RAISE EXCEPTION '运行缺少 LDA 主题数合同，不能写主题行: run_id=%', NEW.run_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.topic_id < 0 OR NEW.topic_id >= v_k THEN
        RAISE EXCEPTION '主题 id 超出 run 的 K 维合同: run=%, topic_id=%, K=%', NEW.run_id, NEW.topic_id, v_k
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_paragraph_topic_requires_complete ON paragraph_topics",
    """
CREATE TRIGGER trg_dc_paragraph_topic_requires_complete
    BEFORE INSERT OR UPDATE ON paragraph_topics
    FOR EACH ROW EXECUTE FUNCTION dc_paragraph_topic_requires_complete()
""",
)

_PARAGRAPH_TOPIC_COMPLETE_DISTRIBUTION = (
    """
CREATE OR REPLACE FUNCTION dc_paragraph_topic_complete_distribution() RETURNS trigger AS $dc$
DECLARE
    v_run text;
    v_paragraph integer;
    v_k integer;
    v_count integer;
    v_min integer;
    v_max integer;
    v_sum double precision;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_run := OLD.run_id;
        v_paragraph := OLD.paragraph_id;
    ELSE
        v_run := NEW.run_id;
        v_paragraph := NEW.paragraph_id;
    END IF;
    SELECT ar.lda_num_topics INTO v_k FROM analysis_runs ar WHERE ar.run_id = v_run;
    IF v_k IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*), min(topic_id), max(topic_id), COALESCE(sum(topic_weight), 0)
      INTO v_count, v_min, v_max, v_sum
      FROM paragraph_topics
     WHERE run_id = v_run AND paragraph_id = v_paragraph;
    IF v_count > 0 AND (v_count <> v_k OR v_min <> 0 OR v_max <> v_k - 1 OR abs(v_sum - 1) > 0.000001) THEN
        RAISE EXCEPTION '段落主题分布必须是完整 0..K-1 且权重和为 1: run=%, paragraph=%, rows=%, K=%, sum=%',
            v_run, v_paragraph, v_count, v_k, v_sum
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_paragraph_topic_complete_distribution ON paragraph_topics",
    """
CREATE CONSTRAINT TRIGGER trg_dc_paragraph_topic_complete_distribution
    AFTER INSERT OR UPDATE OR DELETE ON paragraph_topics
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_paragraph_topic_complete_distribution()
""",
)

_PARAGRAPH_METRIC_INFERENCE_ROWS = (
    """
CREATE OR REPLACE FUNCTION dc_paragraph_metric_inference_rows() RETURNS trigger AS $dc$
DECLARE
    v_k integer;
    v_count integer;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.inference_status IS NOT DISTINCT FROM OLD.inference_status THEN
        RETURN NULL;
    END IF;
    SELECT ar.lda_num_topics INTO v_k FROM analysis_runs ar WHERE ar.run_id = NEW.run_id;
    IF v_k IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO v_count
      FROM paragraph_topics
     WHERE run_id = NEW.run_id AND paragraph_id = NEW.paragraph_id;
    IF NEW.inference_status = 'complete' THEN
        IF v_count <> v_k THEN
            RAISE EXCEPTION 'complete 段落必须有完整 K 维主题行: run=%, paragraph=%, rows=%, K=%',
                NEW.run_id, NEW.paragraph_id, v_count, v_k
                USING ERRCODE = 'check_violation';
        END IF;
    ELSIF v_count > 0 THEN
        RAISE EXCEPTION '非 complete 段落不得留主题行: run=%, paragraph=%, status=%, rows=%',
            NEW.run_id, NEW.paragraph_id, NEW.inference_status, v_count
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_paragraph_metric_inference_rows ON paragraph_metrics",
    """
CREATE CONSTRAINT TRIGGER trg_dc_paragraph_metric_inference_rows
    AFTER INSERT OR UPDATE ON paragraph_metrics
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_paragraph_metric_inference_rows()
""",
)

# ---------------------------------------------------------------------------
# 规则 4：冲突至少两条独立陈述
# ---------------------------------------------------------------------------

_CONFLICT_MIN_CLAIMS = (
    """
CREATE OR REPLACE FUNCTION dc_conflict_min_claims() RETURNS trigger AS $dc$
DECLARE
    v_conflict text;
    v_records integer;
    v_claims integer;
BEGIN
    IF TG_TABLE_NAME = 'conflict_records' THEN
        v_conflict := NEW.conflict_id;
    ELSIF TG_OP = 'DELETE' THEN
        v_conflict := OLD.conflict_id;
    ELSE
        v_conflict := NEW.conflict_id;
    END IF;
    SELECT count(*) INTO v_records FROM conflict_records WHERE conflict_id = v_conflict;
    IF v_records = 0 THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO v_claims FROM conflict_claims WHERE conflict_id = v_conflict;
    IF v_claims < 2 THEN
        RAISE EXCEPTION '冲突登记至少需要两条独立陈述: conflict_id=%, claims=%', v_conflict, v_claims
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_conflict_min_claims_records ON conflict_records",
    """
CREATE CONSTRAINT TRIGGER trg_dc_conflict_min_claims_records
    AFTER INSERT OR UPDATE ON conflict_records
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_conflict_min_claims()
""",
    "DROP TRIGGER IF EXISTS trg_dc_conflict_min_claims_claims ON conflict_claims",
    """
CREATE CONSTRAINT TRIGGER trg_dc_conflict_min_claims_claims
    AFTER INSERT OR UPDATE OR DELETE ON conflict_claims
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_conflict_min_claims()
""",
)

# ---------------------------------------------------------------------------
# 规则 5：结构对无序唯一
# ---------------------------------------------------------------------------

_ORGANIZATION_CHECK_PAIR_DIRECTION = (
    """
CREATE OR REPLACE FUNCTION dc_organization_check_pair_direction() RETURNS trigger AS $dc$
BEGIN
    IF NEW.source_event_id IS NULL OR NEW.source_event_id = NEW.target_event_id THEN
        RETURN NULL;
    END IF;
    IF EXISTS (
        SELECT 1 FROM organization_checks c
         WHERE c.source_event_id = NEW.target_event_id
           AND c.target_event_id = NEW.source_event_id
           AND c.check_id <> NEW.check_id
    ) THEN
        RAISE EXCEPTION '结构对无序唯一，不得反向重复登记: source=%, target=%', NEW.source_event_id, NEW.target_event_id
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_organization_check_pair_direction ON organization_checks",
    """
CREATE TRIGGER trg_dc_organization_check_pair_direction
    AFTER INSERT OR UPDATE ON organization_checks
    FOR EACH ROW EXECUTE FUNCTION dc_organization_check_pair_direction()
""",
)

# ---------------------------------------------------------------------------
# 规则 6：事件阶段序号从 0 连续
# ---------------------------------------------------------------------------

_EVENT_REVISION_STAGE_CHAIN = (
    """
CREATE OR REPLACE FUNCTION dc_event_revision_stage_chain() RETURNS trigger AS $dc$
DECLARE
    v_event text;
    v_count integer;
    v_min integer;
    v_max integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_event := OLD.event_id;
    ELSE
        v_event := NEW.event_id;
    END IF;
    SELECT count(*), min(stage_index), max(stage_index) INTO v_count, v_min, v_max
      FROM event_revisions WHERE event_id = v_event;
    IF v_count > 0 AND (v_min <> 0 OR v_count <> v_max + 1) THEN
        RAISE EXCEPTION '事件阶段序号必须从 0 连续: event_id=%, rows=%, min=%, max=%',
            v_event, v_count, v_min, v_max
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_event_revision_stage_chain ON event_revisions",
    """
CREATE CONSTRAINT TRIGGER trg_dc_event_revision_stage_chain
    AFTER INSERT OR UPDATE OR DELETE ON event_revisions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_event_revision_stage_chain()
""",
)

# ---------------------------------------------------------------------------
# 规则 7：包含/父链无环
# ---------------------------------------------------------------------------

_NARRATIVE_LINK_NO_CONTAINMENT_CYCLE = (
    """
CREATE OR REPLACE FUNCTION dc_narrative_link_no_containment_cycle() RETURNS trigger AS $dc$
DECLARE
    v_found text;
BEGIN
    IF NEW.contained_child_id IS NULL THEN
        RETURN NULL;
    END IF;
    WITH RECURSIVE up AS (
        SELECT NEW.contained_parent_id AS id, 1 AS depth
        UNION ALL
        SELECT l.contained_parent_id, up.depth + 1
          FROM narrative_links l
          JOIN up ON l.contained_child_id = up.id
         WHERE l.contained_child_id IS NOT NULL AND up.depth < 4096
    )
    SELECT up.id INTO v_found FROM up WHERE up.id = NEW.contained_child_id LIMIT 1;
    IF v_found IS NOT NULL THEN
        RAISE EXCEPTION '包含关系不得成环: child=%, parent=%', NEW.contained_child_id, NEW.contained_parent_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_narrative_link_no_containment_cycle ON narrative_links",
    """
CREATE TRIGGER trg_dc_narrative_link_no_containment_cycle
    AFTER INSERT OR UPDATE ON narrative_links
    FOR EACH ROW EXECUTE FUNCTION dc_narrative_link_no_containment_cycle()
""",
)

_NARRATIVE_GROUP_PARENT_CHAIN = (
    """
CREATE OR REPLACE FUNCTION dc_narrative_group_parent_chain() RETURNS trigger AS $dc$
DECLARE
    v_found text;
BEGIN
    IF NEW.parent_arc_id IS NULL THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM narrative_groups g WHERE g.group_id = NEW.parent_arc_id AND g.arc_kind IS NOT NULL
    ) THEN
        RAISE EXCEPTION '父线必须是有线形状的节点: parent=%', NEW.parent_arc_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.arc_kind IS NULL AND EXISTS (
        SELECT 1 FROM narrative_groups c WHERE c.parent_arc_id = NEW.group_id
    ) THEN
        RAISE EXCEPTION '存在子线的节点不能改为结果形状: group_id=%', NEW.group_id
            USING ERRCODE = 'check_violation';
    END IF;
    WITH RECURSIVE up AS (
        SELECT NEW.parent_arc_id AS id, 1 AS depth
        UNION ALL
        SELECT g.parent_arc_id, up.depth + 1
          FROM narrative_groups g
          JOIN up ON g.group_id = up.id
         WHERE g.parent_arc_id IS NOT NULL AND up.depth < 4096
    )
    SELECT up.id INTO v_found FROM up WHERE up.id = NEW.group_id LIMIT 1;
    IF v_found IS NOT NULL THEN
        RAISE EXCEPTION '叙事线父链不得成环: group_id=%', NEW.group_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_narrative_group_parent_chain ON narrative_groups",
    """
CREATE TRIGGER trg_dc_narrative_group_parent_chain
    AFTER INSERT OR UPDATE ON narrative_groups
    FOR EACH ROW EXECUTE FUNCTION dc_narrative_group_parent_chain()
""",
)

# ---------------------------------------------------------------------------
# 规则 8：原文证据属于所有者 run 的段落且区间合法
# ---------------------------------------------------------------------------

_SOURCE_EVIDENCE_OWNER_RUN = (
    """
CREATE OR REPLACE FUNCTION dc_source_evidence_owner_run(
    p_graph_fact_id bigint, p_declaration_id text, p_complete_event_id text, p_narrative_group_id text,
    p_narrative_link_id text, p_foreshadow_action_id text, p_conflict_id text, p_claim_id text, p_check_id text
) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    IF p_graph_fact_id IS NOT NULL THEN
        SELECT COALESCE(dc_execution_run_id(gf.direct_producer_execution_id), dc_work_run_id(gf.program_work_id))
          INTO v_run
          FROM graph_facts gf
         WHERE gf.graph_fact_id = p_graph_fact_id;
    ELSIF p_declaration_id IS NOT NULL THEN
        v_run := dc_declaration_run_id(p_declaration_id);
    ELSIF p_complete_event_id IS NOT NULL THEN
        v_run := dc_complete_event_run_id(p_complete_event_id);
    ELSIF p_narrative_group_id IS NOT NULL THEN
        v_run := dc_group_run_id(p_narrative_group_id);
    ELSIF p_narrative_link_id IS NOT NULL THEN
        SELECT dc_execution_run_id(l.producer_execution_id) INTO v_run
          FROM narrative_links l WHERE l.link_id = p_narrative_link_id;
    ELSIF p_foreshadow_action_id IS NOT NULL THEN
        SELECT dc_execution_run_id(a.producer_execution_id) INTO v_run
          FROM event_foreshadowing_actions a WHERE a.action_id = p_foreshadow_action_id;
    ELSIF p_conflict_id IS NOT NULL THEN
        SELECT dc_execution_run_id(c.producer_execution_id) INTO v_run
          FROM conflict_records c WHERE c.conflict_id = p_conflict_id;
    ELSIF p_claim_id IS NOT NULL THEN
        SELECT dc_execution_run_id(cl.producer_execution_id) INTO v_run
          FROM conflict_claims cl WHERE cl.claim_id = p_claim_id;
    ELSIF p_check_id IS NOT NULL THEN
        SELECT dc_execution_run_id(ck.producer_execution_id) INTO v_run
          FROM organization_checks ck WHERE ck.check_id = p_check_id;
    END IF;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_source_evidence_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
    v_len integer;
BEGIN
    v_run := dc_source_evidence_owner_run(
        NEW.graph_fact_id, NEW.declaration_id, NEW.complete_event_id, NEW.narrative_group_id,
        NEW.narrative_link_id, NEW.foreshadow_action_id, NEW.conflict_id, NEW.claim_id, NEW.check_id);
    IF v_run IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT length(p.text) INTO v_len
      FROM paragraphs p
     WHERE p.run_id = v_run AND p.paragraph_id = NEW.paragraph_id;
    IF v_len IS NULL THEN
        RAISE EXCEPTION '证据段号不属于所有者所在 run 的段落: run=%, paragraph=%', v_run, NEW.paragraph_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.start_char < 0 OR NEW.end_char > v_len THEN
        RAISE EXCEPTION '证据区间超出段落文本: paragraph=%, [%,%), len=%',
            NEW.paragraph_id, NEW.start_char, NEW.end_char, v_len
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_source_evidence_same_run ON source_evidence",
    """
CREATE TRIGGER trg_dc_source_evidence_same_run
    BEFORE INSERT OR UPDATE ON source_evidence
    FOR EACH ROW EXECUTE FUNCTION dc_source_evidence_same_run()
""",
)

# ---------------------------------------------------------------------------
# 规则 9：案例交付的 run 内接受序号唯一
# ---------------------------------------------------------------------------

_CASE_ENTRY_RUN_ORDER = (
    """
CREATE OR REPLACE FUNCTION dc_case_entry_support_run(p_entry_id text) RETURNS text AS $dc$
DECLARE
    v_run text;
BEGIN
    SELECT CASE
             WHEN s.producer_execution_id IS NOT NULL THEN dc_execution_run_id(s.producer_execution_id)
             WHEN s.program_work_id IS NOT NULL THEN dc_work_run_id(s.program_work_id)
             WHEN s.candidate_producer_execution_id IS NOT NULL
                  THEN dc_execution_run_id(s.candidate_producer_execution_id)
           END
      INTO v_run
      FROM case_entries s
     WHERE s.entry_id = p_entry_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql
""",
    """
CREATE OR REPLACE FUNCTION dc_case_entry_run_order() RETURNS trigger AS $dc$
DECLARE
    v_run text;
    v_dup text;
BEGIN
    IF NEW.accepted_order IS NULL OR NEW.parent_entry_id IS NULL THEN
        RETURN NULL;
    END IF;
    v_run := dc_case_entry_support_run(NEW.parent_entry_id);
    IF v_run IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT d.entry_id INTO v_dup
      FROM case_entries d
     WHERE d.accepted_order = NEW.accepted_order
       AND d.entry_id <> NEW.entry_id
       AND d.parent_entry_id IS NOT NULL
       AND dc_case_entry_support_run(d.parent_entry_id) = v_run
     LIMIT 1;
    IF v_dup IS NOT NULL THEN
        RAISE EXCEPTION '案例交付的 run 内接受序号必须唯一: run=%, accepted_order=%', v_run, NEW.accepted_order
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_dc_case_entry_run_order ON case_entries",
    """
CREATE TRIGGER trg_dc_case_entry_run_order
    AFTER INSERT OR UPDATE ON case_entries
    FOR EACH ROW EXECUTE FUNCTION dc_case_entry_run_order()
""",
)

# ---------------------------------------------------------------------------
# 规则 10：跨表同 run（引用方与真实生产链的 run 必须一致）
# ---------------------------------------------------------------------------

_SAME_RUN_TRIGGERS = (
    (
        """
CREATE OR REPLACE FUNCTION dc_graph_relation_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(dc_entity_run_id(NEW.from_entity_id), dc_entity_run_id(NEW.to_entity_id), '关系端点');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_graph_relation_same_run ON graph_relations",
        """
CREATE TRIGGER trg_dc_graph_relation_same_run
    AFTER INSERT OR UPDATE ON graph_relations
    FOR EACH ROW EXECUTE FUNCTION dc_graph_relation_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_declaration_participant_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(
        dc_declaration_run_id(NEW.declaration_id), dc_entity_run_id(NEW.entity_id), '声明参与者实体');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_declaration_participant_same_run ON declaration_participants",
        """
CREATE TRIGGER trg_dc_declaration_participant_same_run
    AFTER INSERT OR UPDATE ON declaration_participants
    FOR EACH ROW EXECUTE FUNCTION dc_declaration_participant_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_dialogue_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
BEGIN
    v_run := dc_execution_run_id(NEW.creation_execution_id);
    PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.speaker_entity_id), '对话说话人');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.related_declaration_id), '对话关联声明');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.related_complete_event_id), '对话关联事件');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_dialogue_same_run ON dialogue_records",
        """
CREATE TRIGGER trg_dc_dialogue_same_run
    AFTER INSERT OR UPDATE ON dialogue_records
    FOR EACH ROW EXECUTE FUNCTION dc_dialogue_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_analysis_assessment_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
    v_len integer;
BEGIN
    IF NEW.record_id IS NOT NULL THEN
        SELECT dc_execution_run_id(ca.execution_id) INTO v_run
          FROM chapter_annotations ca WHERE ca.record_id = NEW.record_id;
        IF v_run IS NOT NULL AND NEW.paragraph_id IS NOT NULL THEN
            SELECT length(p.text) INTO v_len
              FROM paragraphs p WHERE p.run_id = v_run AND p.paragraph_id = NEW.paragraph_id;
            IF v_len IS NULL THEN
                RAISE EXCEPTION '评估段号不属于记录所在 run 的段落: run=%, paragraph=%', v_run, NEW.paragraph_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
        END IF;
    ELSIF NEW.report_id IS NOT NULL THEN
        SELECT dc_execution_run_id(dr.session_id) INTO v_run
          FROM diagnosis_reports dr WHERE dr.report_id = NEW.report_id;
        PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.scored_entity_id), '评分角色实体');
        PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.cast_entity_id), '名单角色实体');
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_analysis_assessment_same_run ON analysis_assessments",
        """
CREATE TRIGGER trg_dc_analysis_assessment_same_run
    AFTER INSERT OR UPDATE ON analysis_assessments
    FOR EACH ROW EXECUTE FUNCTION dc_analysis_assessment_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_foreshadow_action_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
BEGIN
    v_run := dc_execution_run_id(NEW.producer_execution_id);
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.source_declaration_id), '伏笔来源声明');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.target_declaration_id), '伏笔目标声明');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_foreshadow_action_same_run ON event_foreshadowing_actions",
        """
CREATE TRIGGER trg_dc_foreshadow_action_same_run
    AFTER INSERT OR UPDATE ON event_foreshadowing_actions
    FOR EACH ROW EXECUTE FUNCTION dc_foreshadow_action_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_conflict_claim_same_run() RETURNS trigger AS $dc$
DECLARE
    v_conflict text;
    v_expected text;
BEGIN
    v_conflict := COALESCE(NEW.conflict_id, OLD.conflict_id);
    SELECT dc_execution_run_id(c.producer_execution_id) INTO v_expected
      FROM conflict_records c WHERE c.conflict_id = v_conflict;
    PERFORM dc_require_same_run(v_expected, dc_execution_run_id(NEW.producer_execution_id), '冲突陈述生产者');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_conflict_claim_same_run ON conflict_claims",
        """
CREATE TRIGGER trg_dc_conflict_claim_same_run
    AFTER INSERT OR UPDATE ON conflict_claims
    FOR EACH ROW EXECUTE FUNCTION dc_conflict_claim_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_event_revision_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(
        dc_complete_event_run_id(NEW.event_id), dc_declaration_run_id(NEW.declaration_id), '事件版本绑定声明');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_event_revision_same_run ON event_revisions",
        """
CREATE TRIGGER trg_dc_event_revision_same_run
    AFTER INSERT OR UPDATE ON event_revisions
    FOR EACH ROW EXECUTE FUNCTION dc_event_revision_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_narrative_link_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
BEGIN
    v_run := dc_execution_run_id(NEW.producer_execution_id);
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.semantic_source_event_id), '链路源端事件');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.semantic_source_declaration_id), '链路源端声明');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.semantic_target_event_id), '链路目标端事件');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.semantic_target_declaration_id), '链路目标端声明');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.contained_child_id), '包含子端事件');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.contained_parent_id), '包含父端事件');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.member_event_id), '事件—线成员事件');
    PERFORM dc_require_same_run(v_run, dc_group_run_id(NEW.arc_group_id), '事件—线叙事线');
    PERFORM dc_require_same_run(v_run, dc_group_run_id(NEW.outcome_group_id), '事件—结果结果组');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_narrative_link_same_run ON narrative_links",
        """
CREATE TRIGGER trg_dc_narrative_link_same_run
    AFTER INSERT OR UPDATE ON narrative_links
    FOR EACH ROW EXECUTE FUNCTION dc_narrative_link_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_organization_check_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
BEGIN
    v_run := dc_execution_run_id(NEW.producer_execution_id);
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.reviewed_event_id), '核对事件');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.reviewed_declaration_id), '核对声明');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.source_declaration_id), '声明对源端');
    PERFORM dc_require_same_run(v_run, dc_declaration_run_id(NEW.target_declaration_id), '声明对目标端');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.source_event_id), '结构对源端');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.target_event_id), '结构对目标端');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_organization_check_same_run ON organization_checks",
        """
CREATE TRIGGER trg_dc_organization_check_same_run
    AFTER INSERT OR UPDATE ON organization_checks
    FOR EACH ROW EXECUTE FUNCTION dc_organization_check_same_run()
""",
    ),
    (
        """
CREATE OR REPLACE FUNCTION dc_graph_fact_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run text;
BEGIN
    v_run := COALESCE(
        dc_execution_run_id(NEW.direct_producer_execution_id),
        dc_work_run_id(NEW.program_work_id));
    PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.entity_id), '图谱事实实体');
    IF NEW.relation_id IS NOT NULL THEN
        PERFORM dc_require_same_run(
            v_run,
            (SELECT dc_entity_run_id(r.from_entity_id) FROM graph_relations r WHERE r.relation_id = NEW.relation_id),
            '图谱事实关系端点');
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql
""",
        "DROP TRIGGER IF EXISTS trg_dc_graph_fact_same_run ON graph_facts",
        """
CREATE TRIGGER trg_dc_graph_fact_same_run
    AFTER INSERT OR UPDATE ON graph_facts
    FOR EACH ROW EXECUTE FUNCTION dc_graph_fact_same_run()
""",
    ),
)


def domain_constraint_statements() -> Iterable[str]:
    """按依赖顺序返回全部领域约束 DDL 语句（每条独立执行）"""
    groups: list[tuple[str, ...]] = [
        _HELPER_FUNCTIONS,
        _CHAPTER_ANNOTATION_PER_WORK,
        _DIAGNOSIS_REPORT_PER_RUN,
        _PARAGRAPH_TOPIC_REQUIRES_COMPLETE,
        _PARAGRAPH_TOPIC_COMPLETE_DISTRIBUTION,
        _PARAGRAPH_METRIC_INFERENCE_ROWS,
        _CONFLICT_MIN_CLAIMS,
        _ORGANIZATION_CHECK_PAIR_DIRECTION,
        _EVENT_REVISION_STAGE_CHAIN,
        _NARRATIVE_LINK_NO_CONTAINMENT_CYCLE,
        _NARRATIVE_GROUP_PARENT_CHAIN,
        _SOURCE_EVIDENCE_OWNER_RUN,
        _CASE_ENTRY_RUN_ORDER,
        *((statement,) for trigger in _SAME_RUN_TRIGGERS for statement in trigger),
    ]
    for group in groups:
        yield from group


def install_domain_constraints(engine: Any) -> None:
    """在目标库安装全部领域约束触发器；可重复执行，非 PostgreSQL 方言直接跳过"""
    if getattr(getattr(engine, "dialect", None), "name", "") != "postgresql":
        return
    with engine.begin() as connection:
        for statement in domain_constraint_statements():
            connection.execute(text(statement))
