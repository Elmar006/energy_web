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

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
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

var ErrInvalidGeoJSON = errors.New("invalid GeoJSON dataset")

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
		return Result{}, fmt.Errorf("%w: name, source, and valid kind are required", ErrInvalidGeoJSON)
	}
	if meta.CapturedAt != nil {
		// PostgreSQL timestamptz stores microseconds. Use the same instant for
		// the idempotency lookup and INSERT even if the caller has nanoseconds.
		instant := meta.CapturedAt.UTC().Truncate(time.Microsecond)
		meta.CapturedAt = &instant
	}
	raw, err := io.ReadAll(io.LimitReader(reader, 50<<20))
	if err != nil {
		return Result{}, err
	}
	if len(raw) == 50<<20 {
		return Result{}, fmt.Errorf("%w: GeoJSON exceeds 50 MiB", ErrInvalidGeoJSON)
	}
	var input collection
	if err = json.Unmarshal(raw, &input); err != nil {
		return Result{}, fmt.Errorf("%w: %v", ErrInvalidGeoJSON, err)
	}
	if input.Type != "FeatureCollection" || len(input.Features) == 0 || len(input.Features) > 10000 {
		return Result{}, fmt.Errorf("%w: FeatureCollection must contain 1..10000 features", ErrInvalidGeoJSON)
	}
	sum := sha256.Sum256(raw)
	out := Result{SHA256: hex.EncodeToString(sum[:])}
	tx, err := db.Begin(ctx)
	if err != nil {
		return Result{}, err
	}
	defer tx.Rollback(ctx)
	// Serialize imports of the same immutable content. The exact lookup below
	// handles hash-lock collisions and returns an existing version rather than
	// inserting duplicate features on retries or concurrent CLI runs.
	captured := ""
	if meta.CapturedAt != nil {
		captured = meta.CapturedAt.UTC().Format(time.RFC3339Nano)
	}
	lockKey := fmt.Sprintf("%q|%q|%q|%q|%q|%q", meta.Name, meta.Kind, meta.Source,
		out.SHA256, meta.License, captured)
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lockKey); err != nil {
		return Result{}, err
	}
	err = tx.QueryRow(ctx, `SELECT d.id::text,count(f.id)
		FROM dataset_versions d LEFT JOIN geographic_features f ON f.dataset_version_id=d.id
		WHERE d.name=$1 AND d.kind=$2 AND d.source=$3 AND d.checksum=$4
		  AND d.license=$5 AND d.captured_at IS NOT DISTINCT FROM $6
		GROUP BY d.id,d.created_at ORDER BY d.created_at DESC,d.id DESC LIMIT 1`,
		meta.Name, meta.Kind, meta.Source, out.SHA256, meta.License, meta.CapturedAt).Scan(&out.DatasetID, &out.Features)
	if err == nil {
		return out, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Result{}, err
	}
	err = tx.QueryRow(ctx, `INSERT INTO dataset_versions(id,name,kind,source,license,checksum,captured_at)
        VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6) RETURNING id::text`, meta.Name, meta.Kind, meta.Source, meta.License, out.SHA256, meta.CapturedAt).Scan(&out.DatasetID)
	if err != nil {
		return Result{}, err
	}
	for i, feature := range input.Features {
		if feature.Type != "Feature" || !json.Valid(feature.Geometry) || string(feature.Geometry) == "null" {
			return Result{}, fmt.Errorf("%w: invalid feature %d", ErrInvalidGeoJSON, i)
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
			var pgError *pgconn.PgError
			if errors.As(err, &pgError) && (pgError.Code == "XX000" || len(pgError.Code) >= 2 && pgError.Code[:2] == "22") {
				return Result{}, fmt.Errorf("%w: feature %d geometry: %s", ErrInvalidGeoJSON, i, pgError.Message)
			}
			return Result{}, fmt.Errorf("feature %d: %w", i, err)
		}
		if tag.RowsAffected() != 1 {
			return Result{}, fmt.Errorf("%w: feature %d has invalid geometry or coordinates", ErrInvalidGeoJSON, i)
		}
		out.Features++
	}
	if err = tx.Commit(ctx); err != nil {
		return Result{}, err
	}
	return out, nil
}
