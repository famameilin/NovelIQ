"跨表运行归属、证据、事件结构与主题分布约束"

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import text

_STATEMENTS = (
    """CREATE OR REPLACE FUNCTION dc_agent_run_id(p_agent_id uuid) RETURNS uuid AS $dc$
DECLARE
    v_run uuid;
BEGIN
    SELECT run_id
      INTO v_run
      FROM agent
     WHERE id = p_agent_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION dc_entity_run_id(p_entity_id uuid) RETURNS uuid AS $dc$
DECLARE
    v_run uuid;
BEGIN
    SELECT run_id INTO v_run FROM graph_entities WHERE entity_id = p_entity_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION dc_complete_event_run_id(p_event_id uuid) RETURNS uuid AS $dc$
DECLARE
    v_run uuid;
BEGIN
    SELECT dc_agent_run_id(ce.producer_agent_id) INTO v_run
      FROM event_records ce
     WHERE ce.event_id = p_event_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION dc_group_run_id(p_group_id uuid) RETURNS uuid AS $dc$
DECLARE
    v_run uuid;
BEGIN
    SELECT dc_agent_run_id(g.producer_agent_id) INTO v_run
      FROM event_groups g
     WHERE g.group_id = p_group_id;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION dc_require_same_run(p_expected uuid, p_actual uuid, p_label text) RETURNS void AS $dc$
BEGIN
    IF p_expected IS NOT NULL AND p_actual IS NOT NULL AND p_expected <> p_actual THEN
        RAISE EXCEPTION '跨运行引用: % 属于 run=%，所属生产链 run=%', p_label, p_actual, p_expected
            USING ERRCODE = 'foreign_key_violation';
    END IF;
END
$dc$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION dc_diagnosis_report_per_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
    v_count integer;
BEGIN
    v_run := dc_agent_run_id(NEW.agent_id);
    IF v_run IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO v_count
      FROM diagnosis_reports dr
     WHERE dc_agent_run_id(dr.agent_id) = v_run;
    IF v_count > 1 THEN
        RAISE EXCEPTION '每 run 至多一份正式诊断发布: run_id=%, reports=%', v_run, v_count
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_diagnosis_report_per_run ON diagnosis_reports""",
    """CREATE CONSTRAINT TRIGGER trg_dc_diagnosis_report_per_run
    AFTER INSERT OR UPDATE ON diagnosis_reports
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_diagnosis_report_per_run()""",
    """CREATE OR REPLACE FUNCTION dc_organization_check_pair_direction() RETURNS trigger AS $dc$
BEGIN
    IF NEW.source_event_id IS NULL OR NEW.source_event_id = NEW.target_event_id THEN
        RETURN NULL;
    END IF;
    IF EXISTS (
        SELECT 1 FROM event_checks c
         WHERE c.source_event_id = NEW.target_event_id
           AND c.target_event_id = NEW.source_event_id
           AND c.check_id <> NEW.check_id
    ) THEN
        RAISE EXCEPTION '结构对无序唯一，不得反向重复登记: source=%, target=%', NEW.source_event_id, NEW.target_event_id
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_organization_check_pair_direction ON event_checks""",
    """CREATE TRIGGER trg_dc_organization_check_pair_direction
    AFTER INSERT OR UPDATE ON event_checks
    FOR EACH ROW EXECUTE FUNCTION dc_organization_check_pair_direction()""",
    """CREATE OR REPLACE FUNCTION dc_narrative_link_no_containment_cycle() RETURNS trigger AS $dc$
DECLARE
    v_found uuid;
BEGIN
    IF NEW.child_tree_id IS NULL THEN
        RETURN NULL;
    END IF;
    WITH RECURSIVE up AS (
        SELECT NEW.parent_tree_id AS id
        UNION
        SELECT l.parent_tree_id
          FROM event_links l
          JOIN up ON l.child_tree_id = up.id
         WHERE l.child_tree_id IS NOT NULL
    )
    SELECT up.id INTO v_found FROM up WHERE up.id = NEW.child_tree_id LIMIT 1;
    IF v_found IS NOT NULL THEN
        RAISE EXCEPTION '包含关系不得成环: child=%, parent=%', NEW.child_tree_id, NEW.parent_tree_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_narrative_link_no_containment_cycle ON event_links""",
    """CREATE TRIGGER trg_dc_narrative_link_no_containment_cycle
    AFTER INSERT OR UPDATE ON event_links
    FOR EACH ROW EXECUTE FUNCTION dc_narrative_link_no_containment_cycle()""",
    """CREATE OR REPLACE FUNCTION dc_tree_complete() RETURNS trigger AS $dc$
DECLARE
    v_tree uuid;
    v_kind text;
    v_count bigint;
    v_min integer;
    v_max integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_tree := OLD.tree_id;
        IF v_tree IS NOT NULL THEN
            SELECT count(*), min(position), max(position)
              INTO v_count, v_min, v_max
              FROM event_links WHERE tree_id = v_tree;
            IF v_count > 0 AND (v_min <> 0 OR v_max <> v_count - 1) THEN
                RAISE EXCEPTION '事件树成员位置必须从 0 连续: %', v_tree
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NULL;
    END IF;
    FOREACH v_tree IN ARRAY ARRAY[NEW.tree_id, NEW.parent_tree_id, NEW.child_tree_id]
    LOOP
        IF v_tree IS NULL THEN CONTINUE; END IF;
        SELECT kind INTO v_kind FROM event_groups WHERE group_id = v_tree;
        IF v_kind IS DISTINCT FROM 'tree' THEN
            RAISE EXCEPTION '事件树身份不存在或不是树: %', v_tree
                USING ERRCODE = 'foreign_key_violation';
        END IF;
        SELECT count(*), min(position), max(position)
          INTO v_count, v_min, v_max
          FROM event_links WHERE tree_id = v_tree;
        IF v_count > 0 AND (v_min <> 0 OR v_max <> v_count - 1) THEN
            RAISE EXCEPTION '事件树成员位置必须从 0 连续: %', v_tree
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_queue_complete ON event_links""",
    """DROP TRIGGER IF EXISTS trg_dc_tree_complete ON event_links""",
    """CREATE CONSTRAINT TRIGGER trg_dc_tree_complete
    AFTER INSERT OR UPDATE OR DELETE ON event_links DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dc_tree_complete()""",
    """CREATE OR REPLACE FUNCTION dc_source_evidence_owner_run(
    p_graph_fact_id uuid, p_complete_event_id uuid, p_narrative_group_id uuid,
    p_narrative_link_id uuid, p_foreshadow_action_id uuid, p_check_id uuid
) RETURNS uuid AS $dc$
DECLARE
    v_run uuid;
BEGIN
    IF p_graph_fact_id IS NOT NULL THEN
        SELECT COALESCE(dc_agent_run_id(gf.direct_producer_agent_id),
            (SELECT dc_complete_event_run_id(dp.event_id)
             FROM event_participants dp WHERE dp.participant_id = gf.participant_id))
          INTO v_run
          FROM graph_facts gf
         WHERE gf.graph_fact_id = p_graph_fact_id;
    ELSIF p_complete_event_id IS NOT NULL THEN
        v_run := dc_complete_event_run_id(p_complete_event_id);
    ELSIF p_narrative_group_id IS NOT NULL THEN
        v_run := dc_group_run_id(p_narrative_group_id);
    ELSIF p_narrative_link_id IS NOT NULL THEN
        SELECT dc_agent_run_id(l.producer_agent_id) INTO v_run
          FROM event_links l WHERE l.link_id = p_narrative_link_id;
    ELSIF p_foreshadow_action_id IS NOT NULL THEN
        SELECT dc_agent_run_id(a.producer_agent_id) INTO v_run
          FROM event_foreshadowing_actions a WHERE a.action_id = p_foreshadow_action_id;
    ELSIF p_check_id IS NOT NULL THEN
        SELECT dc_agent_run_id(ck.producer_agent_id) INTO v_run
          FROM event_checks ck WHERE ck.check_id = p_check_id;
    END IF;
    RETURN v_run;
END
$dc$ LANGUAGE plpgsql""",
    """CREATE OR REPLACE FUNCTION dc_source_evidence_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
    v_len integer;
BEGIN
    v_run := dc_source_evidence_owner_run(
        NEW.graph_fact_id, NEW.complete_event_id, NEW.narrative_group_id,
        NEW.narrative_link_id, NEW.foreshadow_action_id, NEW.check_id);
    IF v_run IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.related_complete_event_id), '证据相关事件');
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
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_source_evidence_same_run ON paragraph_evidence""",
    """CREATE TRIGGER trg_dc_source_evidence_same_run
    BEFORE INSERT OR UPDATE ON paragraph_evidence
    FOR EACH ROW EXECUTE FUNCTION dc_source_evidence_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_graph_relation_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(dc_entity_run_id(NEW.from_entity_id), dc_entity_run_id(NEW.to_entity_id), '关系端点');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_graph_relation_same_run ON graph_relations""",
    """CREATE TRIGGER trg_dc_graph_relation_same_run
    AFTER INSERT OR UPDATE ON graph_relations
    FOR EACH ROW EXECUTE FUNCTION dc_graph_relation_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_event_participant_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(
        dc_complete_event_run_id(NEW.event_id), dc_entity_run_id(NEW.entity_id), '事件参与者实体');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_event_participant_same_run ON event_participants""",
    """CREATE TRIGGER trg_dc_event_participant_same_run
    AFTER INSERT OR UPDATE ON event_participants
    FOR EACH ROW EXECUTE FUNCTION dc_event_participant_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_dialogue_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
BEGIN
    v_run := dc_agent_run_id(NEW.creation_agent_id);
    PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.speaker_entity_id), '对话说话人');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.related_complete_event_id), '对话关联事件');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_dialogue_same_run ON graph_dialogues""",
    """CREATE TRIGGER trg_dc_dialogue_same_run
    AFTER INSERT OR UPDATE ON graph_dialogues
    FOR EACH ROW EXECUTE FUNCTION dc_dialogue_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_analysis_assessment_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
    v_len integer;
BEGIN
    IF NEW.record_id IS NOT NULL THEN
        SELECT dc_agent_run_id(ca.agent_id) INTO v_run
          FROM agent_annotations ca WHERE ca.record_id = NEW.record_id;
        IF v_run IS NOT NULL AND NEW.paragraph_id IS NOT NULL THEN
            SELECT length(p.text) INTO v_len
              FROM paragraphs p WHERE p.run_id = v_run AND p.paragraph_id = NEW.paragraph_id;
            IF v_len IS NULL THEN
                RAISE EXCEPTION '评估段号不属于记录所在 run 的段落: run=%, paragraph=%', v_run, NEW.paragraph_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
        END IF;
    ELSIF NEW.report_id IS NOT NULL THEN
        SELECT dc_agent_run_id(dr.agent_id) INTO v_run
          FROM diagnosis_reports dr WHERE dr.report_id = NEW.report_id;
        PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.scored_entity_id), '评分角色实体');
        PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.cast_entity_id), '名单角色实体');
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_analysis_assessment_same_run ON agent_assessments""",
    """CREATE TRIGGER trg_dc_analysis_assessment_same_run
    AFTER INSERT OR UPDATE ON agent_assessments
    FOR EACH ROW EXECUTE FUNCTION dc_analysis_assessment_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_foreshadow_action_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
BEGIN
    v_run := dc_agent_run_id(NEW.producer_agent_id);
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.source_event_id), '伏笔来源事件');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.target_event_id), '伏笔目标事件');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_foreshadow_action_same_run ON event_foreshadowing_actions""",
    """CREATE TRIGGER trg_dc_foreshadow_action_same_run
    AFTER INSERT OR UPDATE ON event_foreshadowing_actions
    FOR EACH ROW EXECUTE FUNCTION dc_foreshadow_action_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_narrative_link_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
BEGIN
    v_run := dc_agent_run_id(NEW.producer_agent_id);
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.semantic_source_event_id), '链路源端事件');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.semantic_target_event_id), '链路目标端事件');
    PERFORM dc_require_same_run(v_run, dc_group_run_id(NEW.tree_id), '事件树身份');
    PERFORM dc_require_same_run(v_run, dc_group_run_id(NEW.parent_tree_id), '父事件树');
    PERFORM dc_require_same_run(v_run, dc_group_run_id(NEW.child_tree_id), '子事件树');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.member_event_id), '树成员');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_narrative_link_same_run ON event_links""",
    """CREATE TRIGGER trg_dc_narrative_link_same_run
    AFTER INSERT OR UPDATE ON event_links
    FOR EACH ROW EXECUTE FUNCTION dc_narrative_link_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_organization_check_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
BEGIN
    v_run := dc_agent_run_id(NEW.producer_agent_id);
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.reviewed_event_id), '核对事件');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.source_event_id), '事件对源端');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.target_event_id), '事件对目标端');
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_organization_check_same_run ON event_checks""",
    """CREATE TRIGGER trg_dc_organization_check_same_run
    AFTER INSERT OR UPDATE ON event_checks
    FOR EACH ROW EXECUTE FUNCTION dc_organization_check_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_graph_fact_same_run() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
BEGIN
    v_run := COALESCE(
        dc_agent_run_id(NEW.direct_producer_agent_id),
        (SELECT dc_complete_event_run_id(dp.event_id)
         FROM event_participants dp WHERE dp.participant_id = NEW.participant_id));
    PERFORM dc_require_same_run(v_run, dc_entity_run_id(NEW.entity_id), '图谱事实实体');
    PERFORM dc_require_same_run(v_run, dc_complete_event_run_id(NEW.event_id), '情节推进来源事件');
    IF NEW.relation_id IS NOT NULL THEN
        PERFORM dc_require_same_run(
            v_run,
            (SELECT dc_entity_run_id(r.from_entity_id) FROM graph_relations r WHERE r.relation_id = NEW.relation_id),
            '图谱事实关系端点');
    END IF;
    RETURN NULL;
END
$dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_graph_fact_same_run ON graph_facts""",
    """CREATE TRIGGER trg_dc_graph_fact_same_run
    AFTER INSERT OR UPDATE ON graph_facts
    FOR EACH ROW EXECUTE FUNCTION dc_graph_fact_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_case_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(NEW.run_id, dc_agent_run_id(NEW.producer_agent_id), '案例登记 Agent');
    PERFORM dc_require_same_run(NEW.run_id, dc_agent_run_id(NEW.promised_agent_id), '案例承诺 Agent');
    RETURN NEW;
END $dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_case_same_run ON "case"
""",
    """CREATE TRIGGER trg_dc_case_same_run BEFORE INSERT OR UPDATE ON "case"
FOR EACH ROW EXECUTE FUNCTION dc_case_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_annotation_same_run() RETURNS trigger AS $dc$
BEGIN
    PERFORM dc_require_same_run(NEW.run_id, dc_agent_run_id(NEW.agent_id), '章节标注 Agent');
    RETURN NEW;
END $dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_annotation_same_run ON agent_annotations""",
    """CREATE TRIGGER trg_dc_annotation_same_run BEFORE INSERT OR UPDATE ON agent_annotations
FOR EACH ROW EXECUTE FUNCTION dc_annotation_same_run()""",
    """CREATE OR REPLACE FUNCTION dc_topic_distribution() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
    v_paragraph integer;
    v_status text;
    v_count integer;
    v_min integer;
    v_max integer;
    v_sum double precision;
BEGIN
    v_run := COALESCE(NEW.run_id, OLD.run_id);
    v_paragraph := COALESCE(NEW.paragraph_id, OLD.paragraph_id);
    SELECT inference_status INTO v_status FROM paragraph_metrics
      WHERE run_id = v_run AND paragraph_id = v_paragraph;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT count(*), min(topic_id), max(topic_id), sum(topic_weight)
      INTO v_count, v_min, v_max, v_sum FROM lda_paragraph_topics
      WHERE run_id = v_run AND paragraph_id = v_paragraph;
    IF v_status = 'complete' THEN
        IF v_count = 0 OR v_min <> 0 OR v_max <> v_count - 1 OR abs(v_sum - 1.0) > 0.000001 THEN
            RAISE EXCEPTION '段落主题分布不完整或权重和不为一' USING ERRCODE = 'check_violation';
        END IF;
    ELSIF v_count > 0 THEN
        RAISE EXCEPTION '未完成推断的段落不能保存主题权重' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_topic_distribution ON lda_paragraph_topics""",
    """CREATE CONSTRAINT TRIGGER trg_dc_topic_distribution AFTER INSERT OR UPDATE OR DELETE ON lda_paragraph_topics
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dc_topic_distribution()""",
    """DROP TRIGGER IF EXISTS trg_dc_metric_topic_distribution ON paragraph_metrics""",
    """CREATE CONSTRAINT TRIGGER trg_dc_metric_topic_distribution AFTER INSERT OR UPDATE ON paragraph_metrics
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dc_topic_distribution()""",
    """CREATE OR REPLACE FUNCTION dc_event_source_and_range() RETURNS trigger AS $dc$
DECLARE
    v_run uuid;
    v_from_sequence integer;
    v_to_sequence integer;
    v_source_agent uuid;
    v_source_run uuid;
    v_source_sequence integer;
BEGIN
    IF TG_OP = 'UPDATE' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION '已保存事件不可改写' USING ERRCODE = 'check_violation';
    END IF;
    v_run := dc_agent_run_id(NEW.producer_agent_id);
    SELECT sequence INTO v_from_sequence FROM chapters WHERE run_id = v_run AND chapter_id = NEW."from";
    SELECT sequence INTO v_to_sequence FROM chapters WHERE run_id = v_run AND chapter_id = NEW."to";
    IF v_from_sequence IS NULL OR v_to_sequence IS NULL THEN
        RAISE EXCEPTION '事件起止章节必须属于生产者所在运行' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF v_from_sequence > v_to_sequence THEN
        RAISE EXCEPTION '事件起始章节不得晚于结束章节' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.annotation_record_id IS NOT NULL THEN
        SELECT a.agent_id, a.run_id, c.sequence INTO v_source_agent, v_source_run, v_source_sequence
          FROM agent_annotations a JOIN chapters c ON c.run_id = a.run_id AND c.chapter_id = a.chapter_id
         WHERE a.record_id = NEW.annotation_record_id;
        IF v_source_agent IS DISTINCT FROM NEW.producer_agent_id OR v_source_run IS DISTINCT FROM v_run THEN
            RAISE EXCEPTION '事件标注来源必须属于同一真实生产执行' USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF v_to_sequence > v_source_sequence THEN
            RAISE EXCEPTION '标注事件范围不得超过来源标注章节' USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $dc$ LANGUAGE plpgsql""",
    """DROP TRIGGER IF EXISTS trg_dc_event_source_and_range ON event_records""",
    """CREATE TRIGGER trg_dc_event_source_and_range BEFORE INSERT OR UPDATE ON event_records
FOR EACH ROW EXECUTE FUNCTION dc_event_source_and_range()""",
)


def domain_constraint_statements() -> Iterable[str]:
    "按依赖顺序返回领域约束语句"
    yield from _STATEMENTS


def install_domain_constraints(engine: Any) -> None:
    "在目标 PostgreSQL schema 安装正式约束"
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        for statement in domain_constraint_statements():
            connection.execute(text(statement))
