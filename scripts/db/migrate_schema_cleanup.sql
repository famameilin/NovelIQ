-- ============================================================
-- db-schema-cleanup 分支 DDL 变更脚本
-- 说明: 不兼容旧数据，直接删旧表 + 建新表 + 改列
-- ============================================================

BEGIN;

-- 1. 删除旧表（按外键依赖倒序）
DROP TABLE IF EXISTS entity_registry CASCADE;
DROP TABLE IF EXISTS entity_snapshots CASCADE;
DROP TABLE IF EXISTS entity_relations CASCADE;
DROP TABLE IF EXISTS entity_aliases CASCADE;
DROP TABLE IF EXISTS entities CASCADE;
DROP TABLE IF EXISTS graph_storage CASCADE;
DROP TABLE IF EXISTS chunk_embeddings CASCADE;
DROP TABLE IF EXISTS chunk_culture CASCADE;
DROP TABLE IF EXISTS emotion_curve CASCADE;
DROP TABLE IF EXISTS rhythm_curve CASCADE;

-- 2. chunk_style 新增 imagery_lexicon_density 列
ALTER TABLE chunk_style
    ADD COLUMN IF NOT EXISTS imagery_lexicon_density FLOAT;

-- 3. graph_entities 新增 last_action 列
ALTER TABLE graph_entities
    ADD COLUMN IF NOT EXISTS last_action TEXT;

-- 4. 创建 chunk_curves 表（合并 emotion_curve + rhythm_curve）
CREATE TABLE IF NOT EXISTS chunk_curves (
    chunk_id       INTEGER NOT NULL,
    run_id         VARCHAR(36) NOT NULL,
    pos_density    FLOAT,
    neg_density    FLOAT,
    net_density    FLOAT,
    smoothed_density FLOAT,
    tension_proxy  FLOAT,
    tension_composite FLOAT,
    PRIMARY KEY (chunk_id, run_id),
    CONSTRAINT fk_chunk_curves_chunks
        FOREIGN KEY (chunk_id, run_id)
        REFERENCES chunks (chunk_id, run_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_chunk_curves_runs
        FOREIGN KEY (run_id)
        REFERENCES analysis_runs (run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunk_curves_run_id
    ON chunk_curves (run_id);

COMMIT;
