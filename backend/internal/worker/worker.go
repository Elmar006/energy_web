package worker

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"reflect"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

const maxResultBytes = 16 << 20

// Repository fences every mutation by the current run attempt. A lost lease
// must never allow an old worker to publish over a replacement attempt.
type Repository interface {
	Claim(context.Context) (*planning.Job, error)
	Heartbeat(context.Context, string, string) (bool, error)
	Finish(context.Context, planning.Job, json.RawMessage, string, string) (bool, error)
}

type Worker struct {
	Store     Repository
	EngineURL string
	Client    *http.Client

	// Tests may shorten the interval without changing production lease timing.
	heartbeatInterval time.Duration
}

func (w *Worker) Run(ctx context.Context) error {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
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

func (w *Worker) Process(parent context.Context, job planning.Job) {
	if parent.Err() != nil {
		return
	}
	if err := job.RunSpec.Validate(); err != nil {
		w.finish(parent, job, nil, "invalid_run_spec", err.Error())
		return
	}
	ctx, cancel := context.WithTimeout(parent, processingTimeout(job.RunSpec))
	defer cancel()
	heartbeatDone := make(chan struct{})
	leaseLost := false // Read only after heartbeatDone closes.
	interval := w.heartbeatInterval
	if interval <= 0 {
		interval = 10 * time.Second
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		defer close(heartbeatDone)
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				alive, err := w.Store.Heartbeat(ctx, job.RunID, job.AttemptID)
				if err != nil {
					if ctx.Err() != nil && (errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded)) {
						return
					}
					slog.Error("heartbeat failed", "run", job.RunID, "error", err)
					leaseLost = true
					cancel()
					return
				}
				if !alive {
					leaseLost = true
					cancel()
					return
				}
			}
		}
	}()
	output, code, detail := w.calculate(ctx, job)
	cancel()
	<-heartbeatDone
	// On shutdown or uncertain ownership leave the attempt for cancellation or
	// lease recovery. In particular, a transient heartbeat error is not an
	// engine failure and must not turn a retryable attempt into a failed run.
	if parent.Err() != nil || leaseLost {
		return
	}
	w.finish(parent, job, output, code, detail)
}

func (w *Worker) finish(parent context.Context, job planning.Job, output json.RawMessage, code, detail string) {
	if parent.Err() != nil {
		return
	}
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	done, err := w.Store.Finish(ctx, job, output, code, detail)
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

func processingTimeout(spec planning.RunSpec) time.Duration {
	// This is a worker HTTP wait budget, not an isolated process kill or a
	// guarantee that a configured solver time limit bounds model construction.
	// Allow each primary/counterfactual solve, every requested alternative, and
	// ten extra minutes for simulation, model construction and serialization.
	seconds := (1+spec.ExplainTopN)*spec.SolverSeconds +
		len(spec.AlternativeServiceFractions)*spec.AlternativeSolverSeconds + 600
	return time.Duration(seconds) * time.Second
}

func (w *Worker) calculate(ctx context.Context, job planning.Job) (json.RawMessage, string, string) {
	if err := job.RunSpec.Validate(); err != nil {
		return nil, "invalid_run_spec", err.Error()
	}
	payload, err := json.Marshal(struct {
		Input   json.RawMessage  `json:"input"`
		RunSpec planning.RunSpec `json:"run_spec"`
	}{Input: job.Spec, RunSpec: job.RunSpec})
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
		// The effective RunSpec controls the context deadline; a fixed client
		// timeout would silently undercut valid solver budgets.
		client = &http.Client{}
	}
	response, err := client.Do(req)
	if err != nil {
		return nil, transportErrorCode(ctx, err, "engine_unavailable"), err.Error()
	}
	defer response.Body.Close()
	content, err := io.ReadAll(io.LimitReader(response.Body, maxResultBytes+1))
	if err != nil {
		return nil, transportErrorCode(ctx, err, "engine_error"), err.Error()
	}
	if len(content) > maxResultBytes {
		return nil, "result_too_large", "engine response exceeds the 16 MiB result limit"
	}
	if response.StatusCode != http.StatusOK {
		return nil, "engine_error", fmt.Sprintf("engine HTTP %d: %s", response.StatusCode, string(content))
	}
	var body map[string]json.RawMessage
	if err := json.Unmarshal(content, &body); err != nil || body == nil {
		return nil, "engine_error", "engine returned an invalid JSON object"
	}
	var optimization struct {
		Status       string `json:"status"`
		Verification struct {
			Passed bool `json:"passed"`
		} `json:"verification"`
	}
	if err := json.Unmarshal(body["optimization"], &optimization); err != nil {
		return nil, "engine_error", "engine returned invalid optimization metadata"
	}
	switch optimization.Status {
	case "optimal", "feasible", "infeasible":
		// Infeasibility is a valid planning answer, provided it belongs to the
		// requested versioned calculation just like a feasible result.
	case "error":
		return content, "optimization_error", "optimizer did not produce a result"
	default:
		return nil, "engine_error", "engine returned an unknown optimization status"
	}
	var metadata map[string]json.RawMessage
	if err := json.Unmarshal(body["metadata"], &metadata); err != nil || metadata == nil {
		return nil, "engine_contract_error", "engine result is missing calculation metadata"
	}
	var source string
	if err := json.Unmarshal(metadata["configuration_source"], &source); err != nil || source != "run_spec" {
		return nil, "engine_contract_error", "engine result was not configured by run_spec"
	}
	if !matchesRunSpec(metadata["run_spec"], job.RunSpec) {
		return nil, "engine_contract_error", "engine effective run_spec does not match the persisted run_spec"
	}
	requestSum := sha256.Sum256(payload)
	var reportedRequestSHA string
	if err := json.Unmarshal(metadata["engine_request_sha256"], &reportedRequestSHA); err != nil ||
		reportedRequestSHA != fmt.Sprintf("%x", requestSum) {
		return nil, "engine_contract_error", "engine result is not bound to the submitted request"
	}
	if err := verifyResultCoverage(body["simulation"], job, optimization.Status, optimization.Verification.Passed); err != nil {
		return nil, "engine_contract_error", err.Error()
	}
	// These are hashes of the immutable PostgreSQL snapshots. The engine's
	// input_sha256 uses Python canonicalization and is preserved separately.
	for key, value := range map[string]string{
		"scenario_snapshot_sha256": job.ScenarioSHA256,
		"run_spec_sha256":          job.RunSpecSHA256,
		"execution_sha256":         job.ExecutionSHA256,
	} {
		metadata[key], _ = json.Marshal(value)
	}
	body["metadata"], _ = json.Marshal(metadata)
	output, err := json.Marshal(body)
	if err != nil {
		return nil, "engine_error", err.Error()
	}
	if len(output) > maxResultBytes {
		return nil, "result_too_large", "engine result with snapshot metadata exceeds the 16 MiB result limit"
	}
	return output, "", ""
}

// verifyResultCoverage prevents a nominally successful 200 response from
// becoming a successful run when whole seeds, years or scenarios are absent.
// It does not claim that service thresholds were met: those require a separate
// acceptance model and are currently reported as not_evaluated by the engine.
func verifyResultCoverage(raw json.RawMessage, job planning.Job, status string, physicallyValid bool) error {
	var simulations []struct {
		ScenarioID *string `json:"scenario_id"`
		Year       *int    `json:"year"`
		Seed       *int    `json:"seed"`
		Days       *int    `json:"simulation_days"`
		Dispatch   struct {
			Passed *bool `json:"passed"`
		} `json:"dispatch_verification"`
	}
	if err := json.Unmarshal(raw, &simulations); err != nil || simulations == nil {
		return errors.New("engine result is missing the simulation list")
	}
	if status == "infeasible" {
		if len(simulations) != 0 {
			return errors.New("infeasible result must not claim completed simulations")
		}
		return nil
	}
	if !physicallyValid {
		return errors.New("optimizer result did not pass physical verification")
	}
	var input struct {
		Scenarios []struct {
			ID string `json:"id"`
		} `json:"scenarios"`
		Parameters struct {
			Years []int `json:"years"`
		} `json:"parameters"`
	}
	if err := json.Unmarshal(job.Spec, &input); err != nil || len(input.Scenarios) == 0 || len(input.Parameters.Years) == 0 {
		return errors.New("persisted scenario has no years or demand scenarios")
	}
	ids := make(map[string]bool, len(input.Scenarios))
	for _, scenario := range input.Scenarios {
		if scenario.ID == "" || ids[scenario.ID] {
			return errors.New("persisted scenario has duplicate or missing scenario IDs")
		}
		ids[scenario.ID] = true
	}
	years := make(map[int]bool, len(input.Parameters.Years))
	for _, year := range input.Parameters.Years {
		if years[year] {
			return errors.New("persisted scenario has duplicate years")
		}
		years[year] = true
	}
	requestedSeeds := make(map[int]bool, len(job.RunSpec.SimulationSeeds))
	for _, seed := range job.RunSpec.SimulationSeeds {
		requestedSeeds[seed] = true
	}
	expected := int64(len(ids)) * int64(len(years)) * int64(len(requestedSeeds))
	if int64(len(simulations)) != expected {
		return fmt.Errorf("engine returned %d simulations; expected %d", len(simulations), expected)
	}
	type key struct {
		scenario string
		year     int
		seed     int
	}
	seen := make(map[key]bool, len(simulations))
	for _, simulation := range simulations {
		if simulation.ScenarioID == nil || simulation.Year == nil || simulation.Seed == nil ||
			simulation.Days == nil || simulation.Dispatch.Passed == nil {
			return errors.New("engine returned a simulation with missing identity or physical verification")
		}
		identity := key{*simulation.ScenarioID, *simulation.Year, *simulation.Seed}
		if !ids[identity.scenario] || !years[identity.year] || !requestedSeeds[identity.seed] || seen[identity] ||
			*simulation.Days != job.RunSpec.SimulationDays || !*simulation.Dispatch.Passed {
			return errors.New("engine returned a duplicate, unrequested or physically invalid simulation")
		}
		seen[identity] = true
	}
	return nil
}

func matchesRunSpec(raw json.RawMessage, spec planning.RunSpec) bool {
	expected, err := json.Marshal(spec)
	if err != nil {
		return false
	}
	var actualObject, expectedObject map[string]any
	if json.Unmarshal(raw, &actualObject) != nil || actualObject == nil ||
		json.Unmarshal(expected, &expectedObject) != nil {
		return false
	}
	// Compare all fields, including explicit zero, [] versus null, and extra
	// fields. Decoding into a struct alone would silently accept omitted zeros.
	return reflect.DeepEqual(actualObject, expectedObject)
}

func transportErrorCode(ctx context.Context, err error, fallback string) string {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) || errors.Is(err, context.DeadlineExceeded) {
		return "engine_timeout"
	}
	if errors.Is(ctx.Err(), context.Canceled) || errors.Is(err, context.Canceled) {
		return "engine_cancelled"
	}
	var timeout net.Error
	if errors.As(err, &timeout) && timeout.Timeout() {
		return "engine_timeout"
	}
	return fallback
}
