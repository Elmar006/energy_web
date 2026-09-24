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

func (s *Store) SaveScenarioImport(ctx context.Context, in planning.ImportInput, spec json.RawMessage,
	versionID, fileSHA, transformVersion, key string) (planning.ImportResult, error) {
	var out planning.ImportResult
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return out, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, key); err != nil {
		return out, err
	}
	lookup := `SELECT sc.id::text,sc.name,sc.spec,sc.spec_sha256,si.dataset_version_id::text,
		uc.role,d.checksum FROM scenario_imports si
		JOIN scenarios sc ON sc.id=si.scenario_id
		JOIN uploaded_csv uc ON uc.dataset_version_id=si.dataset_version_id
		JOIN dataset_versions d ON d.id=si.dataset_version_id WHERE si.import_key=$1`
	err = tx.QueryRow(ctx, lookup, key).Scan(&out.Scenario.ID, &out.Scenario.Name,
		&out.Scenario.Spec, &out.Scenario.SHA256, &out.DatasetID, &out.Role, &out.SHA256)
	if err == nil {
		out.Reused = true
		return out, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return planning.ImportResult{}, err
	}
	// Hash exactly the jsonb snapshot that a later worker claim will use.
	var normalized json.RawMessage
	if err = tx.QueryRow(ctx, `SELECT $1::jsonb`, spec).Scan(&normalized); err != nil {
		return planning.ImportResult{}, err
	}
	sum := sha256.Sum256(normalized)
	config, err := json.Marshal(map[string]string{
		"role": in.Role, "source": in.Source, "kind": in.Kind,
		"time_zone": in.TimeZone, "start_date": in.StartDate,
		"end_date": in.EndDate, "profile_date": in.ProfileDate,
		"coverage_complete": fmt.Sprint(in.CoverageComplete),
		"transform_version": transformVersion,
	})
	if err != nil {
		return planning.ImportResult{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO dataset_versions(id,name,kind,source,license,checksum)
		VALUES($1::uuid,$2,$3,$4,$5,$6)`, versionID, in.DatasetName, in.Kind,
		in.Source, in.License, fileSHA); err != nil {
		return planning.ImportResult{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO uploaded_csv(dataset_version_id,role,filename,content,byte_size)
		VALUES($1::uuid,$2,$3,$4,$5)`, versionID, in.Role, in.FileName, in.CSV, len(in.CSV)); err != nil {
		return planning.ImportResult{}, err
	}
	err = tx.QueryRow(ctx, `INSERT INTO scenarios(id,name,spec,spec_sha256)
		VALUES(gen_random_uuid(),$1,$2,$3) RETURNING id::text,name,spec,spec_sha256`,
		in.ScenarioName, normalized, hex.EncodeToString(sum[:])).Scan(
		&out.Scenario.ID, &out.Scenario.Name, &out.Scenario.Spec, &out.Scenario.SHA256)
	if err != nil {
		return planning.ImportResult{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO scenario_imports(scenario_id,parent_scenario_id,dataset_version_id,import_key,transform_config)
		VALUES($1::uuid,$2::uuid,$3::uuid,$4,$5::jsonb)`, out.Scenario.ID,
		in.ParentScenarioID, versionID, key, config); err != nil {
		return planning.ImportResult{}, err
	}
	if err = tx.Commit(ctx); err != nil {
		return planning.ImportResult{}, err
	}
	out.DatasetID, out.Role, out.SHA256 = versionID, in.Role, fileSHA
	return out, nil
}

func (s *Store) GetUploadedFile(ctx context.Context, datasetID string) (planning.UploadedFile, error) {
	var out planning.UploadedFile
	err := s.DB.QueryRow(ctx, `SELECT u.content,u.filename,d.checksum,u.role
		FROM uploaded_csv u JOIN dataset_versions d ON d.id=u.dataset_version_id
		WHERE u.dataset_version_id=$1::uuid`, datasetID).Scan(
		&out.Content, &out.FileName, &out.SHA256, &out.Role)
	if errors.Is(err, pgx.ErrNoRows) {
		return out, planning.ErrNotFound
	}
	return out, err
}
