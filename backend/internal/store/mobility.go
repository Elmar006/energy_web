package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/Elmar006/energy_web/backend/internal/planning"
	"github.com/jackc/pgx/v5"
)

func (s *Store) SaveMobility(ctx context.Context, in planning.MobilityPersist) (planning.MobilitySaveResult, error) {
	var out planning.MobilitySaveResult
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(ctx)
	// Both hashes describe PostgreSQL's persisted jsonb snapshots, not a
	// request-body formatting choice that changes on every serialization.
	var normalizedSpec, normalizedBase json.RawMessage
	if err := tx.QueryRow(ctx, `SELECT $1::jsonb,$2::jsonb`, in.Spec, in.BaseInput).
		Scan(&normalizedSpec, &normalizedBase); err != nil {
		return out, err
	}
	specSum := sha256.Sum256(normalizedSpec)
	baseSum := sha256.Sum256(normalizedBase)
	var manifest struct {
		Datasets []struct {
			VersionID string `json:"version_id"`
			SHA256    string `json:"sha256"`
		} `json:"datasets"`
	}
	if json.Unmarshal(normalizedSpec, &manifest) != nil || len(manifest.Datasets) == 0 ||
		manifest.Datasets[len(manifest.Datasets)-1].VersionID != in.DatasetVersionID ||
		manifest.Datasets[len(manifest.Datasets)-1].SHA256 != in.SourceSHA256 {
		return out, fmt.Errorf("mobility scenario manifest does not bind its source")
	}
	sourceSum := sha256.Sum256(in.CanonicalMobility)
	if hex.EncodeToString(sourceSum[:]) != in.SourceSHA256 {
		return out, fmt.Errorf("mobility source checksum mismatch")
	}
	if _, err := tx.Exec(ctx, `INSERT INTO dataset_versions(id,name,kind,source,license,checksum)
		VALUES($1::uuid,$2,$3,$4,$5,$6)`, in.DatasetVersionID,
		"mobility-v1 potential public requests", in.SourceKind, in.SourceName,
		in.License, in.SourceSHA256); err != nil {
		return out, err
	}
	err = tx.QueryRow(ctx, `INSERT INTO scenarios(id,name,spec,spec_sha256)
		VALUES(gen_random_uuid(),$1,$2::jsonb,$3)
		RETURNING id::text,name,spec,spec_sha256`, in.Name, normalizedSpec,
		hex.EncodeToString(specSum[:])).Scan(
		&out.Scenario.ID, &out.Scenario.Name, &out.Scenario.Spec, &out.Scenario.SHA256)
	if err != nil {
		return planning.MobilitySaveResult{}, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO scenario_mobility_sources
		(scenario_id,dataset_version_id,base_input,base_sha256,content,byte_size,
		 source_sha256,access_token_sha256,compiler_version,compiler_source_sha256,compiler_pydantic_version)
		VALUES($1::uuid,$2::uuid,$3::jsonb,$4,$5,$6,$7,$8,$9,$10,$11)`,
		out.Scenario.ID, in.DatasetVersionID, normalizedBase, hex.EncodeToString(baseSum[:]),
		in.CanonicalMobility, len(in.CanonicalMobility), in.SourceSHA256,
		in.AccessTokenSHA256, in.CompilerVersion, in.CompilerSourceSHA256,
		in.CompilerPydanticVersion); err != nil {
		return planning.MobilitySaveResult{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return planning.MobilitySaveResult{}, err
	}
	out.DatasetVersionID = in.DatasetVersionID
	out.SourceSHA256 = in.SourceSHA256
	out.BaseSHA256 = hex.EncodeToString(baseSum[:])
	return out, nil
}

func (s *Store) GetMobilityOrigin(ctx context.Context, scenarioID, tokenSHA string) (planning.MobilityOrigin, error) {
	var out planning.MobilityOrigin
	var source []byte
	err := s.DB.QueryRow(ctx, `SELECT m.scenario_id::text,m.dataset_version_id::text,
		m.base_input,m.base_sha256,m.content,m.source_sha256,m.compiler_version,
		m.compiler_source_sha256,m.compiler_pydantic_version
		FROM scenario_mobility_sources m
		WHERE m.scenario_id=$1::uuid AND m.access_token_sha256=$2`, scenarioID, tokenSHA).
		Scan(&out.ScenarioID, &out.DatasetVersionID, &out.BaseInput,
			&out.BaseSHA256, &source, &out.SourceSHA256, &out.CompilerVersion,
			&out.CompilerSourceSHA256, &out.CompilerPydanticVersion)
	if errors.Is(err, pgx.ErrNoRows) {
		return planning.MobilityOrigin{}, planning.ErrNotFound
	}
	if err != nil {
		return planning.MobilityOrigin{}, err
	}
	sourceSum := sha256.Sum256(source)
	baseSum := sha256.Sum256(out.BaseInput)
	if hex.EncodeToString(sourceSum[:]) != out.SourceSHA256 ||
		hex.EncodeToString(baseSum[:]) != out.BaseSHA256 {
		return planning.MobilityOrigin{}, fmt.Errorf("stored mobility source integrity check failed")
	}
	out.SourceCanonicalJSON = string(source)
	return out, nil
}
