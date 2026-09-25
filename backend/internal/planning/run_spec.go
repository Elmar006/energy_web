package planning

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"
)

// RunSpec is the fully resolved, immutable configuration of one execution.
// Scenario values remain unchanged when per-run solver/day overrides are used.
type RunSpec struct {
	SchemaVersion     string `json:"schema_version"`
	ModelVersion      string `json:"model_version"`
	SimulationVersion string `json:"simulation_version"`
	Mode              string `json:"mode"`
	SimulationSeeds   []int  `json:"simulation_seeds"`
	// DevelopmentSeeds are used only while selecting a plan. In v2 they must
	// never overlap the final, held-out SimulationSeeds.
	DevelopmentSeeds            []int           `json:"development_seeds,omitempty"`
	MaxImprovementIterations    int             `json:"max_improvement_iterations,omitempty"`
	ExplainTopN                 int             `json:"explain_top_n"`
	AlternativeServiceFractions []float64       `json:"alternative_service_fractions"`
	AlternativeSolverSeconds    int             `json:"alternative_solver_seconds"`
	SolverSeconds               int             `json:"solver_seconds"`
	SimulationDays              int             `json:"simulation_days"`
	ServiceRequirements         json.RawMessage `json:"service_requirements,omitempty"`
}

var ErrInvalidRunSpec = errors.New("invalid run specification")
var ErrRunSpecConflict = errors.New("idempotency key already used with different run specification")

func invalidRunSpec(detail string) error {
	return fmt.Errorf("%w: %s", ErrInvalidRunSpec, detail)
}

// ResolveRunSpec materializes defaults once, before enqueueing. A nil/empty raw
// value preserves the legacy public API defaults; explicit null is invalid.
func ResolveRunSpec(raw, scenario json.RawMessage) (RunSpec, error) {
	spec := RunSpec{
		SchemaVersion: "run-spec-v1", ModelVersion: "planner-mip-v3",
		SimulationVersion: "simpy-multiday-v1", Mode: "exploratory",
		SimulationSeeds: []int{1, 2, 3}, ExplainTopN: 3,
		AlternativeServiceFractions: []float64{0, 0.5, 1},
		AlternativeSolverSeconds:    20, SolverSeconds: 60, SimulationDays: 3,
	}
	var input struct {
		Parameters map[string]json.RawMessage `json:"parameters"`
	}
	if len(scenario) > 0 {
		if err := json.Unmarshal(scenario, &input); err != nil {
			return RunSpec{}, invalidRunSpec("cannot resolve scenario defaults")
		}
		for name, destination := range map[string]*int{"solver_seconds": &spec.SolverSeconds, "simulation_days": &spec.SimulationDays} {
			if value, exists := input.Parameters[name]; exists {
				number, err := scenarioInteger(value)
				if err != nil {
					return RunSpec{}, invalidRunSpec("cannot resolve scenario " + name)
				}
				*destination = number
			}
		}
	}
	raw = bytes.TrimSpace(raw)
	if len(raw) > 0 {
		if raw[0] != '{' {
			return RunSpec{}, invalidRunSpec("run_spec must be an object")
		}
		// encoding/json accepts null for numbers and ignores case in field
		// names. Reject those ambiguous forms before the typed decode.
		decoder := json.NewDecoder(bytes.NewReader(raw))
		if _, err := decoder.Token(); err != nil {
			return RunSpec{}, invalidRunSpec("run_spec must be valid JSON")
		}
		allowed := map[string]bool{
			"schema_version": true, "model_version": true, "simulation_version": true,
			"mode": true, "simulation_seeds": true, "explain_top_n": true,
			"development_seeds": true, "max_improvement_iterations": true,
			"alternative_service_fractions": true, "alternative_solver_seconds": true,
			"solver_seconds": true, "simulation_days": true,
			"service_requirements": true,
		}
		seen := map[string]bool{}
		for decoder.More() {
			token, err := decoder.Token()
			if err != nil {
				return RunSpec{}, invalidRunSpec("invalid field name")
			}
			key, ok := token.(string)
			if !ok || !allowed[key] || seen[key] {
				return RunSpec{}, invalidRunSpec("unknown or repeated field")
			}
			seen[key] = true
			var value any
			if err := decoder.Decode(&value); err != nil || containsNull(value) {
				return RunSpec{}, invalidRunSpec("fields and array items must not be null")
			}
		}
		if _, err := decoder.Token(); err != nil {
			return RunSpec{}, invalidRunSpec("invalid object ending")
		}
		if err := decoder.Decode(new(any)); !errors.Is(err, io.EOF) {
			return RunSpec{}, invalidRunSpec("one run_spec object required")
		}
		decoder = json.NewDecoder(bytes.NewReader(raw))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&spec); err != nil {
			return RunSpec{}, invalidRunSpec(err.Error())
		}
		if spec.SchemaVersion == "run-spec-v1" &&
			(seen["development_seeds"] || seen["max_improvement_iterations"]) {
			return RunSpec{}, invalidRunSpec("development seeds and improvement iterations require run-spec-v2")
		}
	}
	return spec, spec.Validate()
}

// Previously validated PlanningInput uses Pydantic's non-strict integer fields.
// Preserve already accepted scenario values such as 15.0 or "15" while the new
// RunSpec override contract itself deliberately requires strict integer tokens.
func scenarioInteger(raw json.RawMessage) (int, error) {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, err
	}
	var n float64
	switch value := value.(type) {
	case float64:
		n = value
	case string:
		parsed, err := strconv.ParseFloat(value, 64)
		if err != nil {
			return 0, err
		}
		n = parsed
	case bool:
		if value {
			n = 1
		}
	default:
		return 0, errors.New("integer required")
	}
	if math.IsNaN(n) || math.IsInf(n, 0) || n != math.Trunc(n) || n < 0 || n > 3600 {
		return 0, errors.New("integer out of range")
	}
	return int(n), nil
}

func containsNull(value any) bool {
	switch value := value.(type) {
	case nil:
		return true
	case []any:
		for _, item := range value {
			if containsNull(item) {
				return true
			}
		}
	case map[string]any:
		for _, item := range value {
			if containsNull(item) {
				return true
			}
		}
	}
	return false
}

// Validate rejects unsupported model versions and bounds the public workload.
// Validation mode requires enough seeds to start a comparison; it does not
// certify statistical precision or acceptance of the resulting plan.
func (s RunSpec) Validate() error {
	if (s.SchemaVersion != "run-spec-v1" && s.SchemaVersion != "run-spec-v2") ||
		s.ModelVersion != "planner-mip-v3" || s.SimulationVersion != "simpy-multiday-v1" {
		return invalidRunSpec("unsupported schema, model or simulation version")
	}
	if s.Mode != "exploratory" && s.Mode != "validation" {
		return invalidRunSpec("mode must be exploratory or validation")
	}
	if len(s.SimulationSeeds) < 1 || len(s.SimulationSeeds) > 100 || (s.Mode == "validation" && len(s.SimulationSeeds) < 30) {
		return invalidRunSpec("provide 1..100 seeds; validation requires at least 30")
	}
	seen := make(map[int]bool, len(s.SimulationSeeds))
	for _, seed := range s.SimulationSeeds {
		if seed < 0 || int64(seed) > 2147483647 || seen[seed] {
			return invalidRunSpec("seeds must be unique integers in [0,2147483647]")
		}
		seen[seed] = true
	}
	if s.SchemaVersion == "run-spec-v2" {
		if len(s.DevelopmentSeeds) > 30 ||
			s.MaxImprovementIterations < 0 || s.MaxImprovementIterations > 3 {
			return invalidRunSpec("run-spec-v2 permits at most 30 development_seeds and 3 improvement iterations")
		}
		if s.MaxImprovementIterations > 0 &&
			(s.Mode != "validation" || len(s.ServiceRequirements) == 0 || len(s.DevelopmentSeeds) < 2) {
			return invalidRunSpec("improvement requires validation mode, service requirements and at least 2 development seeds")
		}
		for _, seed := range s.DevelopmentSeeds {
			if seed < 0 || int64(seed) > 2147483647 || seen[seed] {
				return invalidRunSpec("development seeds must be unique and disjoint from simulation seeds")
			}
			seen[seed] = true
		}
	} else if len(s.DevelopmentSeeds) != 0 || s.MaxImprovementIterations != 0 {
		return invalidRunSpec("development seeds and improvement iterations require run-spec-v2")
	}
	if s.ExplainTopN < 0 || s.ExplainTopN > 10 || s.SolverSeconds < 1 || s.SolverSeconds > 3600 || s.SimulationDays < 1 || s.SimulationDays > 14 || s.AlternativeSolverSeconds < 1 || s.AlternativeSolverSeconds > 60 {
		return invalidRunSpec("solver, simulation or explanation limit out of range")
	}
	if s.AlternativeServiceFractions == nil || len(s.AlternativeServiceFractions) > 5 {
		return invalidRunSpec("alternative_service_fractions must be an array with at most 5 entries")
	}
	for i, fraction := range s.AlternativeServiceFractions {
		if math.IsNaN(fraction) || math.IsInf(fraction, 0) || fraction < 0 || fraction > 1 || (i > 0 && fraction <= s.AlternativeServiceFractions[i-1]) {
			return invalidRunSpec("alternative targets must be finite, unique, sorted fractions in [0,1]")
		}
	}
	if len(s.ServiceRequirements) > 0 {
		if s.Mode != "validation" {
			return invalidRunSpec("service_requirements require validation mode")
		}
		if err := validateServiceRequirements(s.ServiceRequirements); err != nil {
			return err
		}
		var seedMinimum struct {
			MinSeedsPerCondition int `json:"min_seeds_per_condition"`
		}
		if err := json.Unmarshal(s.ServiceRequirements, &seedMinimum); err != nil {
			return invalidRunSpec("invalid service_requirements")
		}
		if seedMinimum.MinSeedsPerCondition > len(s.SimulationSeeds) {
			return invalidRunSpec("simulation_seeds do not meet min_seeds_per_condition")
		}
	}
	return nil
}

// Validate the persisted service gate before enqueueing. The Python engine
// applies the same schema and produces the actual operational assessment.
func validateServiceRequirements(raw json.RawMessage) error {
	var requirements struct {
		SchemaVersion             string   `json:"schema_version"`
		MinEnergyFraction         *float64 `json:"min_energy_fraction"`
		MinSessionFraction        *float64 `json:"min_session_fraction"`
		MaxRefusalFraction        *float64 `json:"max_refusal_fraction"`
		MaxMeanSeedP95WaitMinutes *float64 `json:"max_mean_seed_p95_wait_minutes"`
		MinSeedsPerCondition      *int     `json:"min_seeds_per_condition"`
	}
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&requirements); err != nil {
		return invalidRunSpec("invalid service_requirements: " + err.Error())
	}
	if err := decoder.Decode(new(any)); !errors.Is(err, io.EOF) {
		return invalidRunSpec("service_requirements must contain one object")
	}
	if requirements.SchemaVersion != "" && requirements.SchemaVersion != "service-v1" {
		return invalidRunSpec("unsupported service_requirements schema_version")
	}
	if requirements.MinEnergyFraction == nil && requirements.MinSessionFraction == nil &&
		requirements.MaxRefusalFraction == nil && requirements.MaxMeanSeedP95WaitMinutes == nil {
		return invalidRunSpec("at least one service threshold is required")
	}
	for _, value := range []*float64{requirements.MinEnergyFraction, requirements.MinSessionFraction,
		requirements.MaxRefusalFraction} {
		if value != nil && (math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0 || *value > 1) {
			return invalidRunSpec("service fractions must be in [0,1]")
		}
	}
	if value := requirements.MaxMeanSeedP95WaitMinutes; value != nil &&
		(math.IsNaN(*value) || math.IsInf(*value, 0) || *value < 0) {
		return invalidRunSpec("maximum wait must be nonnegative and finite")
	}
	if value := requirements.MinSeedsPerCondition; value != nil && (*value < 2 || *value > 100) {
		return invalidRunSpec("min_seeds_per_condition must be in [2,100]")
	}
	return nil
}

// Job is an immutable execution snapshot plus the current fencing token.
type Job struct {
	RunID           string
	AttemptID       string
	Spec            json.RawMessage
	RunSpec         RunSpec
	ScenarioSHA256  string
	RunSpecSHA256   string
	ExecutionSHA256 string
}
