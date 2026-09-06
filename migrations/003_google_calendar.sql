-- Manual migration: Google Calendar sync support
-- Safe to run multiple times (uses IF NOT EXISTS / conditional checks).

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS google_refresh_token TEXT;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(255);
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS google_calendar_connected_at TIMESTAMPTZ;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS google_calendar_sync_enabled BOOLEAN DEFAULT FALSE;

ALTER TABLE tareas ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS ix_tareas_google_event_id ON tareas(google_event_id);
