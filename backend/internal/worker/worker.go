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
	ctx, cancel := context.WithTimeout(parent, 15*time.Minute)
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

func (w *Worker) calculate(ctx context.Context, spec json.RawMessage) (json.RawMessage, string, string) {
	payload, err := json.Marshal(struct {
		Input       json.RawMessage `json:"input"`
		Seeds       []int           `json:"simulation_seeds"`
		ExplainTopN int             `json:"explain_top_n"`
	}{Input: spec, Seeds: []int{1, 2, 3}, ExplainTopN: 3})
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
		client = &http.Client{Timeout: 15 * time.Minute}
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
	if body.Optimization.Status != "optimal" && body.Optimization.Status != "feasible" {
		return content, "optimization_" + body.Optimization.Status, "no feasible plan produced"
	}
	return content, "", ""
}
