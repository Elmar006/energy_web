package geoimport

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Metadata struct {
	Name       string
	Kind       string
	Source     string
	License    string
	CapturedAt *time.Time
}

type Result struct {
	DatasetID string
	Features  int
	SHA256    string
}

type collection struct {
	Type     string `json:"type"`
	Features []struct {
		Type       string          `json:"type"`
		ID         any             `json:"id"`
		Geometry   json.RawMessage `json:"geometry"`
		Properties map[string]any  `json:"properties"`
	} `json:"features"`
}

func Import(ctx context.Context, db *pgxpool.Pool, reader io.Reader, meta Metadata) (Result, error) {
	if meta.Name == "" || meta.Source == "" || (meta.Kind != "observed" && meta.Kind != "derived" && meta.Kind != "assumed") {
		return Result{}, errors.New("name, source, and valid kind are required")
	}
	raw, err := io.ReadAll(io.LimitReader(reader, 50<<20))
	if err != nil {
		return Result{}, err
	}
	if len(raw) == 50<<20 {
		return Result{}, errors.New("GeoJSON exceeds 50 MiB")
	}
	var input collection
	if err = json.Unmarshal(raw, &input); err != nil {
		return Result{}, err
	}
	if input.Type != "FeatureCollection" || len(input.Features) == 0 {
		return Result{}, errors.New("nonempty FeatureCollection required")
	}
	sum := sha256.Sum256(raw)
	out := Result{SHA256: hex.EncodeToString(sum[:])}
	tx, err := db.Begin(ctx)
	if err != nil {
		return Result{}, err
	}
	defer tx.Rollback(ctx)
	err = tx.QueryRow(ctx, `INSERT INTO dataset_versions(id,name,kind,source,license,checksum,captured_at)
        VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6) RETURNING id::text`, meta.Name, meta.Kind, meta.Source, meta.License, out.SHA256, meta.CapturedAt).Scan(&out.DatasetID)
	if err != nil {
		return Result{}, err
	}
	for i, feature := range input.Features {
		if feature.Type != "Feature" || !json.Valid(feature.Geometry) || string(feature.Geometry) == "null" {
			return Result{}, fmt.Errorf("invalid feature %d", i)
		}
		properties := feature.Properties
		if properties == nil {
			properties = map[string]any{}
		}
		kind, _ := properties["feature_type"].(string)
		if kind == "" {
			kind = "unclassified"
		}
		props, err := json.Marshal(properties)
		if err != nil {
			return Result{}, err
		}
		external := fmt.Sprint(feature.ID)
		if feature.ID == nil {
			external = ""
		}
		tag, err := tx.Exec(ctx, `INSERT INTO geographic_features(id,dataset_version_id,feature_type,external_id,properties,geom)
            SELECT gen_random_uuid(),$1::uuid,$2,$3,$4::jsonb,ST_SetSRID(ST_GeomFromGeoJSON($5),4326)
            WHERE ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON($5),4326))
              AND ST_XMin(ST_SetSRID(ST_GeomFromGeoJSON($5),4326))>=-180
              AND ST_XMax(ST_SetSRID(ST_GeomFromGeoJSON($5),4326))<=180
              AND ST_YMin(ST_SetSRID(ST_GeomFromGeoJSON($5),4326))>=-90
              AND ST_YMax(ST_SetSRID(ST_GeomFromGeoJSON($5),4326))<=90`, out.DatasetID, kind, external, props, feature.Geometry)
		if err != nil {
			return Result{}, fmt.Errorf("feature %d: %w", i, err)
		}
		if tag.RowsAffected() != 1 {
			return Result{}, fmt.Errorf("feature %d has invalid geometry or coordinates", i)
		}
		out.Features++
	}
	if err = tx.Commit(ctx); err != nil {
		return Result{}, err
	}
	return out, nil
}
