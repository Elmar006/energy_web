package store

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

func TestPlanningDatasetReadsOnlyTheSelectedVersion(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	var selected, other string
	for index, target := range []*string{&selected, &other} {
		err := s.DB.QueryRow(ctx, `INSERT INTO dataset_versions(id,name,kind,source,checksum,captured_at)
			VALUES(gen_random_uuid(),'version test','observed','integration test',$1,now()) RETURNING id::text`,
			strings.Repeat(string(rune('a'+index)), 64)).Scan(target)
		if err != nil {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() {
		_, _ = s.DB.Exec(context.Background(), `DELETE FROM geographic_features WHERE dataset_version_id IN ($1::uuid,$2::uuid)`, selected, other)
		_, _ = s.DB.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id IN ($1::uuid,$2::uuid)`, selected, other)
	})
	for _, item := range []struct{ datasetID, externalID string }{
		{selected, "z2"}, {selected, "z1"}, {other, "unselected"},
	} {
		_, err := s.DB.Exec(ctx, `INSERT INTO geographic_features(id,dataset_version_id,feature_type,external_id,properties,geom)
			VALUES(gen_random_uuid(),$1::uuid,'demand_zone',$2,'{"feature_type":"demand_zone"}'::jsonb,
			ST_SetSRID(ST_MakePoint(37.6,55.7),4326))`, item.datasetID, item.externalID)
		if err != nil {
			t.Fatal(err)
		}
	}
	got, err := s.PlanningDataset(ctx, selected)
	if err != nil || got.ID != selected || got.Kind != "observed" || got.CapturedAt == nil ||
		len(got.Features) != 2 || got.Features[0].ExternalID != "z1" || got.Features[1].ExternalID != "z2" ||
		got.Features[0].GeometryType != "POINT" || got.Features[0].Latitude == nil ||
		*got.Features[0].Latitude != 55.7 || *got.Features[0].Longitude != 37.6 {
		t.Fatalf("wrong selected snapshot: %+v, %v", got, err)
	}
	_, err = s.PlanningDataset(ctx, "00000000-0000-4000-8000-000000000000")
	if !errors.Is(err, planning.ErrDatasetNotFound) {
		t.Fatalf("unknown version error: %v", err)
	}
}
