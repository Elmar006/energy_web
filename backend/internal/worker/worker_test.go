package worker

import (
	"context"
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
