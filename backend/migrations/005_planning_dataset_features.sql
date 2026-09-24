-- Exact-version assembly reads every feature in stable external-id order.
-- The import's dataset_version_id index remains useful for unordered reads;
-- this index avoids a separate sort for the planning snapshot query.
CREATE INDEX IF NOT EXISTS geographic_features_planning_version_order_idx
ON geographic_features(dataset_version_id, external_id, id);
