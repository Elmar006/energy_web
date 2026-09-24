-- Indexes for the actual list and job-claim access patterns on existing volumes.
CREATE INDEX IF NOT EXISTS scenarios_recent_idx ON scenarios (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS dataset_versions_recent_idx ON dataset_versions (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS runs_queued_idx ON runs (created_at, id) WHERE state = 'queued';
CREATE INDEX IF NOT EXISTS runs_expired_idx ON runs (lease_until, created_at, id)
  WHERE state = 'running';
