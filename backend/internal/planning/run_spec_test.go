package planning

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
)

func TestRunSpecFreezesScenarioDefaultsAndExplicitZeroOptions(t *testing.T) {
	scenario := json.RawMessage(`{"parameters":{"solver_seconds":90,"simulation_days":7}}`)
	spec, err := ResolveRunSpec(nil, scenario)
	if err != nil || spec.SolverSeconds != 90 || spec.SimulationDays != 7 || spec.ExplainTopN != 3 || !reflect.DeepEqual(spec.SimulationSeeds, []int{1, 2, 3}) {
		t.Fatalf("defaults: %+v %v", spec, err)
	}
	overrides := json.RawMessage(`{"explain_top_n":0,"alternative_service_fractions":[],"simulation_days":1,"solver_seconds":15,"simulation_seeds":[0,2147483647]}`)
	custom, err := ResolveRunSpec(overrides, scenario)
	if err != nil || custom.ExplainTopN != 0 || custom.AlternativeServiceFractions == nil || len(custom.AlternativeServiceFractions) != 0 || custom.SolverSeconds != 15 || custom.SimulationDays != 1 {
		t.Fatalf("explicit options lost: %+v %v", custom, err)
	}
	encoded, _ := json.Marshal(custom)
	replayed, err := ResolveRunSpec(encoded, json.RawMessage(`{"parameters":{"solver_seconds":300,"simulation_days":14}}`))
	if err != nil || !reflect.DeepEqual(custom, replayed) {
		t.Fatalf("resolved snapshot changed on replay: %+v %v", replayed, err)
	}
}

func TestRunSpecRejectsAmbiguityAndUnboundedWork(t *testing.T) {
	for _, raw := range []string{
		`{"service_requirements":{"min_energy_fraction":0.9}}`,
		`null`, `[]`, `{} {}`, `{"unknown":1}`, `{"Mode":"validation"}`,
		`{"mode":"exploratory","mode":"validation"}`,
		`{"mode":null}`, `{"simulation_seeds":null}`, `{"simulation_seeds":[]}`,
		`{"simulation_seeds":[null]}`, `{"simulation_seeds":[1,1]}`,
		`{"simulation_seeds":[-1]}`, `{"simulation_seeds":[2147483648]}`,
		`{"simulation_seeds":[true]}`, `{"simulation_seeds":["1"]}`, `{"simulation_seeds":[1.0]}`,
		`{"mode":"validation"}`, `{"mode":"unknown"}`, `{"schema_version":"run-spec-v3"}`,
		`{"development_seeds":[1]}`, `{"max_improvement_iterations":0}`,
		`{"model_version":"new-model"}`, `{"simulation_version":"new-simulator"}`,
		`{"alternative_service_fractions":null}`, `{"alternative_service_fractions":[null]}`,
		`{"alternative_service_fractions":[0.5,0.1]}`, `{"alternative_service_fractions":[0.5,0.5]}`,
		`{"alternative_service_fractions":[-0.1]}`, `{"alternative_service_fractions":[1.1]}`,
		`{"alternative_service_fractions":[0,0.1,0.2,0.3,0.4,0.5]}`,
		`{"explain_top_n":null}`, `{"explain_top_n":-1}`, `{"explain_top_n":11}`,
		`{"solver_seconds":0}`, `{"solver_seconds":3601}`, `{"solver_seconds":"60"}`,
		`{"simulation_days":0}`, `{"simulation_days":15}`,
		`{"alternative_solver_seconds":0}`, `{"alternative_solver_seconds":61}`,
	} {
		t.Run(raw, func(t *testing.T) {
			if _, err := ResolveRunSpec(json.RawMessage(raw), nil); !errors.Is(err, ErrInvalidRunSpec) {
				t.Fatalf("invalid configuration accepted: %v", err)
			}
		})
	}
}

func TestRunSpecV2SeparatesDevelopmentAndHoldoutSeeds(t *testing.T) {
	holdout := make([]int, 30)
	for i := range holdout {
		holdout[i] = 100 + i
	}
	valid, _ := json.Marshal(map[string]any{
		"schema_version": "run-spec-v2", "mode": "validation",
		"simulation_seeds": holdout, "development_seeds": []int{1, 2},
		"max_improvement_iterations": 3,
		"service_requirements":       map[string]any{"min_energy_fraction": 0.9},
	})
	spec, err := ResolveRunSpec(valid, nil)
	if err != nil || spec.SchemaVersion != "run-spec-v2" || spec.MaxImprovementIterations != 3 ||
		!reflect.DeepEqual(spec.DevelopmentSeeds, []int{1, 2}) || !reflect.DeepEqual(spec.SimulationSeeds, holdout) {
		t.Fatalf("v2 seed split changed: %+v %v", spec, err)
	}
	encoded, _ := json.Marshal(spec)
	replayed, err := ResolveRunSpec(encoded, nil)
	if err != nil || !reflect.DeepEqual(spec, replayed) {
		t.Fatalf("v2 persisted snapshot changed: %+v %v", replayed, err)
	}
	for _, mutate := range []func(map[string]any){
		func(v map[string]any) { v["development_seeds"] = []int{100, 1} },
		func(v map[string]any) { v["development_seeds"] = []int{1, 1} },
		func(v map[string]any) { v["development_seeds"] = []int{1} },
		func(v map[string]any) { v["development_seeds"] = []int{} },
		func(v map[string]any) { v["max_improvement_iterations"] = 4 },
		func(v map[string]any) { v["mode"] = "exploratory" },
		func(v map[string]any) { delete(v, "service_requirements") },
	} {
		var config map[string]any
		if err := json.Unmarshal(valid, &config); err != nil {
			t.Fatal(err)
		}
		mutate(config)
		raw, _ := json.Marshal(config)
		if _, err := ResolveRunSpec(raw, nil); !errors.Is(err, ErrInvalidRunSpec) {
			t.Errorf("invalid v2 split accepted: %s %v", raw, err)
		}
	}
}

func TestPreviouslyValidatedScenarioIntegerRepresentations(t *testing.T) {
	for _, scenario := range []string{
		`{"parameters":{"solver_seconds":15.0,"simulation_days":7.0}}`,
		`{"parameters":{"solver_seconds":"15","simulation_days":"7"}}`,
	} {
		spec, err := ResolveRunSpec(nil, json.RawMessage(scenario))
		if err != nil || spec.SolverSeconds != 15 || spec.SimulationDays != 7 {
			t.Fatalf("legacy scenario changed: %+v %v", spec, err)
		}
	}
	if _, err := ResolveRunSpec(nil, json.RawMessage(`{"parameters":{"solver_seconds":15.5}}`)); !errors.Is(err, ErrInvalidRunSpec) {
		t.Fatalf("fractional solver budget accepted: %v", err)
	}
}

func TestValidationModeRequiresDistinctBoundedSeeds(t *testing.T) {
	for _, count := range []int{29, 30, 100, 101} {
		seeds := make([]int, count)
		for i := range seeds {
			seeds[i] = i
		}
		raw, _ := json.Marshal(map[string]any{"mode": "validation", "simulation_seeds": seeds})
		spec, err := ResolveRunSpec(raw, nil)
		valid := count >= 30 && count <= 100
		if valid != (err == nil) || (valid && len(spec.SimulationSeeds) != count) {
			t.Fatalf("seed count %d: %+v %v", count, spec, err)
		}
	}
}

func TestServiceRequirementsAreValidatedAndPersisted(t *testing.T) {
	good := json.RawMessage(`{"mode":"validation","simulation_seeds":[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29],"service_requirements":{"min_energy_fraction":0.9,"min_seeds_per_condition":30}}`)
	spec, err := ResolveRunSpec(good, nil)
	if err != nil || len(spec.ServiceRequirements) == 0 {
		t.Fatalf("valid service gate was not persisted: %+v %v", spec, err)
	}
	encoded, err := json.Marshal(spec)
	if err != nil || !json.Valid(encoded) {
		t.Fatalf("service gate lost on marshaling: %v", err)
	}
	replayed, err := ResolveRunSpec(encoded, nil)
	if err != nil || !reflect.DeepEqual(spec, replayed) {
		t.Fatalf("service gate changed on replay: %v", err)
	}
	tooFewSeeds := strings.Replace(string(good), `"min_seeds_per_condition":30`, `"min_seeds_per_condition":31`, 1)
	if _, err := ResolveRunSpec(json.RawMessage(tooFewSeeds), nil); !errors.Is(err, ErrInvalidRunSpec) {
		t.Fatalf("service gate exceeding configured seeds accepted: %v", err)
	}
	for _, raw := range []string{
		`{"service_requirements":{}}`,
		`{"service_requirements":null}`,
		`{"service_requirements":{"min_energy_fraction":-0.01}}`,
		`{"service_requirements":{"min_energy_fraction":1.01}}`,
		`{"service_requirements":{"min_energy_fraction":true}}`,
		`{"service_requirements":{"min_energy_fraction":0.9,"unknown":1}}`,
		`{"service_requirements":{"min_energy_fraction":0.9,"schema_version":"service-v2"}}`,
		`{"service_requirements":{"min_energy_fraction":0.9,"min_seeds_per_condition":101}}`,
	} {
		if _, err := ResolveRunSpec(json.RawMessage(raw), nil); !errors.Is(err, ErrInvalidRunSpec) {
			t.Errorf("invalid service gate accepted: %s: %v", raw, err)
		}
	}
}

func TestRunServiceRejectsInvalidConfigurationBeforeEnqueue(t *testing.T) {
	repo := &runRepositoryStub{}
	_, err := (Runs{Repository: repo}).Start(context.Background(), "scenario", "valid-key", json.RawMessage(`{"simulation_seeds":[1,1]}`))
	if !errors.Is(err, ErrInvalidRunSpec) || repo.createCalls != 0 {
		t.Fatalf("invalid specification reached queue: %v calls=%d", err, repo.createCalls)
	}
	repo.createErr = ErrRunSpecConflict
	_, err = (Runs{Repository: repo}).Start(context.Background(), "scenario", "valid-key")
	if !errors.Is(err, ErrRunSpecConflict) {
		t.Fatalf("conflict hidden: %v", err)
	}
}
