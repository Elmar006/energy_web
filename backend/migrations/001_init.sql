CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS dataset_versions (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('observed','derived','assumed')),
  source text NOT NULL,
  license text,
  checksum text NOT NULL,
  captured_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenarios (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  spec jsonb NOT NULL,
  spec_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
  id uuid PRIMARY KEY,
  scenario_id uuid NOT NULL REFERENCES scenarios(id),
  idempotency_key text NOT NULL,
  state text NOT NULL CHECK (state IN ('queued','running','succeeded','failed','cancelled')),
  attempt_id uuid,
  attempts integer NOT NULL DEFAULT 0,
  lease_until timestamptz,
  result jsonb,
  error_code text,
  error_detail text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scenario_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS runs_claim_idx ON runs(state, lease_until, created_at);

CREATE TABLE IF NOT EXISTS run_events (
  id bigserial PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  kind text NOT NULL,
  detail text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS run_events_stream_idx ON run_events(run_id, id);

CREATE TABLE IF NOT EXISTS geographic_features (
  id uuid PRIMARY KEY,
  dataset_version_id uuid NOT NULL REFERENCES dataset_versions(id),
  feature_type text NOT NULL,
  external_id text,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb,
  geom geometry(Geometry,4326) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS geographic_features_geom_idx ON geographic_features USING gist(geom);
CREATE INDEX IF NOT EXISTS geographic_features_type_idx ON geographic_features(feature_type, dataset_version_id);
