package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"reflect"
	"strings"
	"sync"
	"testing"
	"testing/fstest"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/migrate"
	"github.com/Elmar006/energy_web/backend/internal/planning"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Each test owns a schema and its queue. The configured database must be a
// disposable test database; no worker may consume its jobs during the suite.
func runSpecTestStore(t *testing.T, legacy bool) *Store {
	t.Helper()
	admin := testStore(t)
	ctx := context.Background()
	schema := fmt.Sprintf("runspec_test_%d", time.Now().UnixNano())
	quoted := pgx.Identifier{schema}.Sanitize()
	if _, err := admin.DB.Exec(ctx, `CREATE SCHEMA `+quoted); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := admin.DB.Exec(context.Background(), `DROP SCHEMA `+quoted+` CASCADE`); err != nil {
			t.Errorf("drop own test schema: %v", err)
		}
	})
	cfg, err := pgxpool.ParseConfig(os.Getenv("TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = schema + ",public"
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	source := os.DirFS("../../migrations")
	if legacy {
		old := fstest.MapFS{}
		entries, err := fs.ReadDir(source, ".")
		if err != nil {
			t.Fatal(err)
		}
		for _, entry := range entries {
			if entry.IsDir() || entry.Name() >= "007_" {
				continue
			}
			body, err := fs.ReadFile(source, entry.Name())
			if err != nil {
				t.Fatal(err)
			}
			old[entry.Name()] = &fstest.MapFile{Data: body}
		}
		if err := migrate.Apply(ctx, pool, old); err != nil {
			t.Fatal(err)
		}
	} else if err := migrate.Apply(ctx, pool, source); err != nil {
		t.Fatal(err)
	}
	return &Store{DB: pool}
}

func testRunSpec(t *testing.T, scenario json.RawMessage, validation bool) planning.RunSpec {
	t.Helper()
	spec, err := planning.ResolveRunSpec(nil, scenario)
	if err != nil {
		t.Fatal(err)
	}
	if validation {
		spec.Mode = "validation"
		spec.SimulationSeeds = make([]int, 30)
		for i := range spec.SimulationSeeds {
			spec.SimulationSeeds[i] = 100 + i
		}
	}
	return spec
}

func assertRunSpecHash(t *testing.T, s *Store, run Run) {
	t.Helper()
	var raw json.RawMessage
	if err := s.DB.QueryRow(context.Background(), `SELECT run_spec FROM runs WHERE id=$1`, run.ID).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	specSum := sha256.Sum256(raw)
	executionSum := sha256.Sum256([]byte(run.ScenarioSHA256 + "\n" + run.RunSpecSHA256))
	if run.RunSpecSHA256 != hex.EncodeToString(specSum[:]) || run.ExecutionSHA256 != hex.EncodeToString(executionSum[:]) {
		t.Fatalf("stored fingerprint differs from normalized snapshots: %+v", run)
	}
}

func TestRunSpecPersistsThirtySeedsAndExplicitOverrides(t *testing.T) {
	s := runSpecTestStore(t, false)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "immutable inputs", json.RawMessage(`{"parameters":{"solver_seconds":185,"simulation_days":7}}`))
	if err != nil {
		t.Fatal(err)
	}
	spec := testRunSpec(t, scenario.Spec, true)
	spec.SolverSeconds = 120
	spec.SimulationDays = 4
	spec.ExplainTopN = 0
	spec.AlternativeServiceFractions = []float64{}
	run, err := s.CreateRun(ctx, scenario.ID, "thirty-seeds", spec)
	if err != nil {
		t.Fatal(err)
	}
	actual, err := s.GetRun(ctx, run.ID)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(actual.RunSpec, spec) || actual.RunSpecOrigin != "resolved" || actual.ScenarioSHA256 != scenario.SHA256 {
		t.Fatalf("resolved execution was not persisted: %+v", actual)
	}
	assertRunSpecHash(t, s, actual)
	unchanged, err := s.GetScenario(ctx, scenario.ID)
	if err != nil || string(unchanged.Spec) != string(scenario.Spec) || unchanged.SHA256 != scenario.SHA256 {
		t.Fatalf("run overrides mutated the scenario: %+v %v", unchanged, err)
	}
	replay, err := s.CreateRun(ctx, scenario.ID, "thirty-seeds", spec)
	if err != nil || replay.ID != run.ID || replay.ExecutionSHA256 != run.ExecutionSHA256 {
		t.Fatalf("equivalent replay: %+v %v", replay, err)
	}
	spec.SimulationSeeds[0] = 999
	if _, err := s.CreateRun(ctx, scenario.ID, "thirty-seeds", spec); !errors.Is(err, planning.ErrRunSpecConflict) {
		t.Fatalf("changed seeds reused the key: %v", err)
	}
}

func TestRunSpecDefaultAndExplicitDefaultAreIdempotent(t *testing.T) {
	s := runSpecTestStore(t, false)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "defaults", json.RawMessage(`{"parameters":{"solver_seconds":185,"simulation_days":7}}`))
	if err != nil {
		t.Fatal(err)
	}
	run, err := s.CreateRun(ctx, scenario.ID, "default-key")
	if err != nil {
		t.Fatal(err)
	}
	if run.RunSpec.SolverSeconds != 185 || run.RunSpec.SimulationDays != 7 {
		t.Fatalf("scenario defaults lost: %+v", run.RunSpec)
	}
	again, err := s.CreateRun(ctx, scenario.ID, "default-key", testRunSpec(t, scenario.Spec, false))
	if err != nil || again.ID != run.ID {
		t.Fatalf("explicit resolved defaults should replay: %+v %v", again, err)
	}
	bad := run.RunSpec
	bad.SimulationSeeds = []int{1, 1}
	if _, err := s.CreateRun(ctx, scenario.ID, "invalid-key", bad); !errors.Is(err, planning.ErrInvalidRunSpec) {
		t.Fatalf("invalid specification persisted: %v", err)
	}
	var count int
	if err := s.DB.QueryRow(ctx, `SELECT count(*) FROM runs`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("failed creation left a run: count=%d err=%v", count, err)
	}
}

func TestRunSpecConcurrentDifferentConfigurationsConflict(t *testing.T) {
	s := runSpecTestStore(t, false)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "concurrency", json.RawMessage(`{}`))
	if err != nil {
		t.Fatal(err)
	}
	first := testRunSpec(t, scenario.Spec, false)
	second := first
	second.ExplainTopN++
	type outcome struct {
		run Run
		err error
	}
	results := make(chan outcome, 12)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < cap(results); i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			spec := first
			if i%2 == 1 {
				spec = second
			}
			run, err := s.CreateRun(ctx, scenario.ID, "concurrent-key", spec)
			results <- outcome{run: run, err: err}
		}(i)
	}
	close(start)
	wg.Wait()
	close(results)
	var id string
	succeeded, conflicted := 0, 0
	for result := range results {
		if errors.Is(result.err, planning.ErrRunSpecConflict) {
			conflicted++
			continue
		}
		if result.err != nil {
			t.Fatal(result.err)
		}
		succeeded++
		if id != "" && id != result.run.ID {
			t.Fatal("concurrent replay created distinct runs")
		}
		id = result.run.ID
	}
	if succeeded != 6 || conflicted != 6 {
		t.Fatalf("one configuration must win atomically: succeeded=%d conflicts=%d", succeeded, conflicted)
	}
	var count int
	if err := s.DB.QueryRow(ctx, `SELECT count(*) FROM runs`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("expected one durable run: count=%d err=%v", count, err)
	}
}

func TestRunSpecRetryPreservesFingerprintAndRejectsMutation(t *testing.T) {
	s := runSpecTestStore(t, false)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "retry", json.RawMessage(`{}`))
	if err != nil {
		t.Fatal(err)
	}
	run, err := s.CreateRun(ctx, scenario.ID, "retry-key", testRunSpec(t, scenario.Spec, true))
	if err != nil {
		t.Fatal(err)
	}
	first, err := s.Claim(ctx)
	if err != nil || first == nil || first.RunID != run.ID {
		t.Fatalf("claim: %+v %v", first, err)
	}
	if _, err := s.DB.Exec(ctx, `UPDATE runs SET lease_until=now()-interval '1 second' WHERE id=$1`, run.ID); err != nil {
		t.Fatal(err)
	}
	second, err := s.Claim(ctx)
	if err != nil || second == nil || second.AttemptID == first.AttemptID {
		t.Fatalf("retry claim: %+v %v", second, err)
	}
	if !reflect.DeepEqual(first.RunSpec, second.RunSpec) || second.ExecutionSHA256 != run.ExecutionSHA256 || second.ScenarioSHA256 != scenario.SHA256 || second.RunSpecSHA256 != run.RunSpecSHA256 || string(second.Spec) != string(scenario.Spec) {
		t.Fatalf("retry changed its execution: first=%+v second=%+v", first, second)
	}
	for _, update := range []string{
		`run_spec=jsonb_set(run_spec,'{solver_seconds}','999')`,
		`scenario_sha256=repeat('a',64)`,
		`run_spec_sha256=repeat('a',64)`,
		`execution_sha256=repeat('a',64)`,
		`run_spec_origin='legacy_inferred'`,
		`idempotency_key='rewritten-key'`,
	} {
		if _, err := s.DB.Exec(ctx, `UPDATE runs SET `+update+` WHERE id=$1`, run.ID); err == nil {
			t.Fatalf("accepted mutation of immutable run: %s", update)
		}
	}
	if _, err := s.DB.Exec(ctx, `UPDATE scenarios SET spec='{"changed":true}' WHERE id=$1`, scenario.ID); err == nil {
		t.Fatal("accepted mutation of a claimed scenario")
	}
	// A consistent but unrelated pair of hashes must not be accepted on insert.
	if _, err := s.DB.Exec(ctx, `INSERT INTO runs(id,scenario_id,idempotency_key,state,run_spec,scenario_sha256,run_spec_sha256,execution_sha256,run_spec_origin)
        SELECT gen_random_uuid(),scenario_id,'forged-snapshot','queued',run_spec,repeat('a',64),run_spec_sha256,
          encode(sha256(convert_to(repeat('a',64) || E'\n' || run_spec_sha256,'UTF8')),'hex'),'resolved'
        FROM runs WHERE id=$1`, run.ID); err == nil {
		t.Fatal("accepted a run referencing the wrong scenario digest")
	}
	if ok, err := s.Finish(ctx, *first, json.RawMessage(`{"stale":true}`), "", ""); err != nil || ok {
		t.Fatalf("expired attempt published: %v %v", ok, err)
	}
	if ok, err := s.Finish(ctx, *second, json.RawMessage(`{"fresh":true}`), "", ""); err != nil || !ok {
		t.Fatalf("current attempt could not publish: %v %v", ok, err)
	}
}

func TestScenarioSnapshotCannotChangeNumericRepresentationOrDigest(t *testing.T) {
	s := runSpecTestStore(t, false)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "numeric snapshot", json.RawMessage(`{"number":1.0}`))
	if err != nil {
		t.Fatal(err)
	}
	for _, update := range []string{
		`spec='{"number":1}'::jsonb`,
		`spec_sha256=repeat('0',64)`,
		`spec='{"number":1}'::jsonb,spec_sha256=encode(sha256(convert_to('{"number":1}'::jsonb::text,'UTF8')),'hex')`,
	} {
		if _, err := s.DB.Exec(ctx, `UPDATE scenarios SET `+update+` WHERE id=$1`, scenario.ID); err == nil {
			t.Fatalf("accepted snapshot mutation: %s", update)
		}
	}
	if _, err := s.DB.Exec(ctx, `INSERT INTO scenarios(id,name,spec,spec_sha256)
        VALUES(gen_random_uuid(),'invalid checksum','{}',repeat('0',64))`); err == nil {
		t.Fatal("accepted a scenario with an invalid checksum")
	}
}

func TestRunSpecMigrationBackfillsWithoutRewritingHistoricalResults(t *testing.T) {
	s := runSpecTestStore(t, true)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "old run", json.RawMessage(`{"parameters":{"solver_seconds":185,"simulation_days":7}}`))
	if err != nil {
		t.Fatal(err)
	}
	var id string
	var oldResult json.RawMessage
	err = s.DB.QueryRow(ctx, `INSERT INTO runs(id,scenario_id,idempotency_key,state,result)
        VALUES(gen_random_uuid(),$1,'legacy-key','succeeded','{"old":true,"evidence":{"seed":1}}')
        RETURNING id::text,result`, scenario.ID).Scan(&id, &oldResult)
	if err != nil {
		t.Fatal(err)
	}
	if err := migrate.Apply(ctx, s.DB, os.DirFS("../../migrations")); err != nil {
		t.Fatal(err)
	}
	if err := migrate.Apply(ctx, s.DB, os.DirFS("../../migrations")); err != nil {
		t.Fatalf("repeat migration changed the database: %v", err)
	}
	run, err := s.GetRun(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if run.RunSpecOrigin != "legacy_inferred" || !reflect.DeepEqual(run.RunSpec, testRunSpec(t, scenario.Spec, false)) {
		t.Fatalf("historical provenance or controls misrepresented: %+v", run)
	}
	assertRunSpecHash(t, s, run)
	result, err := s.Result(ctx, id)
	if err != nil || string(result) != string(oldResult) {
		t.Fatalf("historical result modified: %s %v", result, err)
	}
	replay, err := s.CreateRun(ctx, scenario.ID, "legacy-key")
	if err != nil || replay.ID != id || replay.RunSpecOrigin != "legacy_inferred" {
		t.Fatalf("historical replay must retain inferred origin: %+v %v", replay, err)
	}
	if strings.Contains(string(result), "run_spec") {
		t.Fatal("migration fabricated historical run evidence")
	}
}

func TestRunSpecBackfillMatchesLegacyIntegerCoercions(t *testing.T) {
	s := runSpecTestStore(t, true)
	ctx := context.Background()
	cases := []struct {
		spec   string
		solver int
		days   int
		runID  string
	}{
		{spec: `{}`, solver: 60, days: 3},
		{spec: `{"parameters":{"solver_seconds":15.0,"simulation_days":"5"}}`, solver: 15, days: 5},
		{spec: `{"parameters":{"solver_seconds":true,"simulation_days":true}}`, solver: 1, days: 1},
	}
	for i := range cases {
		scenario, err := s.CreateScenario(ctx, "old coercions", json.RawMessage(cases[i].spec))
		if err != nil {
			t.Fatal(err)
		}
		if err := s.DB.QueryRow(ctx, `INSERT INTO runs(id,scenario_id,idempotency_key,state)
            VALUES(gen_random_uuid(),$1,'legacy-coercion','queued') RETURNING id::text`, scenario.ID).Scan(&cases[i].runID); err != nil {
			t.Fatal(err)
		}
	}
	if err := migrate.Apply(ctx, s.DB, os.DirFS("../../migrations")); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		run, err := s.GetRun(ctx, tc.runID)
		if err != nil || run.RunSpec.SolverSeconds != tc.solver || run.RunSpec.SimulationDays != tc.days || run.RunSpecOrigin != "legacy_inferred" {
			t.Fatalf("historical defaults for %s: %+v %v", tc.spec, run, err)
		}
		assertRunSpecHash(t, s, run)
	}
}
