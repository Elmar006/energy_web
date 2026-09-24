package worker

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestProcessingTimeoutCoversDeclaredSolverBudgetAndExplanations(t *testing.T) {
	for _, tc := range []struct {
		spec string
		want time.Duration
	}{
		{spec: `{}`, want: 14 * time.Minute},
		{spec: `{"parameters":{"solver_seconds":3600}}`, want: 4*time.Hour + 10*time.Minute},
		{spec: `{"parameters":{"solver_seconds":900}}`, want: 70 * time.Minute},
		{spec: `{"parameters":{"solver_seconds":99999}}`, want: 14 * time.Minute},
	} {
		if got := processingTimeout([]byte(tc.spec)); got != tc.want {
			t.Errorf("processingTimeout(%s) = %s, want %s", tc.spec, got, tc.want)
		}
	}
}

func TestCalculateDistinguishesInfeasibilityFromEngineFailure(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status string
		code   string
	}{
		{name: "feasible", status: "feasible", code: ""},
		{name: "infeasible", status: "infeasible", code: ""},
		{name: "solver error", status: "error", code: "optimization_error"},
		{name: "unknown status", status: "unknown", code: "engine_error"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"optimization":{"status":"` + tc.status + `"},"simulation":[]}`))
			}))
			defer server.Close()
			worker := Worker{EngineURL: server.URL}
			output, code, _ := worker.calculate(context.Background(), []byte(`{"id":"test"}`))
			if code != tc.code {
				t.Fatalf("code = %q, want %q", code, tc.code)
			}
			if tc.code == "" && !strings.Contains(string(output), `"status":"`+tc.status+`"`) {
				t.Fatalf("successful result was not preserved: %s", output)
			}
		})
	}
}

func TestCalculateRequestsBoundedComparableAlternatives(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Seeds                       []int     `json:"simulation_seeds"`
			AlternativeServiceFractions []float64 `json:"alternative_service_fractions"`
			AlternativeSolverSeconds    int       `json:"alternative_solver_seconds"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		if len(request.Seeds) != 3 || len(request.AlternativeServiceFractions) != 3 ||
			request.AlternativeServiceFractions[0] != 0 || request.AlternativeServiceFractions[1] != 0.5 ||
			request.AlternativeServiceFractions[2] != 1 || request.AlternativeSolverSeconds != 20 {
			t.Errorf("unexpected alternative calculation parameters: %+v", request)
		}
		_, _ = w.Write([]byte(`{"optimization":{"status":"optimal"},"simulation":[],"alternatives":[]}`))
	}))
	defer server.Close()
	worker := Worker{EngineURL: server.URL}
	_, code, detail := worker.calculate(context.Background(), []byte(`{"id":"test"}`))
	if code != "" {
		t.Fatalf("calculate failed: %s %s", code, detail)
	}
}
