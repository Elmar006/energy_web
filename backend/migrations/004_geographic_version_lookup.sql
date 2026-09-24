-- Keep historical imports for audit, but make canonical-version selection and
-- dataset-scoped feature access efficient. New imports reuse an exact match.
CREATE INDEX IF NOT EXISTS dataset_versions_identity_recent_idx
ON dataset_versions(name,kind,source,checksum,created_at DESC,id DESC);

CREATE INDEX IF NOT EXISTS geographic_features_dataset_idx
ON geographic_features(dataset_version_id);
