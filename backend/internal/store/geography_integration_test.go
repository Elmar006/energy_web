package store

import (
	"context"
	"encoding/json"
	"testing"
)

func TestGeographyResponses(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	var datasetID string
	err := s.DB.QueryRow(ctx, `INSERT INTO dataset_versions(id,name,kind,source,checksum)
		VALUES(gen_random_uuid(),'map integration','assumed','test','test') RETURNING id::text`).Scan(&datasetID)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = s.DB.Exec(context.Background(), `DELETE FROM geographic_features WHERE dataset_version_id=$1::uuid`, datasetID)
		_, _ = s.DB.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, datasetID)
	})
	_, err = s.DB.Exec(ctx, `INSERT INTO geographic_features(id,dataset_version_id,feature_type,properties,geom)
		VALUES(gen_random_uuid(),$1::uuid,'integration_marker','{"label":"map-test"}'::jsonb,ST_SetSRID(ST_MakePoint(37.6,55.7),4326))`, datasetID)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := s.GeoJSON(ctx, 37, 55, 38, 56, "integration_marker")
	if err != nil {
		t.Fatal(err)
	}
	var collection struct {
		Type     string            `json:"type"`
		Features []json.RawMessage `json:"features"`
	}
	if err := json.Unmarshal(raw, &collection); err != nil || collection.Type != "FeatureCollection" || len(collection.Features) != 1 {
		t.Fatalf("invalid GeoJSON: %s %v", raw, err)
	}
	outside, err := s.GeoJSON(ctx, -10, -10, 10, 10, "integration_marker")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(outside, &collection); err != nil || len(collection.Features) != 0 {
		t.Fatalf("bbox filter failed: %s %v", outside, err)
	}
	// 37.6 E, 55.7 N belongs to tile 9/309/160.
	tile, err := s.Tile(ctx, 9, 309, 160, "integration_marker")
	if err != nil || len(tile) == 0 {
		t.Fatalf("empty map tile: %d bytes, %v", len(tile), err)
	}
}
