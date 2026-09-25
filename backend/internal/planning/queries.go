package planning

import (
	"context"
	"encoding/json"
)

// QueryRepository is the read side of immutable planning scenarios.
type QueryRepository interface {
	ListScenarios(context.Context) ([]ScenarioSummary, error)
	GetScenario(context.Context, string) (Scenario, error)
}

type Queries struct{ Repository QueryRepository }

func (q Queries) ListScenarios(ctx context.Context) ([]ScenarioSummary, error) {
	return q.Repository.ListScenarios(ctx)
}

func (q Queries) GetScenario(ctx context.Context, id string) (Scenario, error) {
	return q.Repository.GetScenario(ctx, id)
}

// RunRepository owns durable state transitions; implementations must make
// cancellation and result publication atomic with their corresponding events.
type RunRepository interface {
	QueryRepository
	CreateRun(context.Context, string, string, ...RunSpec) (Run, error)
	GetRun(context.Context, string) (Run, error)
	Cancel(context.Context, string) (bool, error)
	Result(context.Context, string) (json.RawMessage, error)
	Events(context.Context, string, int64) ([]Event, error)
}

type Runs struct{ Repository RunRepository }

func (s Runs) Start(ctx context.Context, scenarioID, key string, rawSpec ...json.RawMessage) (Run, error) {
	if len(key) < 8 || len(key) > 128 {
		return Run{}, ErrInvalidKey
	}
	scenario, err := s.Repository.GetScenario(ctx, scenarioID)
	if err != nil {
		return Run{}, err
	}
	if len(rawSpec) > 1 {
		return Run{}, invalidRunSpec("one configuration required")
	}
	var raw json.RawMessage
	if len(rawSpec) == 1 {
		raw = rawSpec[0]
	}
	spec, err := ResolveRunSpec(raw, scenario.Spec)
	if err != nil {
		return Run{}, err
	}
	return s.Repository.CreateRun(ctx, scenarioID, key, spec)
}

func (s Runs) Get(ctx context.Context, id string) (Run, error) {
	return s.Repository.GetRun(ctx, id)
}

func (s Runs) Cancel(ctx context.Context, id string) error {
	ok, err := s.Repository.Cancel(ctx, id)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotCancellable
	}
	return nil
}

func (s Runs) Result(ctx context.Context, id string) (json.RawMessage, error) {
	return s.Repository.Result(ctx, id)
}

func (s Runs) Events(ctx context.Context, id string, after int64) ([]Event, error) {
	return s.Repository.Events(ctx, id, after)
}
