package planning

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/Elmar006/energy_web/backend/internal/artifact"
)

type inputValidatorFunc func(context.Context, json.RawMessage) error

func (fn inputValidatorFunc) Validate(ctx context.Context, raw json.RawMessage) error {
	return fn(ctx, raw)
}

func TestArtifactValidatorHydratesBeforeDomainValidation(t *testing.T) {
	const data = `{"schema_version":"demand-dataset-v1","service_calendar":{"schema_version":"service-calendar-v1"},"charging_requests":[]}`
	local := artifact.Local{Root: t.TempDir()}
	m, err := local.Put(context.Background(), []byte(data))
	if err != nil {
		t.Fatal(err)
	}
	manifest, _ := json.Marshal(m)
	spec := json.RawMessage(`{"id":"test","demand_dataset":` + string(manifest) + `}`)
	called := false
	validator := ArtifactValidator{Reader: local, Next: inputValidatorFunc(func(_ context.Context, input json.RawMessage) error {
		called = true
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(input, &fields); err != nil ||
			len(fields["service_calendar"]) == 0 || string(fields["charging_requests"]) != "[]" {
			t.Fatalf("validator saw unresolved demand: %s %v", input, err)
		}
		return nil
	})}
	if err := validator.Validate(context.Background(), spec); err != nil || !called {
		t.Fatalf("domain validator skipped: %v", err)
	}
	invalid := json.RawMessage(`{"demand_dataset":{"schema_version":"demand-dataset-v1","artifact_id":"../../evil","sha256":"bad","byte_size":1}}`)
	called = false
	if err := validator.Validate(context.Background(), invalid); !errors.Is(err, ErrInvalidScenario) || called {
		t.Fatalf("invalid manifest reached engine: %v called=%t", err, called)
	}
}
