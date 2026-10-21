"普通持久化记录快照"

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AgentLoopRecord:
    id: str
    model: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    message_key: str | None
    agent_id: str | None
    turn_index: int | None
    standalone_run_id: str | None
    standalone_chapter_id: int | None
    standalone_task_type: str | None
    standalone_call_type: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cache_read_tokens: int | None
    reasoning_tokens: int | None
    accounting_source: str | None
    reported_total_tokens: int | None
    cost: float | None
    ttft_ms: int | None
    first_visible_ms: int | None
    reasoning_ms: int | None
    model_ms: int | None
    tool_wall_ms: int | None
    request_messages_bytes: bytes | None
    raw_response_bytes: bytes | None
    context_observed_bytes: bytes | None
    timing_notes_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    id: str
    agentloop_id: str
    tool_name: str
    call_index: int
    error: str | None
    started_at: datetime
    tool_duration_ms: int | None
    message_key: str | None
    raw_args_bytes: bytes | None
    executed_args_bytes: bytes | None
    response_observed_bytes: bytes | None
    receipt_observed_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class EventOutboxRecord:
    message_key: str
    event_id: str
    stream_id: int
    run_id: str
    chapter_id: int | None
    event_type: str
    emitted_bytes: bytes
    created_at: datetime
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class CaseRecord:
    id: str
    run_id: str
    type: str
    description: str
    status: str
    producer_agent_id: str | None
    promised_agent_id: str | None


@dataclass(frozen=True, slots=True)
class ChapterRecord:
    id: str
    run_id: str
    chapter_id: int
    sequence: int
    title: str
    display_title: str
    display_index_label: str | None
    level: str
    start_pos: int
    end_pos: int
    text: str | None
    char_offset: int | None


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    novelid: str
    taskid: str
    status: str
    lda_completed: bool
    w2v_completed: bool


@dataclass(frozen=True, slots=True)
class GlobalStatsRecord:
    run_id: str
    avg_mtld: float | None
    avg_ttr: float | None
    avg_sent_len: float | None
    emotion_avg: float | None
    lexicon_zero_hit_share: float | None
    emotion_std: float | None
    emotion_max: float | None
    emotion_min: float | None
    emotion_peak_chapter_id: int | None
    emotion_min_chapter_id: int | None
    rhythm_avg: float | None
    rhythm_std: float | None
    rhythm_max: float | None
    rhythm_min: float | None
    rhythm_peak_chapter_id: int | None
    rhythm_min_chapter_id: int | None


@dataclass(frozen=True, slots=True)
class DialogueRecordRecord:
    dialogue_id: str
    run_id: str
    chapter_id: int
    creation_agent_id: str
    candidate_key: str
    start_char: int
    end_char: int
    current_attribution_agent_id: str | None
    speaker_entity_id: str | None
    tone: str | None
    is_inner_monologue: bool
    related_complete_event_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EventParticipantRecord:
    participant_id: str
    event_id: str
    participant_ordinal: int
    entity_id: str
    role: str
    narrative_role: str | None
    action: str | None
    emotion: int | None


@dataclass(frozen=True, slots=True)
class CompleteEventRecord:
    event_id: str
    producer_agent_id: str
    local_key: str
    annotation_record_id: str | None
    from_chapter_id: int
    to_chapter_id: int
    reason: str | None
    is_foreshadowing_root: bool
    payoff_likelihood: str | None
    created_at: datetime
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    progress: str | None


@dataclass(frozen=True, slots=True)
class GraphEntityRecord:
    entity_id: str
    run_id: str
    canonical_name: str
    entity_type: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GraphRelationRecord:
    relation_id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GraphFactRecord:
    graph_fact_id: str
    direct_producer_agent_id: str | None
    operation_order: int | None
    business_call_id: str | None
    effective_chapter_id: int | None
    entity_id: str | None
    relation_id: str | None
    participant_id: str | None
    event_id: str | None
    description_action: str | None
    description_value: str | None
    representative_action: str | None
    representative_value: bool | None
    tags_submitted: bool | None
    relation_change_kind: str | None
    identity_kind: str | None
    reason: str | None
    plotline_subject_id: str | None
    plotline_subject_title: str | None
    plotline_description: str | None
    plotline_before: str | None
    plotline_after: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FactEntityTagRecord:
    id: str
    graph_fact_id: str
    tag_ordinal: int
    tag: str


@dataclass(frozen=True, slots=True)
class LinguisticSpanRecord:
    span_id: str
    run_id: str
    paragraph_id: int
    start_char: int
    end_char: int
    token_index: int | None
    raw_pos: str | None
    raw_entity_type: str | None
    phrase_match_kind: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LinguisticArcRecord:
    arc_id: str
    dependent_span_id: str
    head_span_id: str | None
    relation_code: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class NovelRecord:
    novel_id: str
    filename: str | None
    file_path: str | None
    title: str | None
    author: str | None
    file_size: int | None
    upload_time: datetime | None


@dataclass(frozen=True, slots=True)
class NarrativeLinkRecord:
    link_id: str
    producer_agent_id: str
    reason: str
    semantic_source_event_id: str | None
    semantic_target_event_id: str | None
    relation_type: str | None
    source_operation_local_key: str | None
    annotation_local_key: str | None
    created_at: datetime | None
    is_active: bool | None
    expired_at: datetime | None
    cause_role: str | None
    contained_child_id: str | None
    contained_parent_id: str | None
    member_event_id: str | None
    arc_group_id: str | None
    outcome_group_id: str | None
    arc_role: str | None


@dataclass(frozen=True, slots=True)
class NarrativeGroupRecord:
    group_id: str
    producer_agent_id: str
    title: str
    arc_kind: str | None
    arc_objective: str | None
    arc_role: str | None
    arc_reason: str | None
    parent_arc_id: str | None
    outcome_description: str | None


@dataclass(frozen=True, slots=True)
class OrganizationCheckRecord:
    check_id: str
    producer_agent_id: str
    reason: str
    reviewed_event_id: str | None
    source_event_id: str | None
    target_event_id: str | None
    snapshot_hash: str | None
    disposition: str | None


@dataclass(frozen=True, slots=True)
class EventForeshadowingActionRecord:
    action_id: str
    producer_agent_id: str
    source_operation_local_key: str
    operation_order: int
    action_type: str
    source_event_id: str
    target_event_id: str | None


@dataclass(frozen=True, slots=True)
class SourceEvidenceRecord:
    evidence_id: str
    ordinal: int
    paragraph_id: int
    start_char: int
    end_char: int
    related_complete_event_id: str | None
    graph_fact_id: str | None
    complete_event_id: str | None
    narrative_group_id: str | None
    narrative_link_id: str | None
    foreshadow_action_id: str | None
    check_id: str | None


@dataclass(frozen=True, slots=True)
class ParagraphRecord:
    id: str
    run_id: str
    paragraph_id: int
    chapter_id: int
    paragraph_index: int
    source_paragraph_index: int
    fragment_index: int
    local_start_char: int
    text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParagraphFeatureRecord:
    id: str
    run_id: str
    paragraph_id: int
    feature_code: str
    vector_value: list[float] | None
    scalar_value: float | None
    count_value: int | None
    in_vocabulary_token_count: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParagraphMetricRecord:
    id: str
    run_id: str
    paragraph_id: int
    token_count: int | None
    sentence_count: int | None
    sentence_char_sum: float | None
    sentence_char_sum_sq: float | None
    positive_weight_sum: float | None
    negative_weight_sum: float | None
    fight_weight_sum: float | None
    exclaim_count: int | None
    question_count: int | None
    pause_count: int | None
    dialogue_char_count: int | None
    sensory_hit_count: int | None
    imagery_hit_count: int | None
    metaphor_sentence_count: int | None
    body_reaction_hit_count: int | None
    metrics_created_at: datetime | None
    preprocess_observed_at: datetime | None
    linguistic_completed_at: datetime | None
    phrase_completed_at: datetime | None
    fw_之: int | None
    fw_其: int | None
    fw_者: int | None
    fw_也: int | None
    fw_所: int | None
    fw_以: int | None
    fw_而: int | None
    fw_与: int | None
    fw_则: int | None
    fw_乃: int | None
    fw_于: int | None
    fw_乎: int | None
    fw_矣: int | None
    fw_焉: int | None
    fw_哉: int | None
    fw_兮: int | None
    fw_尔: int | None
    fw_若: int | None
    fw_为: int | None
    fw_何: int | None
    semantic_combat: int | None
    semantic_body: int | None
    semantic_relation: int | None
    semantic_faction: int | None
    semantic_command: int | None
    semantic_action: int | None
    semantic_psychology: int | None
    semantic_measure: int | None
    semantic_emotion: int | None
    semantic_color: int | None
    boundary_pos_score_sum: float | None
    boundary_neg_score_sum: float | None
    inference_token_count: int | None
    inference_status: str | None
    inference_error_text: str | None
    inference_created_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParagraphTopicRecord:
    id: str
    run_id: str
    paragraph_id: int
    topic_id: int
    topic_weight: float


@dataclass(frozen=True, slots=True)
class AgentRecord:
    id: str
    run_id: str
    type: str
    status: str


@dataclass(frozen=True, slots=True)
class ChapterAnnotationRecord:
    record_id: str
    agent_id: str
    run_id: str
    chapter_id: int
    role: str
    consolidation_digest: str | None
    summary: str | None
    emotional_valence: int | None
    narrative_function: str | None
    pivot_moment: bool | None
    cliffhanger: bool | None
    created_at: datetime
    saved_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosisReportRecord:
    report_id: str
    agent_id: str
    diagnosis: str | None
    value_logic_type: str | None
    value_logic_reason: str | None
    power_stance_score: int | None
    power_stance_reason: str | None
    common_people_dignity: int | None
    dignity_reason: str | None
    cultural_depth_score: int | None
    cultural_depth_reason: str | None
    narrative_arc_type: str | None
    focus_structure: str | None
    theme_color: str | None
    content_snapshot: str | None
    structure_snapshot: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisAssessmentRecord:
    assessment_id: str
    record_id: str | None
    report_id: str | None
    paragraph_id: int | None
    emotion: int | None
    ordinal: int | None
    genre_label: str | None
    style_label: str | None
    topic_id: int | None
    topic_label: str | None
    scored_entity_id: str | None
    character_score: float | None
    cast_role: str | None
    cast_entity_id: str | None
