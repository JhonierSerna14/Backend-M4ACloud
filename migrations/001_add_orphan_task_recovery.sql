-- Manual migration for orphan task recovery in worker pipeline
-- Safe to run multiple times.

ALTER TABLE notas
ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ;

ALTER TABLE notas
ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_notas_orphan_detection
ON notas (status, processing_started_at)
WHERE status = 'processing';

CREATE INDEX IF NOT EXISTS ix_notas_processing_attempts
ON notas (status, processing_attempts)
WHERE status = 'processing';
