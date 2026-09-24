package planning

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
)

type runRepositoryStub struct {
	lookupCalls, createCalls, cancelCalls int
	lookupErr, createErr, cancelErr       error
	canCancel                             bool
}

func (r *runRepositoryStub) ListScenarios(context.Context) ([]ScenarioSummary, error) {
	return nil, nil
}
func (r *runRepositoryStub) GetScenario(context.Context, string) (Scenario, error) {
	r.lookupCalls++
	return Scenario{ID: "scenario"}, r.lookupErr
}
func (r *runRepositoryStub) CreateRun(context.Context, string, string) (Run, error) {
	r.createCalls++
	return Run{ID: "run"}, r.createErr
}
func (r *runRepositoryStub) GetRun(context.Context, string) (Run, error) {
	return Run{}, nil
}
func (r *runRepositoryStub) Cancel(context.Context, string) (bool, error) {
	r.cancelCalls++
	return r.canCancel, r.cancelErr
}
func (r *runRepositoryStub) Result(context.Context, string) (json.RawMessage, error) {
	return nil, nil
}
func (r *runRepositoryStub) Events(context.Context, string, int64) ([]Event, error) {
	return nil, nil
}

func TestRunStartEnforcesKeyAndScenarioExistence(t *testing.T) {
	repo := &runRepositoryStub{}
	service := Runs{Repository: repo}
	if _, err := service.Start(context.Background(), "scenario", "short"); !errors.Is(err, ErrInvalidKey) {
		t.Fatalf("short key accepted: %v", err)
	}
	if repo.lookupCalls != 0 || repo.createCalls != 0 {
		t.Fatal("invalid key reached repository")
	}
	repo.lookupErr = ErrNotFound
	if _, err := service.Start(context.Background(), "missing", "valid-key"); !errors.Is(err, ErrNotFound) || repo.createCalls != 0 {
		t.Fatalf("missing scenario created a run: %v", err)
	}
	repo.lookupErr = nil
	run, err := service.Start(context.Background(), "scenario", "valid-key")
	if err != nil || run.ID != "run" || repo.createCalls != 1 {
		t.Fatalf("valid run not created: %+v %v", run, err)
	}
}

func TestRunCancelDistinguishesTerminalState(t *testing.T) {
	repo := &runRepositoryStub{}
	service := Runs{Repository: repo}
	if err := service.Cancel(context.Background(), "run"); !errors.Is(err, ErrNotCancellable) {
		t.Fatalf("terminal run cancellation: %v", err)
	}
	repo.canCancel = true
	if err := service.Cancel(context.Background(), "run"); err != nil || repo.cancelCalls != 2 {
		t.Fatalf("active run cancellation: %v", err)
	}
}
