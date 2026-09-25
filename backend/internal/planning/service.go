package planning

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"
	"unicode/utf8"
)

type Scenario struct {
	ID     string          `json:"id"`
	Name   string          `json:"name"`
	Spec   json.RawMessage `json:"spec"`
	SHA256 string          `json:"sha256"`
}

type ScenarioSummary struct {
	ID        string    `json:"id"`
	Name      string    `json:"name"`
	SHA256    string    `json:"sha256"`
	CreatedAt time.Time `json:"created_at"`
}

type Run struct {
	RunSpec         RunSpec   `json:"run_spec"`
	RunSpecSHA256   string    `json:"run_spec_sha256"`
	ExecutionSHA256 string    `json:"execution_sha256"`
	ScenarioSHA256  string    `json:"scenario_sha256"`
	RunSpecOrigin   string    `json:"run_spec_origin"`
	ID              string    `json:"id"`
	ScenarioID      string    `json:"scenario_id"`
	State           string    `json:"state"`
	Attempts        int       `json:"attempts"`
	ErrorCode       *string   `json:"error_code,omitempty"`
	ErrorDetail     *string   `json:"error_detail,omitempty"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

type Event struct {
	ID        int64     `json:"id"`
	Kind      string    `json:"kind"`
	Detail    *string   `json:"detail,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type ScenarioRepository interface {
	CreateScenario(context.Context, string, json.RawMessage) (Scenario, error)
}

type InputValidator interface {
	Validate(context.Context, json.RawMessage) error
}

type Service struct {
	Repository ScenarioRepository
	Validator  InputValidator
}

var ErrInvalidScenario = errors.New("invalid scenario")
var ErrValidatorUnavailable = errors.New("input validator unavailable")
var ErrNotFound = errors.New("not found")
var ErrInvalidKey = errors.New("invalid idempotency key")
var ErrNotCancellable = errors.New("run not cancellable")

type InvalidInputError struct{ Detail string }

func (e InvalidInputError) Error() string        { return e.Detail }
func (e InvalidInputError) Is(target error) bool { return target == ErrInvalidScenario }

func (s Service) CreateScenario(ctx context.Context, name string, spec json.RawMessage) (Scenario, error) {
	name = strings.TrimSpace(name)
	spec = bytes.TrimSpace(spec)
	if name == "" || utf8.RuneCountInString(name) > 120 || !json.Valid(spec) || len(spec) == 0 || spec[0] != '{' {
		return Scenario{}, InvalidInputError{Detail: "name and JSON object spec are required; name must be at most 120 characters"}
	}
	if s.Validator == nil {
		return Scenario{}, ErrValidatorUnavailable
	}
	if err := s.Validator.Validate(ctx, spec); err != nil {
		return Scenario{}, err
	}
	return s.Repository.CreateScenario(ctx, name, spec)
}
