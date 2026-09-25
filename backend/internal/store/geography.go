package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"

	"github.com/Elmar006/energy_web/backend/internal/geography"
	"github.com/Elmar006/energy_web/backend/internal/geoimport"
)

type Dataset = geography.Dataset

func (s *Store) ImportDataset(ctx context.Context, reader io.Reader, meta geography.ImportMetadata) (geography.ImportResult, error) {
	result, err := geoimport.Import(ctx, s.DB, reader, geoimport.Metadata{
		Name: meta.Name, Kind: meta.Kind, Source: meta.Source,
		License: meta.License, CapturedAt: meta.CapturedAt})
	if err != nil {
		if errors.Is(err, geoimport.ErrInvalidGeoJSON) {
			return geography.ImportResult{}, fmt.Errorf("%w: %v", geography.ErrInvalidImport, err)
		}
		return geography.ImportResult{}, err
	}
	return geography.ImportResult{DatasetID: result.DatasetID,
		Features: result.Features, SHA256: result.SHA256}, nil
}

func (s *Store) Datasets(ctx context.Context) ([]Dataset, error) {
	rows, err := s.DB.Query(ctx, `SELECT d.id::text,d.name,d.kind,d.source,d.license,d.checksum,
		d.captured_at,d.created_at,
		CASE WHEN m.dataset_version_id IS NOT NULL THEN 'mobility'
		     WHEN u.dataset_version_id IS NOT NULL THEN 'csv' ELSE 'geojson' END,
		CASE WHEN m.dataset_version_id IS NOT NULL THEN 'mobility_source' ELSE u.role END
		FROM dataset_versions d LEFT JOIN uploaded_csv u ON u.dataset_version_id=d.id
		LEFT JOIN scenario_mobility_sources m ON m.dataset_version_id=d.id
		ORDER BY d.created_at DESC,d.id DESC LIMIT 100`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Dataset{}
	for rows.Next() {
		var d Dataset
		if err := rows.Scan(&d.ID, &d.Name, &d.Kind, &d.Source, &d.License, &d.Checksum,
			&d.CapturedAt, &d.CreatedAt, &d.Format, &d.Role); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func (s *Store) GeoJSON(ctx context.Context, west, south, east, north float64, kind string) (json.RawMessage, error) {
	var raw json.RawMessage
	err := s.DB.QueryRow(ctx, `WITH canonical AS (
    SELECT DISTINCT ON (name,kind,source,checksum,license,captured_at) id FROM dataset_versions
    ORDER BY name,kind,source,checksum,license,captured_at,created_at DESC,id DESC
  ) SELECT json_build_object('type','FeatureCollection','features',coalesce(json_agg(json_build_object(
  'type','Feature','id',id::text,'geometry',ST_AsGeoJSON(geom)::json,'properties',properties)), '[]'::json))
  FROM (SELECT f.id,f.geom,f.properties FROM geographic_features f JOIN canonical c ON c.id=f.dataset_version_id
   WHERE f.geom && ST_MakeEnvelope($1,$2,$3,$4,4326)
   AND ($5='' OR f.feature_type=$5) ORDER BY f.id LIMIT 1000) AS found`, west, south, east, north, kind).Scan(&raw)
	return raw, err
}

func (s *Store) Tile(ctx context.Context, z, x, y int, kind string) ([]byte, error) {
	var tile []byte
	err := s.DB.QueryRow(ctx, `WITH bounds AS (SELECT ST_TileEnvelope($1,$2,$3) AS geom),
	  canonical AS (SELECT DISTINCT ON (name,kind,source,checksum,license,captured_at) id FROM dataset_versions
	   ORDER BY name,kind,source,checksum,license,captured_at,created_at DESC,id DESC),
	  features AS (SELECT f.id::text AS id,f.feature_type,ST_AsMVTGeom(ST_Transform(f.geom,3857),bounds.geom) AS geom
	   FROM geographic_features f JOIN canonical c ON c.id=f.dataset_version_id,bounds
	   WHERE f.geom && ST_Transform(bounds.geom,4326)
   AND ($4='' OR f.feature_type=$4) LIMIT 10000)
  SELECT ST_AsMVT(features,'features',4096,'geom') FROM features`, z, x, y, kind).Scan(&tile)
	return tile, err
}
