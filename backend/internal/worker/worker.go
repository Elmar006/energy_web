package worker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/store"
)

type Worker struct {
	Store     *store.Store
	EngineURL string
	Client    *http.Client
}

func (w *Worker) Run(ctx context.Context) error {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		job, err := w.Store.Claim(ctx)
		if err != nil {
			slog.Error("claim failed", "error", err)
		} else if job != nil {
			w.Process(ctx, *job)
			continue
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}

func (w *Worker) Process(parent context.Context, job store.Job) {
	ctx, cancel := context.WithTimeout(parent, processingTimeout(job.Spec))
	defer cancel()
	heartbeatDone := make(chan struct{})
	go func() {
		ticker := time.NewTicker(10 * time.Second)
		defer ticker.Stop()
		defer close(heartbeatDone)
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				alive, err := w.Store.Heartbeat(ctx, job.RunID, job.AttemptID)
				if err != nil {
					slog.Error("heartbeat failed", "run", job.RunID, "error", err)
					cancel()
					return
				}
				if !alive {
					cancel()
					return
				}
			}
		}
	}()
	output, code, detail := w.calculate(ctx, job.Spec)
	cancel()
	<-heartbeatDone
	if errors.Is(parent.Err(), context.Canceled) {
		return
	}
	done, err := w.Store.Finish(context.Background(), job, output, code, detail)
	if err != nil {
		slog.Error("finish failed", "run", job.RunID, "error", err)
		return
	}
	if !done {
		slog.Info("stale or cancelled attempt discarded", "run", job.RunID)
		return
	}
	slog.Info("run completed", "run", job.RunID, "status", code)
}

func processingTimeout(spec json.RawMessage) time.Duration {
	var input struct {
		Parameters struct {
			SolverSeconds int `json:"solver_seconds"`
		} `json:"parameters"`
	}
	seconds := 60 // Python model default.
	if json.Unmarshal(spec, &input) == nil && input.Parameters.SolverSeconds >= 1 && input.Parameters.SolverSeconds <= 3600 {
		seconds = input.Parameters.SolverSeconds
	}
	// One primary optimization and up to three counterfactual re-solves.
	// Three alternatives use at most 20 solver seconds each, covered by the
	// additional ten minutes together with simulation and serialization.
	return time.Duration(4*seconds)*time.Second + 10*time.Minute
}

func (w *Worker) calculate(ctx context.Context, spec json.RawMessage) (json.RawMessage, string, string) {
	payload, err := json.Marshal(struct {
		Input                       json.RawMessage `json:"input"`
		Seeds                       []int           `json:"simulation_seeds"`
		ExplainTopN                 int             `json:"explain_top_n"`
		AlternativeServiceFractions []float64       `json:"alternative_service_fractions"`
		AlternativeSolverSeconds    int             `json:"alternative_solver_seconds"`
	}{Input: spec, Seeds: []int{1, 2, 3}, ExplainTopN: 3,
		AlternativeServiceFractions: []float64{0, 0.5, 1}, AlternativeSolverSeconds: 20})
	if err != nil {
		return nil, "invalid_input", err.Error()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, w.EngineURL+"/v1/calculate", bytes.NewReader(payload))
	if err != nil {
		return nil, "engine_error", err.Error()
	}
	req.Header.Set("Content-Type", "application/json")
	client := w.Client
	if client == nil {
		// The per-run context already applies the computation budget. A fixed
		// client timeout would silently undercut valid solver_seconds values.
		client = &http.Client{}
	}
	response, err := client.Do(req)
	if err != nil {
		return nil, "engine_unavailable", err.Error()
	}
	defer response.Body.Close()
	content, err := io.ReadAll(io.LimitReader(response.Body, 16<<20))
	if err != nil {
		return nil, "engine_error", err.Error()
	}
	if response.StatusCode != 200 {
		return nil, "engine_error", fmt.Sprintf("engine HTTP %d: %s", response.StatusCode, string(content))
	}
	if !json.Valid(content) {
		return nil, "engine_error", "engine returned invalid JSON"
	}
	var body struct {
		Optimization struct {
			Status string `json:"status"`
		} `json:"optimization"`
	}
	if err := json.Unmarshal(content, &body); err != nil {
		return nil, "engine_error", err.Error()
	}
	switch body.Optimization.Status {
	case "optimal", "feasible", "infeasible":
		// Infeasibility is a valid answer to a planning question. Preserve the
		// solver diagnostic as a result instead of losing it as a worker error.
		return content, "", ""
	case "error":
		return content, "optimization_error", "optimizer did not produce a result"
	default:
		return nil, "engine_error", "engine returned an unknown optimization status"
	}
}
