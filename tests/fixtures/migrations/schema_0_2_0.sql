-- 0.2.0 ORM schema snapshot from 6e1883ee9b29e4bd930d9c87e091ab3f3da3f64f

-- Test fixture only; dynamic paragraph_embeddings excluded as in production initialization


CREATE TABLE novels (
	novel_id VARCHAR(8) NOT NULL,
	filename VARCHAR(500),
	file_path TEXT,
	title VARCHAR(500),
	author VARCHAR(255),
	file_size INTEGER,
	upload_time TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (novel_id)
)

;


CREATE TABLE analysis_runs (
	run_id VARCHAR(36) NOT NULL,
	novel_id VARCHAR(255) NOT NULL,
	source_path TEXT,
	title VARCHAR(500),
	author VARCHAR(255),
	status VARCHAR(50) NOT NULL,
	progress FLOAT NOT NULL,
	stage VARCHAR(255),
	sub_stage VARCHAR(255),
	current INTEGER NOT NULL,
	total INTEGER NOT NULL,
	message TEXT,
	error TEXT,
	task_kind VARCHAR(50) NOT NULL,
	request_payload TEXT,
	cancel_requested BOOLEAN NOT NULL,
	cancellation_epoch INTEGER NOT NULL,
	annotation_cutoff_hash VARCHAR(64),
	worker_id VARCHAR(255),
	heartbeat_at TIMESTAMP WITHOUT TIME ZONE,
	started_at TIMESTAMP WITHOUT TIME ZONE,
	completed_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (run_id),
	CONSTRAINT analysis_runs_novel_id_fkey FOREIGN KEY(novel_id) REFERENCES novels (novel_id) ON DELETE RESTRICT
)

;

CREATE INDEX idx_analysis_runs_novel ON analysis_runs (novel_id);

CREATE INDEX idx_analysis_runs_status ON analysis_runs (status);


CREATE TABLE agent_invocations (
	id SERIAL NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	task_type VARCHAR(20) NOT NULL,
	chapter_id INTEGER,
	attempt_number INTEGER NOT NULL,
	model_name VARCHAR(100),
	model_provider VARCHAR(20),
	status VARCHAR(20) NOT NULL,
	final_error TEXT,
	started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_agent_invocations_run_task ON agent_invocations (run_id, task_type);

CREATE INDEX ix_agent_invocations_run_id ON agent_invocations (run_id);


CREATE TABLE analysis_cutoffs (
	cutoff_hash VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	round_kind VARCHAR(20) NOT NULL,
	round_number INTEGER NOT NULL,
	formal_manifest_hash VARCHAR(64) NOT NULL,
	command_manifest_hash VARCHAR(64) NOT NULL,
	case_manifest_hash VARCHAR(64) NOT NULL,
	manifest JSONB NOT NULL,
	cancellation_epoch INTEGER NOT NULL,
	state VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	released_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (cutoff_hash),
	CONSTRAINT uq_analysis_cutoff_round UNIQUE (run_id, round_kind, round_number),
	CONSTRAINT ck_cutoff_state CHECK (state IN ('sealing', 'projecting', 'released', 'failed')),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_analysis_cutoff_latest ON analysis_cutoffs (run_id, state, released_at);


CREATE TABLE chapter_annotations (
	annotation_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	payload JSONB NOT NULL,
	formal_work_id VARCHAR(64),
	payload_hash VARCHAR(64),
	source_manifest_hash VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (annotation_id),
	CONSTRAINT uq_chapter_annotations_run_chapter UNIQUE (run_id, chapter_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	UNIQUE (formal_work_id)
)

;

CREATE INDEX idx_chapter_annotations_run_chapter ON chapter_annotations (run_id, chapter_id);


CREATE TABLE chapters (
	chapter_id INTEGER NOT NULL,
	sequence INTEGER NOT NULL,
	title TEXT NOT NULL,
	display_title TEXT NOT NULL,
	display_index_label VARCHAR(64),
	level VARCHAR(20) NOT NULL,
	start_pos INTEGER NOT NULL,
	end_pos INTEGER NOT NULL,
	text TEXT,
	char_offset INTEGER,
	char_end_offset INTEGER,
	run_id VARCHAR(36) NOT NULL,
	PRIMARY KEY (chapter_id, run_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_chapters_run_id ON chapters (run_id);

CREATE INDEX idx_chapters_run_text_trgm ON chapters USING gin (lower(text) gin_trgm_ops);


CREATE TABLE cloud_analysis (
	id SERIAL NOT NULL,
	novel_id VARCHAR(255),
	foreshadow_expectation FLOAT,
	arc_scores TEXT,
	genre_labels TEXT,
	style_labels TEXT,
	topic_labels TEXT,
	diagnosis TEXT,
	value_logic_type VARCHAR(50),
	value_logic_reason TEXT,
	power_stance_score INTEGER,
	power_stance_reason TEXT,
	common_people_dignity INTEGER,
	dignity_reason TEXT,
	cultural_depth_score INTEGER,
	cultural_depth_reason TEXT,
	narrative_arc_type VARCHAR(50),
	focus_structure VARCHAR(20),
	focus_characters TEXT,
	main_characters TEXT,
	core_cast TEXT,
	theme_color VARCHAR(20),
	run_id VARCHAR(36),
	PRIMARY KEY (id),
	CONSTRAINT cloud_analysis_novel_id_fkey FOREIGN KEY(novel_id) REFERENCES novels (novel_id) ON DELETE RESTRICT,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_cloud_analysis_novel_id ON cloud_analysis (novel_id);

CREATE INDEX idx_cloud_analysis_run_id ON cloud_analysis (run_id);


CREATE TABLE event_outbox (
	event_id VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER,
	cutoff_hash VARCHAR(64),
	stream_id BIGINT GENERATED BY DEFAULT AS IDENTITY,
	event_type VARCHAR(60) NOT NULL,
	payload JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (event_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	UNIQUE (stream_id)
)

;

CREATE INDEX idx_event_outbox_pending ON event_outbox (published_at, created_at);

CREATE INDEX idx_event_outbox_stream ON event_outbox (run_id, stream_id);


CREATE TABLE global_context (
	novel_id VARCHAR(255) NOT NULL,
	novel_title VARCHAR(500),
	core_characters TEXT,
	world_setting TEXT,
	updated_at VARCHAR(50),
	run_id VARCHAR(36),
	PRIMARY KEY (novel_id),
	CONSTRAINT global_context_novel_id_fkey FOREIGN KEY(novel_id) REFERENCES novels (novel_id) ON DELETE RESTRICT,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_global_context_run_id ON global_context (run_id);


CREATE TABLE global_stats (
	stat_name VARCHAR(255) NOT NULL,
	stat_value FLOAT,
	run_id VARCHAR(36) NOT NULL,
	PRIMARY KEY (stat_name, run_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;


CREATE TABLE graph_entities (
	entity_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	canonical_name VARCHAR(255) NOT NULL,
	entity_type VARCHAR(50) NOT NULL,
	tags JSONB NOT NULL,
	attributes JSONB NOT NULL,
	first_seen_chapter INTEGER NOT NULL,
	last_seen_chapter INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (entity_id),
	CONSTRAINT ck_graph_entities_type CHECK (entity_type IN ('character', 'location', 'item', 'organization')),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_graph_entities_run_canonical ON graph_entities (run_id, canonical_name);

CREATE INDEX idx_graph_entities_run_last_seen ON graph_entities (run_id, last_seen_chapter);

CREATE INDEX idx_graph_entities_run_type ON graph_entities (run_id, entity_type);


CREATE TABLE partition_heads (
	run_id VARCHAR(36) NOT NULL,
	partition_key VARCHAR(128) NOT NULL,
	head_epoch INTEGER NOT NULL,
	state_hash VARCHAR(64) NOT NULL,
	projection_hash VARCHAR(64) NOT NULL,
	projection JSONB NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, partition_key),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;


CREATE TABLE source_manifests (
	source_manifest_hash VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_hashes JSONB NOT NULL,
	paragraph_hashes JSONB NOT NULL,
	PRIMARY KEY (source_manifest_hash),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;


CREATE TABLE topic_model_runs (
	run_id VARCHAR(36) NOT NULL,
	model_key VARCHAR(255) NOT NULL,
	library_version VARCHAR(64) NOT NULL,
	pipeline_version VARCHAR(64) NOT NULL,
	num_topics INTEGER NOT NULL,
	parameters JSONB NOT NULL,
	dictionary_size INTEGER NOT NULL,
	training_document_count INTEGER NOT NULL,
	inference_paragraph_count INTEGER NOT NULL,
	artifact_key TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;


CREATE TABLE word2vec_model_runs (
	run_id VARCHAR(36) NOT NULL,
	embedding_dimension INTEGER NOT NULL,
	vocabulary_size INTEGER NOT NULL,
	parameters JSONB NOT NULL,
	source_uri TEXT,
	license_name VARCHAR(255),
	training_document_count INTEGER,
	training_token_count INTEGER,
	artifact_key TEXT NOT NULL,
	artifact_scope VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;


CREATE TABLE work_items (
	work_id VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	work_kind VARCHAR(30) NOT NULL,
	logical_key VARCHAR(128) NOT NULL,
	payload JSONB NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	cutoff_hash VARCHAR(64) NOT NULL,
	state VARCHAR(20) NOT NULL,
	priority INTEGER NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE NOT NULL,
	attempt_count INTEGER NOT NULL,
	attempt_epoch INTEGER NOT NULL,
	lease_owner VARCHAR(128),
	lease_hash VARCHAR(64),
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	cancellation_epoch INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (work_id),
	CONSTRAINT uq_work_identity UNIQUE (run_id, work_kind, logical_key, payload_hash, cutoff_hash),
	CONSTRAINT ck_work_kind CHECK (work_kind IN ('formal_current', 'continuity')),
	CONSTRAINT ck_work_state CHECK (state IN ('waiting', 'running', 'succeeded', 'failed')),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_work_claim ON work_items (state, available_at, priority);

CREATE INDEX idx_work_run_state ON work_items (run_id, state);


CREATE TABLE agent_turns (
	id SERIAL NOT NULL,
	invocation_id INTEGER NOT NULL,
	turn_index INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	error TEXT,
	raw_response JSONB NOT NULL,
	context_summary JSONB NOT NULL,
	request_messages JSONB DEFAULT '[]'::jsonb NOT NULL,
	timing_notes JSONB DEFAULT '[]'::jsonb NOT NULL,
	ttft_ms INTEGER,
	first_visible_ms INTEGER,
	reasoning_ms INTEGER,
	model_ms INTEGER,
	tool_wall_ms INTEGER,
	turn_ms INTEGER,
	started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(invocation_id) REFERENCES agent_invocations (id) ON DELETE CASCADE
)

;

CREATE INDEX idx_agent_turns_invocation_index ON agent_turns (invocation_id, turn_index);

CREATE INDEX ix_agent_turns_invocation_id ON agent_turns (invocation_id);


CREATE TABLE chapter_summaries (
	chapter_id INTEGER NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	summary TEXT,
	created_at VARCHAR(50),
	PRIMARY KEY (chapter_id, run_id),
	FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_chapter_summaries_run_id ON chapter_summaries (run_id);


CREATE TABLE continuity_cases (
	case_id VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	case_key VARCHAR(64) NOT NULL,
	issue_kind VARCHAR(60) NOT NULL,
	description TEXT NOT NULL,
	search_keys JSONB NOT NULL,
	target_ref JSONB NOT NULL,
	source_evidence JSONB NOT NULL,
	originating_annotation_id VARCHAR(36),
	originating_chapter_id INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (case_id),
	CONSTRAINT uq_continuity_cases_key UNIQUE (run_id, case_key),
	CONSTRAINT ck_continuity_case_evidence CHECK (jsonb_array_length(source_evidence) > 0),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(originating_annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE
)

;


CREATE TABLE cutoff_partitions (
	cutoff_hash VARCHAR(64) NOT NULL,
	partition_key VARCHAR(128) NOT NULL,
	projection JSONB NOT NULL,
	projection_hash VARCHAR(64) NOT NULL,
	PRIMARY KEY (cutoff_hash, partition_key),
	FOREIGN KEY(cutoff_hash) REFERENCES analysis_cutoffs (cutoff_hash) ON DELETE CASCADE
)

;


CREATE TABLE dialogue_records (
	dialogue_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	candidate_key VARCHAR(100) NOT NULL,
	content TEXT NOT NULL,
	start INTEGER NOT NULL,
	"end" INTEGER NOT NULL,
	speaker VARCHAR(36),
	tone VARCHAR(255),
	is_inner_monologue BOOLEAN NOT NULL,
	confidence VARCHAR(20) NOT NULL,
	event_id VARCHAR(36),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (dialogue_id),
	CONSTRAINT dialogue_records_chapter_run_fkey FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT uq_dialogue_records_run_candidate UNIQUE (run_id, candidate_key),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(speaker) REFERENCES graph_entities (entity_id) ON DELETE SET NULL
)

;

CREATE INDEX idx_dialogue_records_run_chapter ON dialogue_records (run_id, chapter_id);


CREATE TABLE entity_states (
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	entity_id VARCHAR(36) NOT NULL,
	state JSONB NOT NULL,
	changes JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, chapter_id, entity_id),
	CONSTRAINT entity_states_chapter_run_fkey FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT ck_entity_states_changes_non_empty CHECK (jsonb_array_length(changes) > 0),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(entity_id) REFERENCES graph_entities (entity_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_entity_states_run_entity ON entity_states (run_id, entity_id, chapter_id);


CREATE TABLE event_nodes (
	event_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	chapter_order INTEGER NOT NULL,
	description VARCHAR NOT NULL,
	participants JSONB NOT NULL,
	anchor_paragraph_ids JSONB NOT NULL,
	char_start INTEGER NOT NULL,
	char_end INTEGER NOT NULL,
	evidence JSONB NOT NULL,
	causal_event_refs JSONB NOT NULL,
	tree_id VARCHAR(255) NOT NULL,
	cause_role VARCHAR(16) NOT NULL,
	is_foreshadowing_root BOOLEAN NOT NULL,
	foreshadowing_status VARCHAR(20),
	payoff_likelihood VARCHAR(20),
	strength VARCHAR(20),
	annotation_id VARCHAR(36) NOT NULL,
	source_kind VARCHAR(30) NOT NULL,
	payload_path VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (event_id),
	CONSTRAINT event_nodes_chapter_run_fkey FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT ck_event_nodes_char_order CHECK (char_end > char_start),
	CONSTRAINT ck_event_nodes_cause_role CHECK (cause_role IN ('root', 'main', 'secondary')),
	CONSTRAINT ck_event_nodes_foreshadow_status CHECK ((is_foreshadowing_root = FALSE) OR (foreshadowing_status IN ('open', 'reinforced', 'likely_paid_off'))),
	CONSTRAINT uq_event_nodes_chapter_payload_path UNIQUE (run_id, chapter_id, payload_path),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_event_nodes_run_chapter ON event_nodes (run_id, chapter_id);

CREATE INDEX idx_event_nodes_run_chapter_order ON event_nodes (run_id, chapter_order);

CREATE INDEX idx_event_nodes_run_foreshadow_root ON event_nodes (run_id, is_foreshadowing_root);

CREATE INDEX idx_event_nodes_run_tree ON event_nodes (run_id, tree_id);


CREATE TABLE formal_artifacts (
	annotation_id VARCHAR(36) NOT NULL,
	result JSONB NOT NULL,
	materialized BOOLEAN NOT NULL,
	PRIMARY KEY (annotation_id),
	FOREIGN KEY(annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE
)

;


CREATE TABLE graph_relations (
	relation_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	from_entity_id VARCHAR(36) NOT NULL,
	to_entity_id VARCHAR(36) NOT NULL,
	directionality VARCHAR(20) NOT NULL,
	relation_semantics VARCHAR(30) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (relation_id),
	CONSTRAINT ck_graph_relations_directionality CHECK (directionality IN ('directed', 'bidirectional')),
	CONSTRAINT ck_graph_relations_semantics CHECK (relation_semantics IN ('ordinary', 'same_character')),
	CONSTRAINT ck_graph_relations_distinct_endpoints CHECK (from_entity_id <> to_entity_id),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(from_entity_id) REFERENCES graph_entities (entity_id) ON DELETE CASCADE,
	FOREIGN KEY(to_entity_id) REFERENCES graph_entities (entity_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_graph_relations_run_from ON graph_relations (run_id, from_entity_id);

CREATE INDEX idx_graph_relations_run_to ON graph_relations (run_id, to_entity_id);


CREATE TABLE paragraphs (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	chapter_id INTEGER NOT NULL,
	paragraph_index INTEGER NOT NULL,
	source_paragraph_index INTEGER NOT NULL,
	fragment_index INTEGER NOT NULL,
	local_start_char INTEGER NOT NULL,
	local_end_char INTEGER NOT NULL,
	global_start_char INTEGER NOT NULL,
	global_end_char INTEGER NOT NULL,
	char_count INTEGER NOT NULL,
	token_count INTEGER NOT NULL,
	text TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, paragraph_id),
	CONSTRAINT uq_paragraphs_run_chapter_index UNIQUE (run_id, chapter_id, paragraph_index),
	FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	CONSTRAINT ck_paragraphs_local_order CHECK (local_start_char < local_end_char),
	CONSTRAINT ck_paragraphs_global_order CHECK (global_start_char < global_end_char),
	CONSTRAINT ck_paragraphs_char_count_global CHECK (char_count = global_end_char - global_start_char),
	CONSTRAINT ck_paragraphs_char_count_text CHECK (char_count = length(text))
)

;

CREATE INDEX idx_paragraphs_run_chapter_index ON paragraphs (run_id, chapter_id, paragraph_index);

CREATE INDEX idx_paragraphs_run_chapter_local_start ON paragraphs (run_id, chapter_id, local_start_char);

CREATE INDEX idx_paragraphs_run_global_start ON paragraphs (run_id, global_start_char);

CREATE INDEX idx_paragraphs_text_trgm ON paragraphs USING gin (lower(text) gin_trgm_ops);


CREATE TABLE semantic_commands (
	command_id VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	origin_annotation_id VARCHAR(36),
	origin_chapter_id INTEGER,
	origin_chapter_sequence INTEGER,
	command_path VARCHAR(255) NOT NULL,
	command_kind VARCHAR(60) NOT NULL,
	partition_key VARCHAR(128) NOT NULL,
	effective_document_position JSONB NOT NULL,
	explicit_story_time JSONB,
	payload JSONB NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	evidence_ids JSONB NOT NULL,
	independence_keys JSONB NOT NULL,
	parent_command_id VARCHAR(64),
	precondition_epoch INTEGER,
	precondition_hash VARCHAR(64),
	author_work_id VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (command_id),
	CONSTRAINT uq_semantic_command_annotation_path UNIQUE (origin_annotation_id, command_path),
	CONSTRAINT ck_semantic_command_evidence CHECK (jsonb_array_length(evidence_ids) > 0),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(origin_annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_semantic_command_partition ON semantic_commands (run_id, partition_key, created_at);


CREATE TABLE stage_summaries (
	stage_id SERIAL NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	start_chapter_id INTEGER NOT NULL,
	end_chapter_id INTEGER NOT NULL,
	summary TEXT,
	created_at VARCHAR(50),
	PRIMARY KEY (stage_id),
	FOREIGN KEY(start_chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	FOREIGN KEY(end_chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_stage_summaries_run_id ON stage_summaries (run_id);


CREATE TABLE agent_tool_calls (
	id SERIAL NOT NULL,
	turn_id INTEGER NOT NULL,
	tool_name VARCHAR(100) NOT NULL,
	call_index INTEGER NOT NULL,
	request_args JSONB NOT NULL,
	raw_args TEXT,
	response JSONB,
	receipt JSONB,
	status VARCHAR(20) NOT NULL,
	error TEXT,
	tool_duration_ms INTEGER,
	started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(turn_id) REFERENCES agent_turns (id) ON DELETE CASCADE
)

;

CREATE INDEX idx_agent_tool_calls_turn ON agent_tool_calls (turn_id, call_index);

CREATE INDEX ix_agent_tool_calls_turn_id ON agent_tool_calls (turn_id);


CREATE TABLE case_claims (
	case_id VARCHAR(64) NOT NULL,
	claim_epoch INTEGER NOT NULL,
	lease_hash VARCHAR(64) NOT NULL,
	work_id VARCHAR(64) NOT NULL,
	status VARCHAR(20) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	consumed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (case_id, claim_epoch),
	CONSTRAINT ck_case_claim_status CHECK (status IN ('active', 'consumed', 'released', 'expired')),
	FOREIGN KEY(case_id) REFERENCES continuity_cases (case_id) ON DELETE CASCADE
)

;


CREATE TABLE case_heads (
	case_id VARCHAR(64) NOT NULL,
	state VARCHAR(20) NOT NULL,
	head_epoch INTEGER NOT NULL,
	state_hash VARCHAR(64) NOT NULL,
	claim_epoch INTEGER NOT NULL,
	active_lease_hash VARCHAR(64),
	active_lease_expires_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (case_id),
	CONSTRAINT ck_case_head_state CHECK (state IN ('pending', 'resolved', 'deferred', 'contested')),
	FOREIGN KEY(case_id) REFERENCES continuity_cases (case_id) ON DELETE CASCADE
)

;


CREATE TABLE command_outcomes (
	command_id VARCHAR(64) NOT NULL,
	state VARCHAR(30) NOT NULL,
	reason_code VARCHAR(80),
	partition_key VARCHAR(128) NOT NULL,
	head_epoch INTEGER,
	state_hash VARCHAR(64),
	resolved_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (command_id),
	CONSTRAINT ck_command_outcome_state CHECK (state IN ('accepted', 'conflict', 'pending_dependency', 'rejected')),
	FOREIGN KEY(command_id) REFERENCES semantic_commands (command_id) ON DELETE CASCADE
)

;


CREATE TABLE event_edges (
	edge_id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	edge_type VARCHAR(20) NOT NULL,
	source_event_id VARCHAR(36) NOT NULL,
	target_event_id VARCHAR(36) NOT NULL,
	source_chapter_id INTEGER NOT NULL,
	target_chapter_id INTEGER NOT NULL,
	is_active BOOLEAN NOT NULL,
	evidence JSONB NOT NULL,
	annotation_id VARCHAR(36) NOT NULL,
	payload_path VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expired_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (edge_id),
	CONSTRAINT event_edges_source_chapter_run_fkey FOREIGN KEY(source_chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT event_edges_target_chapter_run_fkey FOREIGN KEY(target_chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT ck_event_edges_type CHECK (edge_type IN ('causal', 'foreshadowing')),
	CONSTRAINT uq_event_edges_endpoints UNIQUE (run_id, source_event_id, target_event_id),
	CONSTRAINT uq_event_edges_chapter_payload_path UNIQUE (run_id, source_chapter_id, payload_path),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(source_event_id) REFERENCES event_nodes (event_id) ON DELETE CASCADE,
	FOREIGN KEY(target_event_id) REFERENCES event_nodes (event_id) ON DELETE CASCADE,
	FOREIGN KEY(annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_event_edges_run_source ON event_edges (run_id, source_event_id);

CREATE INDEX idx_event_edges_run_target ON event_edges (run_id, target_event_id);

CREATE INDEX idx_event_edges_run_type ON event_edges (run_id, edge_type);


CREATE TABLE graph_facts (
	graph_fact_id SERIAL NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	fact_id VARCHAR(128) NOT NULL,
	fact_type VARCHAR(100) NOT NULL,
	subject_entity_id VARCHAR(36),
	predicate VARCHAR(255) NOT NULL,
	object JSONB,
	value JSONB,
	participants JSONB NOT NULL,
	scope VARCHAR(255) NOT NULL,
	story_time JSONB,
	assertion VARCHAR(20) NOT NULL,
	confidence VARCHAR(20) NOT NULL,
	content JSONB NOT NULL,
	effective_chapter_id INTEGER NOT NULL,
	source_kind VARCHAR(30) NOT NULL,
	annotation_id VARCHAR(36) NOT NULL,
	payload_path VARCHAR(255) NOT NULL,
	event_id VARCHAR(36),
	evidence JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (graph_fact_id),
	CONSTRAINT graph_facts_chapter_run_fkey FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT graph_facts_effective_chapter_run_fkey FOREIGN KEY(effective_chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT ck_graph_facts_evidence_non_empty CHECK (jsonb_array_length(evidence) > 0),
	CONSTRAINT uq_graph_facts_run_chapter_fact UNIQUE (run_id, chapter_id, fact_id),
	CONSTRAINT uq_graph_facts_chapter_payload_path UNIQUE (run_id, chapter_id, payload_path),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(subject_entity_id) REFERENCES graph_entities (entity_id) ON DELETE RESTRICT,
	FOREIGN KEY(annotation_id) REFERENCES chapter_annotations (annotation_id) ON DELETE CASCADE,
	FOREIGN KEY(event_id) REFERENCES event_nodes (event_id) ON DELETE RESTRICT
)

;

CREATE INDEX idx_graph_facts_run_chapter ON graph_facts (run_id, chapter_id);

CREATE INDEX idx_graph_facts_run_event ON graph_facts (run_id, event_id);

CREATE INDEX idx_graph_facts_run_subject_predicate ON graph_facts (run_id, subject_entity_id, predicate);


CREATE TABLE paragraph_curves (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	pos_density FLOAT,
	neg_density FLOAT,
	net_density FLOAT,
	smoothed_net_density FLOAT,
	surface_tension FLOAT,
	smoothed_surface_tension FLOAT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, paragraph_id),
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_paragraph_curves_run_paragraph ON paragraph_curves (run_id, paragraph_id);


CREATE TABLE paragraph_linguistic_features (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	ltp_token_count INTEGER NOT NULL,
	tokens JSONB NOT NULL,
	word_length_counts JSONB NOT NULL,
	pos_counts JSONB NOT NULL,
	sentence_count INTEGER NOT NULL,
	sentence_pattern_counts JSONB NOT NULL,
	dependency_arcs JSONB NOT NULL,
	dependency_node_count INTEGER NOT NULL,
	dependency_root_count INTEGER NOT NULL,
	dependency_depth_sum INTEGER NOT NULL,
	dependency_depth_max INTEGER NOT NULL,
	dependency_relation_counts JSONB NOT NULL,
	sdp_arcs JSONB NOT NULL,
	emotion_events JSONB NOT NULL,
	emotion_event_count INTEGER NOT NULL,
	emotion_pos_event_count INTEGER NOT NULL,
	emotion_neg_event_count INTEGER NOT NULL,
	lexicon_pos_count FLOAT NOT NULL,
	lexicon_neg_count FLOAT NOT NULL,
	mneg_pos_count FLOAT NOT NULL,
	mneg_neg_count FLOAT NOT NULL,
	boundary_pos_score_sum FLOAT,
	boundary_neg_score_sum FLOAT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, paragraph_id),
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_linguistic_features_run_paragraph ON paragraph_linguistic_features (run_id, paragraph_id);


CREATE TABLE paragraph_metrics (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	token_count INTEGER NOT NULL,
	char_count INTEGER NOT NULL,
	sentence_count INTEGER NOT NULL,
	sentence_char_sum FLOAT NOT NULL,
	sentence_char_sum_sq FLOAT NOT NULL,
	positive_weight_sum FLOAT NOT NULL,
	negative_weight_sum FLOAT NOT NULL,
	fight_weight_sum FLOAT NOT NULL,
	exclaim_count INTEGER NOT NULL,
	question_count INTEGER NOT NULL,
	pause_count INTEGER NOT NULL,
	dialogue_char_count INTEGER NOT NULL,
	sensory_hit_count INTEGER NOT NULL,
	imagery_hit_count INTEGER NOT NULL,
	metaphor_sentence_count INTEGER NOT NULL,
	body_reaction_hit_count INTEGER NOT NULL,
	function_word_counts JSONB NOT NULL,
	semantic_category_counts JSONB NOT NULL,
	surface_tension_z FLOAT,
	surface_tension FLOAT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, paragraph_id),
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_paragraph_metrics_run_paragraph ON paragraph_metrics (run_id, paragraph_id);


CREATE TABLE paragraph_topic_inference (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	source_token_count INTEGER NOT NULL,
	inference_token_count INTEGER NOT NULL,
	inference_status VARCHAR(30) NOT NULL,
	unavailable_reason TEXT,
	distribution_sum FLOAT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, paragraph_id),
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id) REFERENCES topic_model_runs (run_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_topic_inference_status_paragraph ON paragraph_topic_inference (run_id, inference_status, paragraph_id);


CREATE TABLE relation_states (
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	relation_id VARCHAR(36) NOT NULL,
	relation_type VARCHAR(100) NOT NULL,
	attributes JSONB NOT NULL,
	is_active BOOLEAN NOT NULL,
	changes JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, chapter_id, relation_id),
	CONSTRAINT relation_states_chapter_run_fkey FOREIGN KEY(chapter_id, run_id) REFERENCES chapters (chapter_id, run_id) ON DELETE CASCADE,
	CONSTRAINT ck_relation_states_changes_non_empty CHECK (jsonb_array_length(changes) > 0),
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(relation_id) REFERENCES graph_relations (relation_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_relation_states_run_active ON relation_states (run_id, is_active);

CREATE INDEX idx_relation_states_run_relation ON relation_states (run_id, relation_id, chapter_id);


CREATE TABLE text_evidence (
	evidence_id VARCHAR(64) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	chapter_id INTEGER NOT NULL,
	paragraph_id INTEGER NOT NULL,
	char_start INTEGER NOT NULL,
	char_end INTEGER NOT NULL,
	text_hash VARCHAR(64) NOT NULL,
	source_manifest_hash VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (evidence_id),
	CONSTRAINT text_evidence_paragraph_fkey FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	CONSTRAINT ck_text_evidence_span CHECK (char_start >= 0 AND char_end > char_start),
	CONSTRAINT uq_text_evidence_span UNIQUE (run_id, paragraph_id, char_start, char_end, source_manifest_hash)
)

;


CREATE TABLE token_usage (
	id SERIAL NOT NULL,
	novel_id VARCHAR(255) NOT NULL,
	chapter_id INTEGER,
	task_type VARCHAR(100) NOT NULL,
	call_type VARCHAR(50) NOT NULL,
	model VARCHAR(100) NOT NULL,
	prompt_tokens INTEGER NOT NULL,
	completion_tokens INTEGER,
	total_tokens INTEGER NOT NULL,
	cache_read_tokens INTEGER,
	reasoning_tokens INTEGER,
	cost FLOAT,
	accounting_source VARCHAR(20) DEFAULT 'reported' NOT NULL,
	created_at VARCHAR(50) NOT NULL,
	run_id VARCHAR(36),
	agent_turn_id INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT token_usage_novel_id_fkey FOREIGN KEY(novel_id) REFERENCES novels (novel_id) ON DELETE RESTRICT,
	FOREIGN KEY(run_id) REFERENCES analysis_runs (run_id) ON DELETE CASCADE,
	UNIQUE (agent_turn_id),
	FOREIGN KEY(agent_turn_id) REFERENCES agent_turns (id) ON DELETE CASCADE
)

;

CREATE INDEX idx_token_usage_agent_turn ON token_usage (agent_turn_id);

CREATE INDEX idx_token_usage_novel_id ON token_usage (novel_id);

CREATE INDEX idx_token_usage_run_id ON token_usage (run_id);

CREATE INDEX idx_token_usage_task_type ON token_usage (novel_id, task_type);

CREATE INDEX ix_token_usage_task_type ON token_usage (task_type);


CREATE TABLE paragraph_entities (
	id BIGSERIAL NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	surface_text TEXT NOT NULL,
	raw_entity_type VARCHAR(50) NOT NULL,
	normalized_entity_type VARCHAR(50),
	local_start_char INTEGER NOT NULL,
	local_end_char INTEGER NOT NULL,
	confidence FLOAT,
	source_kind VARCHAR(30) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraph_linguistic_features (run_id, paragraph_id) ON DELETE CASCADE,
	CONSTRAINT uq_entities_run_para_span_type_text UNIQUE (run_id, paragraph_id, local_start_char, local_end_char, raw_entity_type, surface_text)
)

;

CREATE INDEX idx_entities_run_normalized ON paragraph_entities (run_id, normalized_entity_type);

CREATE INDEX idx_entities_run_para_start ON paragraph_entities (run_id, paragraph_id, local_start_char);


CREATE TABLE paragraph_phrase_hits (
	id BIGSERIAL NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	surface_text TEXT NOT NULL,
	phrase_type VARCHAR(50),
	local_start_char INTEGER NOT NULL,
	local_end_char INTEGER NOT NULL,
	match_kind VARCHAR(30) NOT NULL,
	lexicon_key VARCHAR(255),
	is_metric_hit BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraph_linguistic_features (run_id, paragraph_id) ON DELETE CASCADE,
	CONSTRAINT uq_phrase_hits_run_para_span_kind_text UNIQUE (run_id, paragraph_id, local_start_char, local_end_char, match_kind, surface_text)
)

;

CREATE INDEX idx_phrase_hits_run_kind_metric ON paragraph_phrase_hits (run_id, match_kind, is_metric_hit);

CREATE INDEX idx_phrase_hits_run_para_start ON paragraph_phrase_hits (run_id, paragraph_id, local_start_char);


CREATE TABLE paragraph_pos_embeddings (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	pos_group VARCHAR(50) NOT NULL,
	embedding_vector VECTOR,
	source_token_count INTEGER NOT NULL,
	in_vocabulary_token_count INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (run_id, paragraph_id, pos_group),
	FOREIGN KEY(run_id) REFERENCES word2vec_model_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraph_linguistic_features (run_id, paragraph_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_pos_embeddings_run_pos_para ON paragraph_pos_embeddings (run_id, pos_group, paragraph_id);


CREATE TABLE paragraph_topics (
	run_id VARCHAR(36) NOT NULL,
	paragraph_id INTEGER NOT NULL,
	topic_id INTEGER NOT NULL,
	topic_weight FLOAT NOT NULL,
	PRIMARY KEY (run_id, paragraph_id, topic_id),
	FOREIGN KEY(run_id) REFERENCES topic_model_runs (run_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraph_topic_inference (run_id, paragraph_id) ON DELETE CASCADE,
	FOREIGN KEY(run_id, paragraph_id) REFERENCES paragraphs (run_id, paragraph_id) ON DELETE CASCADE
)

;

CREATE INDEX idx_paragraph_topics_topic_paragraph ON paragraph_topics (run_id, topic_id, paragraph_id);
