-- Preserve the itinerary and the exact pre-transformation input alongside the
-- immutable compiled scenario. A random retrieval capability is stored only
-- as a digest; the public API never enumerates source contents.
CREATE TABLE scenario_mobility_sources (
  scenario_id uuid PRIMARY KEY REFERENCES scenarios(id) ON DELETE RESTRICT,
  dataset_version_id uuid NOT NULL UNIQUE REFERENCES dataset_versions(id) ON DELETE RESTRICT,
  base_input jsonb NOT NULL CHECK (jsonb_typeof(base_input)='object'),
  base_sha256 text NOT NULL CHECK (base_sha256 ~ '^[0-9a-f]{64}$'),
  content bytea NOT NULL,
  byte_size integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 4194304),
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  access_token_sha256 text NOT NULL CHECK (access_token_sha256 ~ '^[0-9a-f]{64}$'),
  compiler_version text NOT NULL CHECK (compiler_version='mobility-v1'),
  compiler_source_sha256 text NOT NULL CHECK (compiler_source_sha256 ~ '^[0-9a-f]{64}$'),
  compiler_pydantic_version text NOT NULL CHECK
    (char_length(compiler_pydantic_version) BETWEEN 1 AND 80),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mobility_source_bytes_match CHECK (octet_length(content)=byte_size),
  CONSTRAINT mobility_source_digest_match CHECK (source_sha256=encode(sha256(content),'hex')),
  CONSTRAINT mobility_base_digest_match CHECK
    (base_sha256=encode(sha256(convert_to(base_input::text,'UTF8')),'hex'))
);

CREATE FUNCTION protect_mobility_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mobility source snapshots are immutable; create a new scenario'
    USING ERRCODE='23514';
END;
$$;

CREATE TRIGGER mobility_immutable_snapshot BEFORE UPDATE ON scenario_mobility_sources
  FOR EACH ROW EXECUTE FUNCTION protect_mobility_snapshot();
