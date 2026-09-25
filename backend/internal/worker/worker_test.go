package worker

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

func testJob(t *testing.T) planning.Job {
	t.Helper()
	spec, err := planning.ResolveRunSpec(nil, json.RawMessage("{}"))
	if err != nil {
		t.Fatal(err)
	}
	return planning.Job{
		RunID: "run", AttemptID: "attempt",
		Spec:    json.RawMessage(`{"id":"test","scenarios":[{"id":"base"}],"parameters":{"years":[2026]}}`),
		RunSpec: spec, ScenarioSHA256: "postgres-scenario", RunSpecSHA256: "postgres-options",
		ExecutionSHA256: "postgres-execution",
	}
}

func engineResult(t *testing.T, job planning.Job, status string) []byte {
	t.Helper()
	simulations := make([]any, 0, len(job.RunSpec.SimulationSeeds))
	if status == "optimal" || status == "feasible" {
		for _, seed := range job.RunSpec.SimulationSeeds {
			simulations = append(simulations, map[string]any{
				"scenario_id": "base", "year": 2026, "seed": seed,
				"simulation_days":       job.RunSpec.SimulationDays,
				"dispatch_verification": map[string]any{"passed": true},
			})
		}
	}
	body, err := json.Marshal(map[string]any{
		"optimization": map[string]any{"status": status, "verification": map[string]any{"passed": true}},
		"metadata": map[string]any{
			"run_spec": job.RunSpec, "configuration_source": "run_spec",
			"input_sha256": "python-input", "scenario_snapshot_sha256": "untrusted-engine-value",
		},
		"simulation": simulations, "alternatives": []any{},
	})
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func TestProcessingTimeoutCoversEffectiveBudgets(t *testing.T) {
	for _, tc := range []struct {
		name string
		raw  string
		want time.Duration
	}{
		{"defaults", "{}", 15 * time.Minute},
		{"full primary budget", "{\"solver_seconds\":3600}", 4*time.Hour + 11*time.Minute},
		{"custom counts", "{\"solver_seconds\":900,\"explain_top_n\":2,\"alternative_service_fractions\":[0,1],\"alternative_solver_seconds\":30}", 56 * time.Minute},
		{"no auxiliary solves", "{\"solver_seconds\":123,\"explain_top_n\":0,\"alternative_service_fractions\":[]}", 723 * time.Second},
		{"maximum solve count", "{\"solver_seconds\":3600,\"explain_top_n\":10,\"alternative_service_fractions\":[0,0.25,0.5,0.75,1],\"alternative_solver_seconds\":60}", 11*time.Hour + 15*time.Minute},
	} {
		t.Run(tc.name, func(t *testing.T) {
			spec, err := planning.ResolveRunSpec(json.RawMessage(tc.raw), nil)
			if err != nil {
				t.Fatal(err)
			}
			if got := processingTimeout(spec); got != tc.want {
				t.Errorf("processingTimeout = %s, want %s", got, tc.want)
			}
		})
	}
}

func TestCalculatePreservesEffectiveRunSpecAndSnapshotIdentity(t *testing.T) {
	job := testJob(t)
	job.RunSpec.Mode = "validation"
	job.RunSpec.SimulationSeeds = make([]int, 30)
	for i := range job.RunSpec.SimulationSeeds {
		job.RunSpec.SimulationSeeds[i] = 100 + i
	}
	job.RunSpec.ExplainTopN = 0
	job.RunSpec.AlternativeServiceFractions = []float64{}
	job.RunSpec.SolverSeconds = 321
	job.RunSpec.SimulationDays = 7
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/calculate" || r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("wrong request: %s %s %s", r.Method, r.URL.Path, r.Header.Get("Content-Type"))
		}
		requestBody, _ := io.ReadAll(r.Body)
		var request map[string]json.RawMessage
		if err := json.Unmarshal(requestBody, &request); err != nil {
			t.Error(err)
		}
		if len(request) != 2 || !matchesRunSpec(request["run_spec"], job.RunSpec) ||
			!reflect.DeepEqual(request["input"], job.Spec) {
			t.Errorf("request changed persisted inputs: %s", request)
		}
		_, _ = w.Write(bindEngineResult(engineResult(t, job, "optimal"), requestBody))
	}))
	defer server.Close()
	worker := Worker{EngineURL: server.URL}
	output, code, detail := worker.calculate(context.Background(), job)
	if code != "" {
		t.Fatalf("calculate failed: %s %s", code, detail)
	}
	var result struct {
		Metadata map[string]json.RawMessage
	}
	if err := json.Unmarshal(output, &result); err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]string{
		"input_sha256":             "python-input",
		"scenario_snapshot_sha256": job.ScenarioSHA256,
		"run_spec_sha256":          job.RunSpecSHA256,
		"execution_sha256":         job.ExecutionSHA256,
	} {
		var got string
		_ = json.Unmarshal(result.Metadata[key], &got)
		if got != want {
			t.Errorf("%s = %s, want %s", key, got, want)
		}
	}
	if !matchesRunSpec(result.Metadata["run_spec"], job.RunSpec) {
		t.Fatal("result run_spec changed")
	}
}

func TestCalculateDistinguishesInfeasibilityFromEngineFailure(t *testing.T) {
	for _, tc := range []struct {
		status string
		code   string
	}{
		{"optimal", ""}, {"feasible", ""}, {"infeasible", ""},
		{"error", "optimization_error"}, {"unknown", "engine_error"},
	} {
		t.Run(tc.status, func(t *testing.T) {
			job := testJob(t)
			worker := responseWorker(http.StatusOK, engineResult(t, job, tc.status))
			output, code, _ := worker.calculate(context.Background(), job)
			if code != tc.code {
				t.Fatalf("code = %q, want %q", code, tc.code)
			}
			if tc.code == "" && !strings.Contains(string(output), "\"status\":\""+tc.status+"\"") {
				t.Fatalf("planning answer was not preserved: %s", output)
			}
		})
	}
}

func TestCalculateRejectsIncorrectEngineContract(t *testing.T) {
	for _, tc := range []struct {
		name string
		edit func(map[string]any, map[string]any, map[string]any)
	}{
		{"missing metadata", func(body, _, _ map[string]any) { delete(body, "metadata") }},
		{"null metadata", func(body, _, _ map[string]any) { body["metadata"] = nil }},
		{"missing source", func(_, meta, _ map[string]any) { delete(meta, "configuration_source") }},
		{"legacy source", func(_, meta, _ map[string]any) { meta["configuration_source"] = "legacy" }},
		{"missing run spec", func(_, meta, _ map[string]any) { delete(meta, "run_spec") }},
		{"wrong model", func(_, _, spec map[string]any) { spec["model_version"] = "wrong" }},
		{"wrong days", func(_, _, spec map[string]any) { spec["simulation_days"] = 9 }},
		{"wrong seeds", func(_, _, spec map[string]any) { spec["simulation_seeds"] = []int{5} }},
		{"omitted zero", func(_, _, spec map[string]any) { delete(spec, "explain_top_n") }},
		{"null alternatives", func(_, _, spec map[string]any) { spec["alternative_service_fractions"] = nil }},
		{"unexpected field", func(_, _, spec map[string]any) { spec["hidden_override"] = true }},
		{"wrong request SHA", func(_, meta, _ map[string]any) { meta["engine_request_sha256"] = strings.Repeat("0", 64) }},
		{"missing simulations", func(body, _, _ map[string]any) { delete(body, "simulation") }},
		{"incomplete simulations", func(body, _, _ map[string]any) {
			body["simulation"] = body["simulation"].([]any)[:1]
		}},
		{"duplicate simulation", func(body, _, _ map[string]any) {
			sims := body["simulation"].([]any)
			sims[1] = sims[0]
		}},
		{"wrong simulation days", func(body, _, _ map[string]any) {
			body["simulation"].([]any)[0].(map[string]any)["simulation_days"] = 14
		}},
		{"null simulation seed", func(body, _, _ map[string]any) {
			body["simulation"].([]any)[0].(map[string]any)["seed"] = nil
		}},
		{"failed dispatch verification", func(body, _, _ map[string]any) {
			body["simulation"].([]any)[0].(map[string]any)["dispatch_verification"].(map[string]any)["passed"] = false
		}},
		{"failed optimizer verification", func(body, _, _ map[string]any) {
			body["optimization"].(map[string]any)["verification"].(map[string]any)["passed"] = false
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			job := testJob(t)
			job.RunSpec.ExplainTopN = 0
			job.RunSpec.SimulationSeeds = []int{0, 1, 2}
			job.RunSpec.AlternativeServiceFractions = []float64{}
			var body map[string]any
			if err := json.Unmarshal(engineResult(t, job, "optimal"), &body); err != nil {
				t.Fatal(err)
			}
			meta := body["metadata"].(map[string]any)
			tc.edit(body, meta, meta["run_spec"].(map[string]any))
			content, err := json.Marshal(body)
			if err != nil {
				t.Fatal(err)
			}
			worker := responseWorker(http.StatusOK, content)
			output, code, _ := worker.calculate(context.Background(), job)
			if code != "engine_contract_error" || output != nil {
				t.Fatalf("incorrect contract accepted: code=%q output=%s", code, output)
			}
		})
	}
}

func TestCalculateRejectsInvalidPersistedRunSpecWithoutCallingEngine(t *testing.T) {
	job := testJob(t)
	job.RunSpec = planning.RunSpec{}
	called := false
	worker := Worker{EngineURL: "http://engine", Client: &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		called = true
		return nil, errors.New("must not be called")
	})}}
	_, code, _ := worker.calculate(context.Background(), job)
	if code != "invalid_run_spec" || called {
		t.Fatalf("code=%s engine called=%t", code, called)
	}
}

func TestCalculateTransportAndResponseErrors(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status int
		body   string
		want   string
	}{
		{"HTTP 503", http.StatusServiceUnavailable, "unavailable", "engine_error"},
		{"broken JSON", http.StatusOK, "{", "engine_error"},
		{"JSON null", http.StatusOK, "null", "engine_error"},
		{"JSON array", http.StatusOK, "[]", "engine_error"},
		{"missing optimization", http.StatusOK, "{}", "engine_error"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			worker := responseWorker(tc.status, []byte(tc.body))
			_, code, _ := worker.calculate(context.Background(), testJob(t))
			if code != tc.want {
				t.Fatalf("code=%s, want %s", code, tc.want)
			}
		})
	}
	t.Run("unavailable", func(t *testing.T) {
		worker := Worker{EngineURL: "http://engine", Client: &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			return nil, errors.New("connection refused")
		})}}
		_, code, _ := worker.calculate(context.Background(), testJob(t))
		if code != "engine_unavailable" {
			t.Fatalf("code=%s", code)
		}
	})
	t.Run("body read failure", func(t *testing.T) {
		worker := Worker{EngineURL: "http://engine", Client: &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(failedReader{})}, nil
		})}}
		_, code, _ := worker.calculate(context.Background(), testJob(t))
		if code != "engine_error" {
			t.Fatalf("code=%s", code)
		}
	})
}

func TestCalculateDoesNotTruncateOversizedResults(t *testing.T) {
	job := testJob(t)
	content := string(engineResult(t, job, "optimal"))
	// Even valid JSON followed by excess whitespace must be rejected.
	content += strings.Repeat(" ", maxResultBytes+1-len(content))
	worker := Worker{EngineURL: "http://engine", Client: &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(content))}, nil
	})}}
	output, code, _ := worker.calculate(context.Background(), job)
	if code != "result_too_large" || output != nil {
		t.Fatalf("oversized response was accepted: code=%s", code)
	}
}

func TestCalculateDistinguishesDeadlineFromCancellation(t *testing.T) {
	for _, tc := range []struct {
		name    string
		context func() (context.Context, context.CancelFunc)
		want    string
	}{
		{"cancelled", func() (context.Context, context.CancelFunc) {
			ctx, cancel := context.WithCancel(context.Background())
			cancel()
			return ctx, cancel
		}, "engine_cancelled"},
		{"deadline", func() (context.Context, context.CancelFunc) {
			return context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
		}, "engine_timeout"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ctx, cancel := tc.context()
			defer cancel()
			worker := Worker{EngineURL: "http://engine", Client: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
				<-r.Context().Done()
				return nil, r.Context().Err()
			})}}
			_, code, _ := worker.calculate(ctx, testJob(t))
			if code != tc.want {
				t.Fatalf("code=%s, want %s", code, tc.want)
			}
		})
	}
}

func TestProcessAbandonsLostOrUncertainLease(t *testing.T) {
	for _, tc := range []struct {
		name string
		err  error
	}{
		{"lost lease", nil},
		{"temporary database failure", errors.New("connection reset")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var heartbeats atomic.Int32
			requestStarted := make(chan struct{})
			repo := &fakeRepository{
				heartbeat: func(ctx context.Context, runID, attemptID string) (bool, error) {
					select {
					case <-requestStarted:
					case <-ctx.Done():
						return false, ctx.Err()
					}
					if runID != "run" || attemptID != "attempt" {
						t.Errorf("wrong fencing token: %s/%s", runID, attemptID)
					}
					heartbeats.Add(1)
					return false, tc.err
				},
			}
			worker := Worker{Store: repo, EngineURL: "http://engine", heartbeatInterval: time.Millisecond,
				Client: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
					close(requestStarted)
					<-r.Context().Done()
					return nil, r.Context().Err()
				})},
			}
			parent, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			worker.Process(parent, testJob(t))
			if heartbeats.Load() != 1 || repo.finishes != 0 {
				t.Fatalf("heartbeats=%d finishes=%d", heartbeats.Load(), repo.finishes)
			}
		})
	}
}

func TestProcessParentShutdownDoesNotPublishFailure(t *testing.T) {
	for _, deadline := range []bool{false, true} {
		name := "cancel"
		if deadline {
			name = "deadline"
		}
		t.Run(name, func(t *testing.T) {
			parent, cancel := context.WithCancel(context.Background())
			if deadline {
				cancel()
				parent, cancel = context.WithTimeout(context.Background(), 20*time.Millisecond)
			}
			defer cancel()
			repo := &fakeRepository{}
			worker := Worker{Store: repo, EngineURL: "http://engine",
				Client: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
					if !deadline {
						cancel()
					}
					<-r.Context().Done()
					return nil, r.Context().Err()
				})},
			}
			worker.Process(parent, testJob(t))
			if repo.finishes != 0 {
				t.Fatalf("shutdown published a result: %d", repo.finishes)
			}
		})
	}
}

func TestProcessPublishesValidResultWithAttemptFencing(t *testing.T) {
	for _, accepted := range []bool{true, false} {
		job := testJob(t)
		repo := &fakeRepository{accepted: accepted}
		worker := responseWorker(http.StatusOK, engineResult(t, job, "infeasible"))
		worker.Store = repo
		worker.Process(context.Background(), job)
		if repo.finishes != 1 || repo.lastCode != "" || repo.lastJob.AttemptID != job.AttemptID ||
			!strings.Contains(string(repo.lastOutput), "\"status\":\"infeasible\"") {
			t.Fatalf("incorrect finish: %+v", repo)
		}
	}
}

func TestProcessInvalidRunSpecPublishesExplicitFailure(t *testing.T) {
	repo := &fakeRepository{accepted: true}
	job := testJob(t)
	job.RunSpec = planning.RunSpec{}
	worker := Worker{Store: repo}
	worker.Process(context.Background(), job)
	if repo.finishes != 1 || repo.lastCode != "invalid_run_spec" || repo.lastOutput != nil {
		t.Fatalf("incorrect finish: %+v", repo)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func bindEngineResult(body, requestBody []byte) []byte {
	var result map[string]any
	if json.Unmarshal(body, &result) != nil {
		return body
	}
	metadata, ok := result["metadata"].(map[string]any)
	if !ok {
		return body
	}
	if _, exists := metadata["engine_request_sha256"]; !exists {
		sum := sha256.Sum256(requestBody)
		metadata["engine_request_sha256"] = fmt.Sprintf("%x", sum)
	}
	bound, err := json.Marshal(result)
	if err != nil {
		return body
	}
	return bound
}

func responseWorker(status int, body []byte) Worker {
	return Worker{EngineURL: "http://engine", Client: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		requestBody, _ := io.ReadAll(r.Body)
		content := bindEngineResult(body, requestBody)
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(string(content)))}, nil
	})}}
}

type failedReader struct{}

func (failedReader) Read([]byte) (int, error) { return 0, errors.New("interrupted response") }

type fakeRepository struct {
	heartbeat  func(context.Context, string, string) (bool, error)
	accepted   bool
	finishes   int
	lastJob    planning.Job
	lastOutput json.RawMessage
	lastCode   string
}

func (*fakeRepository) Claim(context.Context) (*planning.Job, error) { return nil, nil }
func (f *fakeRepository) Heartbeat(ctx context.Context, runID, attemptID string) (bool, error) {
	if f.heartbeat != nil {
		return f.heartbeat(ctx, runID, attemptID)
	}
	return true, nil
}
func (f *fakeRepository) Finish(_ context.Context, job planning.Job, output json.RawMessage, code, _ string) (bool, error) {
	f.finishes++
	f.lastJob, f.lastOutput, f.lastCode = job, output, code
	return f.accepted, nil
}

func TestServiceAcceptanceMustBeBoundToRequirementsAndCoverConditions(t *testing.T) {
	job := testJob(t)
	job.RunSpec.ServiceRequirements = json.RawMessage(`{"min_energy_fraction":0.9}`)
	good := json.RawMessage(`{"status":"accepted","reason":"all_conditions_met","requirements":{"schema_version":"service-v1","min_energy_fraction":0.9,"min_seeds_per_condition":30},"conditions":[{"scenario_id":"base","year":2026,"status":"accepted"}]}`)
	if err := verifyServiceAcceptance(good, job, "optimal"); err != nil {
		t.Fatalf("complete acceptance rejected: %v", err)
	}
	for _, raw := range []string{
		`{}`,
		`{"status":"not_evaluated","reason":"disabled"}`,
		`{"status":"accepted","reason":"all_conditions_met","requirements":{"min_energy_fraction":0.8},"conditions":[{"scenario_id":"base","year":2026,"status":"accepted"}]}`,
		`{"status":"accepted","reason":"all_conditions_met","requirements":{"min_energy_fraction":0.9},"conditions":[]}`,
		`{"status":"accepted","reason":"all_conditions_met","requirements":{"min_energy_fraction":0.9},"conditions":[{"scenario_id":"other","year":2026,"status":"accepted"}]}`,
	} {
		if err := verifyServiceAcceptance(json.RawMessage(raw), job, "optimal"); err == nil {
			t.Errorf("invalid assessment was accepted: %s", raw)
		}
	}
	if err := verifyServiceAcceptance(good, job, "infeasible"); err == nil {
		t.Fatal("infeasible optimization was accepted")
	}
}
