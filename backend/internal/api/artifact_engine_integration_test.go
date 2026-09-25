package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/artifact"
	"github.com/Elmar006/energy_web/backend/internal/planning"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/Elmar006/energy_web/backend/internal/worker"
	"github.com/jackc/pgx/v5/pgxpool"
)

type completedArtifactRun struct {
	output json.RawMessage
	code   string
	detail string
}

func (*completedArtifactRun) Claim(context.Context) (*planning.Job, error) { return nil, nil }
func (*completedArtifactRun) Heartbeat(context.Context, string, string) (bool, error) {
	return true, nil
}
func (r *completedArtifactRun) Finish(_ context.Context, _ planning.Job, output json.RawMessage, code, detail string) (bool, error) {
	r.output, r.code, r.detail = output, code, detail
	return true, nil
}

// Run only against a local test database and a current Python engine. It
// crosses upload -> Go scenario validation/persistence -> worker hydration ->
// optimizer/simulator -> fenced-result contract without a fixture response.
func TestDemandArtifactAgainstRealEngine(t *testing.T) {
	dbURL, engineURL := os.Getenv("TEST_DATABASE_URL"), os.Getenv("TEST_ENGINE_URL")
	if dbURL == "" || engineURL == "" {
		t.Skip("TEST_DATABASE_URL and TEST_ENGINE_URL are required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	db, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	local := artifact.Local{Root: t.TempDir()}
	api := (Server{Store: &store.Store{DB: db}, Token: "dated-artifact-engine-test",
		EngineURL: engineURL, Artifacts: local}).Handler()
	doc, _ := json.Marshal(map[string]any{
		"schema_version": "demand-dataset-v1",
		"service_calendar": map[string]any{
			"schema_version": "service-calendar-v1", "time_zone": "Europe/Moscow",
			"covered_dates": []string{"2027-05-03"}, "request_zone_ids": []string{"z1"},
			"legacy_profile_zone_ids": []string{}, "annualization_factor": 365,
			"annualization_basis": "assumed_repeat",
		},
		"charging_requests": []any{map[string]any{
			"request_id": "v:1", "vehicle_id": "v", "segment": "private", "zone_id": "z1",
			"arrival_at": "2027-05-03T12:30:00+03:00", "deadline_at": "2027-05-03T13:30:00+03:00",
			"energy_from_charger_kwh": 10, "battery_kwh": 40, "soc_before_kwh": 0,
			"max_vehicle_kw": 20, "charging_efficiency": 1, "population_weight": 1,
			"provenance": map[string]any{"source": "assumed integration case", "kind": "assumed"},
		}},
	})
	upload := httptest.NewRequest(http.MethodPost, "/api/v1/artifacts/demand", bytes.NewReader(doc))
	upload.Header.Set("Authorization", "Bearer dated-artifact-engine-test")
	uploaded := httptest.NewRecorder()
	api.ServeHTTP(uploaded, upload)
	var manifest artifact.Manifest
	if uploaded.Code != 201 || json.Unmarshal(uploaded.Body.Bytes(), &manifest) != nil {
		t.Fatalf("upload failed: %d %s", uploaded.Code, uploaded.Body.String())
	}
	hourly := make([]int, 24)
	hourly[12] = 10
	flatTen, flatZero := make([]int, 24), make([]int, 24)
	for i := range flatTen {
		flatTen[i] = 10
	}
	provenance := map[string]any{"source": "assumed integration case", "kind": "assumed"}
	scenario, _ := json.Marshal(map[string]any{
		"id": "artifact-dated-integration", "time_zone": "Europe/Moscow", "demand_dataset": manifest,
		"zones": []any{map[string]any{"id": "z1", "name": "Zone", "latitude": 55, "longitude": 37,
			"hourly_kwh": hourly, "mean_session_kwh": 10, "max_travel_minutes": 20, "provenance": provenance}},
		"sites": []any{map[string]any{"id": "s1", "name": "Station", "latitude": 55, "longitude": 37,
			"grid_node_id": "g1", "option_ids": []string{"dc"}, "provenance": provenance}},
		"options": []any{map[string]any{"id": "dc", "ports": 1, "charger_kw": 10, "connection_kw": 10,
			"capex_rub": 1000, "annual_fixed_rub": 0}},
		"grid_nodes":   []any{map[string]any{"id": "g1", "headroom_kw": flatTen, "provenance": provenance}},
		"scenarios":    []any{map[string]any{"id": "base", "demand_multiplier": []int{1}}},
		"travel_edges": []any{map[string]any{"zone_id": "z1", "site_id": "s1", "minutes": 5}},
		"parameters": map[string]any{"mode": "city", "years": []int{2027},
			"annual_budgets_rub": []int{2000}, "total_budget_rub": 2000,
			"sale_rub_per_kwh": 20, "purchase_rub_per_kwh": 5,
			"discount_rate": 0.1, "pv_hourly_factor": flatZero, "solver_seconds": 15},
	})
	createBody, _ := json.Marshal(map[string]any{"name": "dated-artifact-engine-integration", "spec": json.RawMessage(scenario)})
	create := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios", bytes.NewReader(createBody))
	create.Header.Set("Authorization", "Bearer dated-artifact-engine-test")
	created := httptest.NewRecorder()
	api.ServeHTTP(created, create)
	var saved planning.Scenario
	if created.Code != 201 || json.Unmarshal(created.Body.Bytes(), &saved) != nil {
		t.Fatalf("real engine validation failed: %d %s", created.Code, created.Body.String())
	}
	t.Cleanup(func() {
		_, _ = db.Exec(context.Background(), `DELETE FROM scenarios WHERE id=$1::uuid`, saved.ID)
	})
	runSpec, err := planning.ResolveRunSpec(json.RawMessage(`{"simulation_seeds":[42],"simulation_days":1,"solver_seconds":15,"explain_top_n":0,"alternative_service_fractions":[]}`), saved.Spec)
	if err != nil {
		t.Fatal(err)
	}
	repo := &completedArtifactRun{}
	job := planning.Job{RunID: "test-run", AttemptID: "test-attempt", Spec: saved.Spec, RunSpec: runSpec,
		ScenarioSHA256: saved.SHA256, RunSpecSHA256: "test-run-spec", ExecutionSHA256: "test-execution"}
	(&worker.Worker{Store: repo, Artifacts: local, EngineURL: engineURL}).Process(ctx, job)
	if repo.code != "" || len(repo.output) == 0 {
		t.Fatalf("real engine calculation failed: %s %s", repo.code, repo.detail)
	}
	var result struct {
		Optimization struct {
			Status       string `json:"status"`
			Verification struct {
				Passed bool `json:"passed"`
			} `json:"verification"`
		} `json:"optimization"`
		Simulation []struct {
			DemandBasis string `json:"demand_basis"`
		} `json:"simulation"`
		Metadata struct {
			DemandSHA string `json:"demand_dataset_sha256"`
		} `json:"metadata"`
	}
	if json.Unmarshal(repo.output, &result) != nil || result.Optimization.Status != "optimal" ||
		!result.Optimization.Verification.Passed || len(result.Simulation) != 1 ||
		result.Simulation[0].DemandBasis != "dated_requests" || result.Metadata.DemandSHA != manifest.SHA256 {
		t.Fatalf("real engine did not calculate verified dated demand: %s", repo.output)
	}
}
