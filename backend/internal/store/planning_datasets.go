package store

import (
	"context"
	"errors"
	"fmt"

	"github.com/Elmar006/energy_web/backend/internal/planning"
	"github.com/jackc/pgx/v5"
)

// PlanningDataset reads one exact imported version. The features and metadata
// are immutable after import; querying by version ID avoids the map's
// canonical-version selection and prevents a later import changing a plan.
func (s *Store) PlanningDataset(ctx context.Context, id string) (planning.PlanningDataset, error) {
	var out planning.PlanningDataset
	err := s.DB.QueryRow(ctx, `SELECT id::text,name,kind,source,license,checksum,captured_at
		FROM dataset_versions WHERE id=$1::uuid`, id).Scan(&out.ID, &out.Name, &out.Kind,
		&out.Source, &out.License, &out.Checksum, &out.CapturedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return out, fmt.Errorf("%w: %s", planning.ErrDatasetNotFound, id)
	}
	if err != nil {
		return out, err
	}
	rows, err := s.DB.Query(ctx, `SELECT coalesce(external_id,''),feature_type,properties,GeometryType(geom),
		CASE WHEN GeometryType(geom)='POINT' THEN ST_Y(geom) END,
		CASE WHEN GeometryType(geom)='POINT' THEN ST_X(geom) END
		FROM geographic_features WHERE dataset_version_id=$1::uuid
		ORDER BY external_id,id LIMIT 10001`, id)
	if err != nil {
		return out, err
	}
	defer rows.Close()
	out.Features = make([]planning.PlanningFeature, 0)
	for rows.Next() {
		var feature planning.PlanningFeature
		if err := rows.Scan(&feature.ExternalID, &feature.FeatureType, &feature.Properties,
			&feature.GeometryType, &feature.Latitude, &feature.Longitude); err != nil {
			return planning.PlanningDataset{}, err
		}
		out.Features = append(out.Features, feature)
	}
	return out, rows.Err()
}
