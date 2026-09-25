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
	"github.com/jackc/pgx/v5/pgxpool"
)

type Store struct{ DB *pgxpool.Pool }

type Scenario = planning.Scenario
type ScenarioSummary = planning.ScenarioSummary
type Run = planning.Run

type Job = planning.Job

type Event = planning.Event

var ErrNotFound = planning.ErrNotFound

func New(ctx context.Context, url string) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 10
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return &Store{DB: pool}, nil
}

func (s *Store) Close() { s.DB.Close() }

func (s *Store) CreateScenario(ctx context.Context, name string, spec json.RawMessage) (Scenario, error) {
	// PostgreSQL jsonb normalizes object order and number formatting. Hash the
	// exact representation that a later GET and worker claim will retrieve.
	var normalized json.RawMessage
	if err := s.DB.QueryRow(ctx, `SELECT $1::jsonb`, spec).Scan(&normalized); err != nil {
		return Scenario{}, err
	}
	sum := sha256.Sum256(normalized)
	var out Scenario
	err := s.DB.QueryRow(ctx, `INSERT INTO scenarios(id,name,spec,spec_sha256) VALUES(gen_random_uuid(),$1,$2,$3)
		RETURNING id::text,name,spec,spec_sha256`, name, normalized, hex.EncodeToString(sum[:])).Scan(&out.ID, &out.Name, &out.Spec, &out.SHA256)
	return out, err
}

func (s *Store) GetScenario(ctx context.Context, id string) (Scenario, error) {
	var out Scenario
	err := s.DB.QueryRow(ctx, `SELECT id::text,name,spec,spec_sha256 FROM scenarios WHERE id=$1::uuid`, id).Scan(&out.ID, &out.Name, &out.Spec, &out.SHA256)
	if errors.Is(err, pgx.ErrNoRows) {
		return out, ErrNotFound
	}
	return out, err
}

func (s *Store) ListScenarios(ctx context.Context) ([]ScenarioSummary, error) {
	rows, err := s.DB.Query(ctx, `SELECT id::text,name,spec_sha256,created_at FROM scenarios ORDER BY created_at DESC,id DESC LIMIT 100`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ScenarioSummary{}
	for rows.Next() {
		var item ScenarioSummary
		if err := rows.Scan(&item.ID, &item.Name, &item.SHA256, &item.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

const runColumns = `id::text,scenario_id::text,state,attempts,error_code,error_detail,created_at,updated_at,
    run_spec,scenario_sha256,run_spec_sha256,execution_sha256,run_spec_origin`

func scanRun(row pgx.Row) (Run, error) {
	var r Run
	err := row.Scan(&r.ID, &r.ScenarioID, &r.State, &r.Attempts, &r.ErrorCode, &r.ErrorDetail,
		&r.CreatedAt, &r.UpdatedAt, &r.RunSpec, &r.ScenarioSHA256, &r.RunSpecSHA256, &r.ExecutionSHA256, &r.RunSpecOrigin)
	return r, err
}

// CreateRun freezes the complete execution configuration before a worker can
// claim the job. Reusing a key is valid only for exactly the same resolved
// configuration, including under concurrent inserts.
func (s *Store) CreateRun(ctx context.Context, scenarioID, key string, specs ...planning.RunSpec) (Run, error) {
	if len(specs) > 1 {
		return Run{}, errors.New("at most one run specification is supported")
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Run{}, err
	}
	defer tx.Rollback(ctx)
	var scenario json.RawMessage
	var scenarioSHA string
	err = tx.QueryRow(ctx, `SELECT spec,spec_sha256 FROM scenarios WHERE id=$1::uuid FOR SHARE`, scenarioID).Scan(&scenario, &scenarioSHA)
	if errors.Is(err, pgx.ErrNoRows) {
		return Run{}, ErrNotFound
	}
	if err != nil {
		return Run{}, err
	}
	var raw json.RawMessage
	if len(specs) == 1 {
		raw, err = json.Marshal(specs[0])
		if err != nil {
			return Run{}, err
		}
	}
	resolved, err := planning.ResolveRunSpec(raw, scenario)
	if err != nil {
		return Run{}, err
	}
	raw, err = json.Marshal(resolved)
	if err != nil {
		return Run{}, err
	}
	var normalized json.RawMessage
	if err := tx.QueryRow(ctx, `SELECT $1::jsonb`, raw).Scan(&normalized); err != nil {
		return Run{}, err
	}
	specSum := sha256.Sum256(normalized)
	specSHA := hex.EncodeToString(specSum[:])
	executionSum := sha256.Sum256([]byte(scenarioSHA + "\n" + specSHA))
	executionSHA := hex.EncodeToString(executionSum[:])
	r, err := scanRun(tx.QueryRow(ctx, `INSERT INTO runs(id,scenario_id,idempotency_key,state,
            run_spec,scenario_sha256,run_spec_sha256,execution_sha256,run_spec_origin)
        VALUES(gen_random_uuid(),$1::uuid,$2,'queued',$3,$4,$5,$6,'resolved')
        ON CONFLICT (scenario_id,idempotency_key) DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key
        WHERE runs.run_spec_sha256=EXCLUDED.run_spec_sha256 AND runs.execution_sha256=EXCLUDED.execution_sha256
        RETURNING `+runColumns, scenarioID, key, normalized, scenarioSHA, specSHA, executionSHA))
	if errors.Is(err, pgx.ErrNoRows) {
		return Run{}, planning.ErrRunSpecConflict
	}
	if err != nil {
		return Run{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Run{}, err
	}
	return r, nil
}

func (s *Store) GetRun(ctx context.Context, id string) (Run, error) {
	r, err := scanRun(s.DB.QueryRow(ctx, `SELECT `+runColumns+` FROM runs WHERE id=$1::uuid`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return r, ErrNotFound
	}
	return r, err
}

func (s *Store) Result(ctx context.Context, id string) (json.RawMessage, error) {
	var data json.RawMessage
	err := s.DB.QueryRow(ctx, `SELECT result FROM runs WHERE id=$1::uuid AND state='succeeded'`, id).Scan(&data)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	return data, err
}

func (s *Store) Cancel(ctx context.Context, id string) (bool, error) {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)
	var state string
	err = tx.QueryRow(ctx, `UPDATE runs SET state='cancelled',updated_at=now() WHERE id=$1::uuid AND state IN ('queued','running') RETURNING state`, id).Scan(&state)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	_, err = tx.Exec(ctx, `INSERT INTO run_events(run_id,kind) VALUES($1::uuid,'cancelled')`, id)
	if err != nil {
		return false, err
	}
	return true, tx.Commit(ctx)
}

func (s *Store) Claim(ctx context.Context) (*Job, error) {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var job Job
	err = tx.QueryRow(ctx, `WITH next AS (
        SELECT id FROM runs WHERE state='queued' OR (state='running' AND lease_until<now())
        ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    ) UPDATE runs r SET state='running',attempt_id=gen_random_uuid(),attempts=attempts+1,
        lease_until=now()+interval '30 seconds',updated_at=now(),error_code=NULL,error_detail=NULL
        FROM next,scenarios sc WHERE r.id=next.id AND sc.id=r.scenario_id
        RETURNING r.id::text,r.attempt_id::text,sc.spec,r.run_spec,r.scenario_sha256,r.run_spec_sha256,r.execution_sha256`).Scan(
		&job.RunID, &job.AttemptID, &job.Spec, &job.RunSpec, &job.ScenarioSHA256, &job.RunSpecSHA256, &job.ExecutionSHA256)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	_, err = tx.Exec(ctx, `INSERT INTO run_events(run_id,kind,detail) VALUES($1::uuid,'running',$2)`, job.RunID, fmt.Sprintf("attempt %s", job.AttemptID))
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return &job, nil
}

func (s *Store) Heartbeat(ctx context.Context, runID, attemptID string) (bool, error) {
	tag, err := s.DB.Exec(ctx, `UPDATE runs SET lease_until=now()+interval '30 seconds',updated_at=now()
        WHERE id=$1::uuid AND attempt_id=$2::uuid AND state='running'`, runID, attemptID)
	return tag.RowsAffected() == 1, err
}

func (s *Store) Finish(ctx context.Context, job Job, result json.RawMessage, code, detail string) (bool, error) {
	state := "succeeded"
	if code != "" {
		state = "failed"
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer tx.Rollback(ctx)
	tag, err := tx.Exec(ctx, `UPDATE runs SET state=$3,result=$4,error_code=NULLIF($5,''),error_detail=NULLIF($6,''),
        lease_until=NULL,updated_at=now() WHERE id=$1::uuid AND attempt_id=$2::uuid AND state='running'`,
		job.RunID, job.AttemptID, state, result, code, detail)
	if err != nil {
		return false, err
	}
	if tag.RowsAffected() == 0 {
		return false, nil
	}
	_, err = tx.Exec(ctx, `INSERT INTO run_events(run_id,kind,detail) VALUES($1::uuid,$2,$3)`, job.RunID, state, detail)
	if err != nil {
		return false, err
	}
	return true, tx.Commit(ctx)
}

func (s *Store) Events(ctx context.Context, runID string, after int64) ([]Event, error) {
	rows, err := s.DB.Query(ctx, `SELECT e.id,e.kind,e.detail,e.created_at FROM run_events e WHERE e.run_id=$1::uuid AND e.id>$2 ORDER BY e.id LIMIT 100`, runID, after)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var events []Event
	for rows.Next() {
		var e Event
		if err = rows.Scan(&e.ID, &e.Kind, &e.Detail, &e.CreatedAt); err != nil {
			return nil, err
		}
		events = append(events, e)
	}
	return events, rows.Err()
}
