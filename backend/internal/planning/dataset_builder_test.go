package planning

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

type datasetRepositoryFixture struct {
	datasets map[string]PlanningDataset
	reads    int
	writes   int
	saved    json.RawMessage
}

func (r *datasetRepositoryFixture) PlanningDataset(_ context.Context, id string) (PlanningDataset, error) {
	r.reads++
	item, ok := r.datasets[id]
	if !ok {
		return PlanningDataset{}, ErrDatasetNotFound
	}
	return item, nil
}

func (r *datasetRepositoryFixture) CreateScenario(_ context.Context, name string, spec json.RawMessage) (Scenario, error) {
	r.writes++
	r.saved = spec
	return Scenario{ID: "saved", Name: name, Spec: spec}, nil
}

func fixtureFeature(id, kind, properties string, point bool) PlanningFeature {
	feature := PlanningFeature{ExternalID: id, FeatureType: kind,
		Properties: json.RawMessage(properties), GeometryType: "LINESTRING"}
	if point {
		lat, lon := 55.7, 37.6
		feature.GeometryType, feature.Latitude, feature.Longitude = "POINT", &lat, &lon
	}
	return feature
}

func datasetBuildFixture() (*datasetRepositoryFixture, DatasetBuildRequest) {
	ids := DatasetSelection{
		DemandZones: "00000000-0000-4000-8000-000000000001",
		Sites:       "00000000-0000-4000-8000-000000000002",
		GridNodes:   "00000000-0000-4000-8000-000000000003",
		TravelEdges: "00000000-0000-4000-8000-000000000004",
	}
	hourly := `[0,0,0,0,0,0,0,0,0,0,0,0,10,0,0,0,0,0,0,0,0,0,0,0]`
	grid := `[10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10]`
	features := map[string]PlanningFeature{
		ids.DemandZones: fixtureFeature("z1", "demand_zone", `{"feature_type":"demand_zone","name":"Zone","hourly_kwh":`+hourly+`,"mean_session_kwh":10,"max_travel_minutes":20,"time_zone":"Europe/Moscow"}`, true),
		ids.Sites:       fixtureFeature("s1", "candidate_site", `{"feature_type":"candidate_site","name":"Site","grid_node_id":"g1","option_ids":["dc"]}`, true),
		ids.GridNodes:   fixtureFeature("g1", "grid_node", `{"feature_type":"grid_node","headroom_kw":`+grid+`,"time_zone":"Europe/Moscow"}`, true),
		ids.TravelEdges: fixtureFeature("", "travel_edge", `{"feature_type":"travel_edge","zone_id":"z1","site_id":"s1","minutes":5}`, false),
	}
	stamp := time.Date(2026, 9, 24, 12, 0, 0, 0, time.UTC)
	repo := &datasetRepositoryFixture{datasets: map[string]PlanningDataset{}}
	for id, feature := range features {
		repo.datasets[id] = PlanningDataset{ID: id, Name: "Imported " + feature.FeatureType,
			Kind: "observed", Source: "supplier export", Checksum: strings.Repeat("a", 64),
			CapturedAt: &stamp, Features: []PlanningFeature{feature}}
	}
	request := DatasetBuildRequest{Name: "  Imported scenario  ", InputID: "selected-versions",
		TimeZone: "Europe/Moscow", DatasetVersions: ids,
		Options:    json.RawMessage(`[{"id":"dc","ports":1,"charger_kw":10,"connection_kw":10,"capex_rub":1000,"annual_fixed_rub":0}]`),
		Parameters: json.RawMessage(`{"mode":"city","years":[2027],"annual_budgets_rub":[1000],"total_budget_rub":1000,"sale_rub_per_kwh":20,"purchase_rub_per_kwh":5,"discount_rate":0.1,"pv_hourly_factor":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}`),
		Scenarios:  json.RawMessage(`[{"id":"base","demand_multiplier":[1]}]`)}
	return repo, request
}

func TestBuildUsesExactVersionsWithoutInventingEnergyOrRoadTimes(t *testing.T) {
	repo, request := datasetBuildFixture()
	validator := &fakeValidator{}
	builder := DatasetBuilder{Repository: repo, Validator: validator}
	prepared, err := builder.Prepare(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if repo.reads != 4 || repo.writes != 0 || validator.calls != 1 || len(prepared.DataQuality.Datasets) != 4 {
		t.Fatalf("unexpected build flow: reads=%d writes=%d validator=%d quality=%+v",
			repo.reads, repo.writes, validator.calls, prepared.DataQuality)
	}
	var spec struct {
		TimeZone string `json:"time_zone"`
		Zones    []struct {
			ID         string                        `json:"id"`
			Hourly     []float64                     `json:"hourly_kwh"`
			Provenance struct{ Kind, Source string } `json:"provenance"`
		} `json:"zones"`
		Sites []struct {
			ID       string  `json:"id"`
			Latitude float64 `json:"latitude"`
		} `json:"sites"`
		GridNodes []struct {
			ID       string    `json:"id"`
			Headroom []float64 `json:"headroom_kw"`
		} `json:"grid_nodes"`
		Edges []struct {
			Minutes float64 `json:"minutes"`
		} `json:"travel_edges"`
		Datasets []struct {
			Role      string `json:"role"`
			VersionID string `json:"version_id"`
			SHA256    string `json:"sha256"`
		} `json:"datasets"`
	}
	if err := json.Unmarshal(prepared.Spec, &spec); err != nil {
		t.Fatal(err)
	}
	var encoded map[string]json.RawMessage
	if err := json.Unmarshal(prepared.Spec, &encoded); err != nil || string(encoded["locked_site_ids"]) != "[]" ||
		string(encoded["excluded_site_ids"]) != "[]" {
		t.Fatalf("optional lists were not normalized: %s %v", prepared.Spec, err)
	}
	if spec.TimeZone != "Europe/Moscow" || spec.Zones[0].ID != "z1" || spec.Zones[0].Hourly[12] != 10 ||
		spec.Zones[0].Provenance.Kind != "observed" || !strings.Contains(spec.Zones[0].Provenance.Source, request.DatasetVersions.DemandZones) ||
		spec.Sites[0].ID != "s1" || spec.Sites[0].Latitude != 55.7 || spec.GridNodes[0].Headroom[12] != 10 ||
		spec.Edges[0].Minutes != 5 || len(spec.Datasets) != 5 || spec.Datasets[0].VersionID != request.DatasetVersions.DemandZones ||
		spec.Datasets[4].Role != "planning_assumptions" || spec.Datasets[4].VersionID != "" {
		t.Fatalf("incorrect assembled input: %s", prepared.Spec)
	}
	saved, _, err := builder.Create(context.Background(), request)
	if err != nil || saved.Name != "Imported scenario" || repo.writes != 1 || !json.Valid(repo.saved) {
		t.Fatalf("validated scenario was not saved: %+v %v", saved, err)
	}
}

func TestBuildPreservesMeasuredSessionArrivalProfile(t *testing.T) {
	repo, request := datasetBuildFixture()
	dataset := repo.datasets[request.DatasetVersions.DemandZones]
	var properties map[string]any
	if err := json.Unmarshal(dataset.Features[0].Properties, &properties); err != nil {
		t.Fatal(err)
	}
	arrivals := make([]float64, 24)
	arrivals[12] = 1
	properties["arrival_profile"] = map[string]any{
		"hourly_sessions": arrivals, "hourly_count_variance": make([]float64, 24),
		"energy_quantiles_kwh": func() []float64 {
			values := make([]float64, 101)
			for index := range values {
				values[index] = 10
			}
			return values
		}(),
		"sample_count": 1, "observation_days": 1, "source_kind": "observed",
		"hourly_load_method": "uniform_session_duration",
		"provenance":         map[string]any{"kind": "derived", "source": "metered sessions"},
	}
	encoded, err := json.Marshal(properties)
	if err != nil {
		t.Fatal(err)
	}
	dataset.Features[0].Properties = encoded
	repo.datasets[request.DatasetVersions.DemandZones] = dataset
	prepared, err := (DatasetBuilder{Repository: repo, Validator: &fakeValidator{}}).Prepare(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		Zones []struct {
			ArrivalProfile struct {
				HourlySessions []float64 `json:"hourly_sessions"`
				SourceKind     string    `json:"source_kind"`
			} `json:"arrival_profile"`
		} `json:"zones"`
	}
	if err := json.Unmarshal(prepared.Spec, &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Zones) != 1 || result.Zones[0].ArrivalProfile.HourlySessions[12] != 1 ||
		result.Zones[0].ArrivalProfile.SourceKind != "observed" {
		t.Fatalf("session arrival profile was not preserved: %s", prepared.Spec)
	}
}

func TestBuildRejectsMissingOrContradictoryDataBeforeSaving(t *testing.T) {
	for _, mutate := range []struct {
		name   string
		change func(*datasetRepositoryFixture, *DatasetBuildRequest)
		want   string
	}{
		{"missing headroom", func(r *datasetRepositoryFixture, q *DatasetBuildRequest) {
			d := r.datasets[q.DatasetVersions.GridNodes]
			d.Features[0].Properties = []byte(`{"feature_type":"grid_node","time_zone":"Europe/Moscow"}`)
			r.datasets[q.DatasetVersions.GridNodes] = d
		}, "missing headroom_kw"},
		{"wrong zone", func(r *datasetRepositoryFixture, q *DatasetBuildRequest) {
			d := r.datasets[q.DatasetVersions.DemandZones]
			d.Features[0].Properties = []byte(strings.ReplaceAll(string(d.Features[0].Properties), "Europe/Moscow", "Asia/Yekaterinburg"))
			r.datasets[q.DatasetVersions.DemandZones] = d
		}, "time_zone differs"},
		{"no observation date", func(r *datasetRepositoryFixture, q *DatasetBuildRequest) {
			d := r.datasets[q.DatasetVersions.DemandZones]
			d.CapturedAt = nil
			r.datasets[q.DatasetVersions.DemandZones] = d
		}, "requires captured_at"},
		{"unsupported numeric field", func(r *datasetRepositoryFixture, q *DatasetBuildRequest) {
			d := r.datasets[q.DatasetVersions.GridNodes]
			d.Features[0].Properties = []byte(strings.Replace(string(d.Features[0].Properties), `"headroom_kw"`, `"headroom_kwh"`, 1))
			r.datasets[q.DatasetVersions.GridNodes] = d
		}, "unsupported property"},
		{"wrong feature type", func(r *datasetRepositoryFixture, q *DatasetBuildRequest) {
			d := r.datasets[q.DatasetVersions.Sites]
			d.Features[0].FeatureType = "charger"
			r.datasets[q.DatasetVersions.Sites] = d
		}, "expected feature_type"},
		{"wrong geometry", func(r *datasetRepositoryFixture, q *DatasetBuildRequest) {
			d := r.datasets[q.DatasetVersions.Sites]
			d.Features[0].GeometryType = "POLYGON"
			r.datasets[q.DatasetVersions.Sites] = d
		}, "Point geometry required"},
		{"duplicate selection", func(_ *datasetRepositoryFixture, q *DatasetBuildRequest) {
			q.DatasetVersions.GridNodes = q.DatasetVersions.DemandZones
		}, "distinct version"},
	} {
		t.Run(mutate.name, func(t *testing.T) {
			repo, request := datasetBuildFixture()
			mutate.change(repo, &request)
			_, _, err := (DatasetBuilder{Repository: repo, Validator: &fakeValidator{}}).Create(context.Background(), request)
			if !errors.Is(err, ErrInvalidScenario) || !strings.Contains(err.Error(), mutate.want) || repo.writes != 0 {
				t.Fatalf("invalid source was accepted: %v, writes=%d", err, repo.writes)
			}
		})
	}
}

func TestBuildReportsMissingVersionAndValidatorFailure(t *testing.T) {
	repo, request := datasetBuildFixture()
	delete(repo.datasets, request.DatasetVersions.GridNodes)
	_, err := (DatasetBuilder{Repository: repo, Validator: &fakeValidator{}}).Prepare(context.Background(), request)
	if !errors.Is(err, ErrDatasetNotFound) || repo.writes != 0 {
		t.Fatalf("missing version not reported: %v", err)
	}
	repo, request = datasetBuildFixture()
	validator := &fakeValidator{err: InvalidInputError{Detail: "zones.0.hourly_kwh invalid"}}
	_, _, err = (DatasetBuilder{Repository: repo, Validator: validator}).Create(context.Background(), request)
	if !errors.Is(err, ErrInvalidScenario) || repo.writes != 0 || validator.calls != 1 {
		t.Fatalf("validator rejection was persisted: %v", err)
	}
}

func TestEquivalentJSONSectionsProduceSamePlanningSnapshot(t *testing.T) {
	repo, request := datasetBuildFixture()
	builder := DatasetBuilder{Repository: repo, Validator: &fakeValidator{}}
	first, err := builder.Prepare(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	request.Options = []byte(` [ { "ports": 1, "id": "dc", "annual_fixed_rub": 0, "capex_rub": 1000, "connection_kw": 10, "charger_kw": 10 } ] `)
	second, err := builder.Prepare(context.Background(), request)
	if err != nil || string(first.Spec) != string(second.Spec) {
		t.Fatalf("insignificant JSON formatting changed the scenario snapshot: %v", err)
	}
}

func TestCanonicalSectionPreservesLargeMonetaryNumber(t *testing.T) {
	got, err := canonicalSection([]byte(`{"z":9007199254740993,"a":1}`))
	if err != nil || string(got) != `{"a":1,"z":9007199254740993}` {
		t.Fatalf("JSON normalization rounded a number: %s %v", got, err)
	}
}
