package store

import (
	"context"
	"encoding/json"
)

type Dataset struct {
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	Kind     string  `json:"kind"`
	Source   string  `json:"source"`
	License  *string `json:"license,omitempty"`
	Checksum string  `json:"checksum"`
}

func (s *Store) Datasets(ctx context.Context) ([]Dataset, error) {
	rows, err := s.DB.Query(ctx, `SELECT id::text,name,kind,source,license,checksum FROM dataset_versions ORDER BY created_at DESC LIMIT 100`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Dataset{}
	for rows.Next() {
		var d Dataset
		if err := rows.Scan(&d.ID, &d.Name, &d.Kind, &d.Source, &d.License, &d.Checksum); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func (s *Store) GeoJSON(ctx context.Context, west, south, east, north float64, kind string) (json.RawMessage, error) {
	var raw json.RawMessage
	err := s.DB.QueryRow(ctx, `SELECT json_build_object('type','FeatureCollection','features',coalesce(json_agg(json_build_object(
  'type','Feature','id',id::text,'geometry',ST_AsGeoJSON(geom)::json,'properties',properties)), '[]'::json))
  FROM (SELECT id,geom,properties FROM geographic_features WHERE geom && ST_MakeEnvelope($1,$2,$3,$4,4326)
   AND ($5='' OR feature_type=$5) ORDER BY id LIMIT 1000) AS found`, west, south, east, north, kind).Scan(&raw)
	return raw, err
}

func (s *Store) Tile(ctx context.Context, z, x, y int, kind string) ([]byte, error) {
	var tile []byte
	err := s.DB.QueryRow(ctx, `WITH bounds AS (SELECT ST_TileEnvelope($1,$2,$3) AS geom),
	  features AS (SELECT f.id::text AS id,f.feature_type,ST_AsMVTGeom(ST_Transform(f.geom,3857),bounds.geom) AS geom
	   FROM geographic_features f,bounds WHERE f.geom && ST_Transform(bounds.geom,4326)
   AND ($4='' OR f.feature_type=$4) LIMIT 10000)
  SELECT ST_AsMVT(features,'features',4096,'geom') FROM features`, z, x, y, kind).Scan(&tile)
	return tile, err
}
