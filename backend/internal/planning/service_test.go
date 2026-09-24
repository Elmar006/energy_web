package planning

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
)

type fakeRepository struct{ calls int }

func (r *fakeRepository) CreateScenario(_ context.Context, name string, spec json.RawMessage) (Scenario, error) {
	r.calls++
	return Scenario{ID: "saved", Name: name, Spec: spec}, nil
}

type fakeValidator struct {
	calls int
	err   error
}

func (v *fakeValidator) Validate(_ context.Context, _ json.RawMessage) error {
	v.calls++
	return v.err
}

func TestCreateScenarioSeparatesContractValidationFromPersistence(t *testing.T) {
	repo := &fakeRepository{}
	validator := &fakeValidator{}
	service := Service{Repository: repo, Validator: validator}
	for _, bad := range []struct {
		name string
		spec string
	}{{"", `{}`}, {"valid", `null`}, {"valid", `[]`}, {"valid", `{`}} {
		_, err := service.CreateScenario(context.Background(), bad.name, []byte(bad.spec))
		if !errors.Is(err, ErrInvalidScenario) {
			t.Fatalf("bad input accepted: %+v, %v", bad, err)
		}
	}
	if repo.calls != 0 || validator.calls != 0 {
		t.Fatal("invalid input reached validator or database")
	}
	validator.err = InvalidInputError{Detail: "body.zones: missing"}
	_, err := service.CreateScenario(context.Background(), "valid", []byte(`{}`))
	if !errors.Is(err, ErrInvalidScenario) || repo.calls != 0 {
		t.Fatalf("engine rejection was persisted: %v", err)
	}
	validator.err = nil
	saved, err := service.CreateScenario(context.Background(), "  План  ", []byte(`  {"id":"test"}  `))
	if err != nil || saved.Name != "План" || string(saved.Spec) != `{"id":"test"}` || repo.calls != 1 {
		t.Fatalf("valid scenario was not stored cleanly: %+v, %v", saved, err)
	}
}
