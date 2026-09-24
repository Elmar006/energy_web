-- Keep the exact user-supplied bytes alongside their immutable dataset version.
-- TOAST stores large CSV values out of line; this is a bounded self-hosted
-- artifact backend until an object-store implementation is introduced.
CREATE TABLE uploaded_csv (
  dataset_version_id uuid PRIMARY KEY REFERENCES dataset_versions(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('demand_sessions','grid_headroom')),
  filename text NOT NULL,
  content bytea NOT NULL,
  byte_size integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 52428800),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (octet_length(content) = byte_size)
);

CREATE TABLE scenario_imports (
  scenario_id uuid PRIMARY KEY REFERENCES scenarios(id) ON DELETE RESTRICT,
  parent_scenario_id uuid NOT NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
  dataset_version_id uuid NOT NULL UNIQUE REFERENCES uploaded_csv(dataset_version_id) ON DELETE RESTRICT,
  import_key text NOT NULL UNIQUE CHECK (import_key ~ '^[0-9a-f]{64}$'),
  transform_config jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX scenario_imports_parent_created_idx
  ON scenario_imports(parent_scenario_id, created_at DESC, scenario_id);
