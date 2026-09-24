package planning

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// Dataset-backed plans refer to exact immutable imports, never to whichever
// version happens to be visible on the map at calculation time.
type DatasetSelection struct {
	DemandZones string `json:"demand_zones"`
	Sites       string `json:"candidate_sites"`
	GridNodes   string `json:"grid_nodes"`
	TravelEdges string `json:"travel_edges"`
}

type DatasetBuildRequest struct {
	Name            string           `json:"name"`
	InputID         string           `json:"input_id"`
	TimeZone        string           `json:"time_zone"`
	DatasetVersions DatasetSelection `json:"dataset_versions"`
	Options         json.RawMessage  `json:"options"`
	Parameters      json.RawMessage  `json:"parameters"`
	Scenarios       json.RawMessage  `json:"scenarios"`
	LockedSiteIDs   []string         `json:"locked_site_ids"`
	ExcludedSiteIDs []string         `json:"excluded_site_ids"`
}

type PlanningFeature struct {
	ExternalID   string
	FeatureType  string
	Properties   json.RawMessage
	GeometryType string
	Latitude     *float64
	Longitude    *float64
}

type PlanningDataset struct {
	ID         string
	Name       string
	Kind       string
	Source     string
	License    *string
	Checksum   string
	CapturedAt *time.Time
	Features   []PlanningFeature
}

type DatasetUse struct {
	Role         string     `json:"role"`
	VersionID    string     `json:"version_id"`
	Name         string     `json:"name"`
	Kind         string     `json:"kind"`
	Source       string     `json:"source"`
	SHA256       string     `json:"sha256"`
	License      *string    `json:"license,omitempty"`
	CapturedAt   *time.Time `json:"captured_at,omitempty"`
	FeatureCount int        `json:"feature_count"`
}

type DataQuality struct {
	Datasets []DatasetUse `json:"datasets"`
	Warnings []string     `json:"warnings"`
}

type PreparedScenario struct {
	Spec        json.RawMessage `json:"spec"`
	DataQuality DataQuality     `json:"data_quality"`
}

type DatasetRepository interface {
	PlanningDataset(context.Context, string) (PlanningDataset, error)
	CreateScenario(context.Context, string, json.RawMessage) (Scenario, error)
}

type DatasetBuilder struct {
	Repository DatasetRepository
	Validator  InputValidator
}

var ErrDatasetNotFound = errors.New("dataset version not found")
var datasetUUID = regexp.MustCompile(`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
var sha256Hex = regexp.MustCompile(`^[0-9a-f]{64}$`)

func invalidDataset(detail string) error { return InvalidInputError{Detail: detail} }

type selectedDataset struct {
	role, featureType, id, outputKey string
	required                         []string
	allowed                          map[string]bool
	point, hourly                    bool
}

func fields(names ...string) map[string]bool {
	out := make(map[string]bool, len(names))
	for _, name := range names {
		out[name] = true
	}
	return out
}

func canonicalSection(raw json.RawMessage) (json.RawMessage, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber() // Retain decimal precision instead of converting money through float64.
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	return json.Marshal(value) // Sort object keys and remove insignificant whitespace.
}

func (r DatasetBuildRequest) selections() []selectedDataset {
	return []selectedDataset{
		{role: "demand_zones", featureType: "demand_zone", id: r.DatasetVersions.DemandZones, outputKey: "zones",
			required: []string{"name", "hourly_kwh", "mean_session_kwh", "max_travel_minutes", "time_zone"},
			allowed:  fields("feature_type", "name", "group", "hourly_kwh", "mean_session_kwh", "arrival_profile", "max_travel_minutes", "time_zone"),
			point:    true, hourly: true},
		{role: "candidate_sites", featureType: "candidate_site", id: r.DatasetVersions.Sites, outputKey: "sites",
			required: []string{"name", "grid_node_id", "option_ids"},
			allowed: fields("feature_type", "name", "grid_node_id", "option_ids", "existing_option_id", "earliest_period",
				"battery_max_kwh", "battery_capex_per_kwh_rub", "pv_max_kw", "pv_capex_per_kw_rub"),
			point: true},
		{role: "grid", featureType: "grid_node", id: r.DatasetVersions.GridNodes, outputKey: "grid_nodes",
			required: []string{"headroom_kw", "time_zone"},
			allowed:  fields("feature_type", "headroom_kw", "time_zone", "upgrade_kw", "upgrade_capex_rub", "upgrade_lead_years"),
			point:    true, hourly: true},
		{role: "routing", featureType: "travel_edge", id: r.DatasetVersions.TravelEdges, outputKey: "travel_edges",
			required: []string{"zone_id", "site_id", "minutes"},
			allowed:  fields("feature_type", "zone_id", "site_id", "minutes")},
	}
}

// Prepare checks provenance and completeness before calling the same Python
// contract validator used for manually submitted planning inputs.
func (b DatasetBuilder) Prepare(ctx context.Context, request DatasetBuildRequest) (PreparedScenario, error) {
	request.Name = strings.TrimSpace(request.Name)
	request.InputID = strings.TrimSpace(request.InputID)
	request.TimeZone = strings.TrimSpace(request.TimeZone)
	if request.Name == "" || utf8.RuneCountInString(request.Name) > 120 ||
		request.InputID == "" || utf8.RuneCountInString(request.InputID) > 200 ||
		request.TimeZone == "" || len(request.TimeZone) > 128 {
		return PreparedScenario{}, invalidDataset("name (max 120 characters), input_id (max 200) and time_zone are required")
	}
	for _, part := range []struct {
		name string
		data *json.RawMessage
	}{{"options", &request.Options}, {"parameters", &request.Parameters}, {"scenarios", &request.Scenarios}} {
		if !json.Valid(*part.data) || string(*part.data) == "null" {
			return PreparedScenario{}, invalidDataset(part.name + " must be valid non-null JSON")
		}
		normalized, err := canonicalSection(*part.data)
		if err != nil {
			return PreparedScenario{}, invalidDataset(part.name + " cannot be normalized")
		}
		*part.data = normalized
	}
	if b.Validator == nil {
		return PreparedScenario{}, ErrValidatorUnavailable
	}
	selections := request.selections()
	seen := make(map[string]bool, len(selections))
	for _, selected := range selections {
		if !datasetUUID.MatchString(selected.id) {
			return PreparedScenario{}, invalidDataset("dataset_versions." + selected.role + " must be a UUID")
		}
		key := strings.ToLower(selected.id)
		if seen[key] {
			return PreparedScenario{}, invalidDataset("each dataset role requires a distinct version")
		}
		seen[key] = true
	}

	quality := DataQuality{Datasets: make([]DatasetUse, 0, len(selections)),
		Warnings: []string{"Equipment, tariffs, budgets and uncertainty scenarios were supplied in the request and are unverified assumptions."}}
	if request.LockedSiteIDs == nil {
		request.LockedSiteIDs = []string{}
	}
	if request.ExcludedSiteIDs == nil {
		request.ExcludedSiteIDs = []string{}
	}
	spec := map[string]any{
		"id": request.InputID, "time_zone": request.TimeZone,
		"options": request.Options, "parameters": request.Parameters, "scenarios": request.Scenarios,
		"locked_site_ids": request.LockedSiteIDs, "excluded_site_ids": request.ExcludedSiteIDs,
	}
	manifests := make([]map[string]any, 0, len(selections)+1)
	for _, selected := range selections {
		dataset, err := b.Repository.PlanningDataset(ctx, selected.id)
		if err != nil {
			return PreparedScenario{}, err
		}
		if dataset.ID != selected.id && !strings.EqualFold(dataset.ID, selected.id) {
			return PreparedScenario{}, invalidDataset("dataset version mismatch for " + selected.role)
		}
		if len(dataset.Features) == 0 || len(dataset.Features) > 10000 || !sha256Hex.MatchString(dataset.Checksum) || dataset.Source == "" {
			return PreparedScenario{}, invalidDataset("dataset " + selected.id + " is empty, oversized or lacks valid provenance")
		}
		if dataset.Kind != "observed" && dataset.Kind != "derived" && dataset.Kind != "assumed" {
			return PreparedScenario{}, invalidDataset("dataset " + selected.id + " has invalid kind")
		}
		if dataset.Kind == "observed" && dataset.CapturedAt == nil {
			return PreparedScenario{}, invalidDataset("observed dataset " + selected.id + " requires captured_at")
		}
		rows := make([]map[string]any, 0, len(dataset.Features))
		for _, feature := range dataset.Features {
			row, err := mapPlanningFeature(dataset, feature, selected, request.TimeZone)
			if err != nil {
				return PreparedScenario{}, err
			}
			rows = append(rows, row)
		}
		spec[selected.outputKey] = rows
		quality.Datasets = append(quality.Datasets, DatasetUse{
			Role: selected.role, VersionID: dataset.ID, Name: dataset.Name,
			Kind: dataset.Kind, Source: dataset.Source, SHA256: dataset.Checksum,
			License: dataset.License, CapturedAt: dataset.CapturedAt, FeatureCount: len(rows),
		})
		if dataset.Kind == "observed" {
			quality.Warnings = append(quality.Warnings, selected.role+": observed is a supplier claim, not independent verification")
		}
		if dataset.License == nil || strings.TrimSpace(*dataset.License) == "" {
			quality.Warnings = append(quality.Warnings, selected.role+": license is not recorded")
		}
		manifest := map[string]any{"name": dataset.Name, "role": selected.role, "kind": dataset.Kind,
			"source": dataset.Source, "sha256": dataset.Checksum, "version_id": dataset.ID}
		if dataset.License != nil {
			manifest["license"] = *dataset.License
		}
		if dataset.CapturedAt != nil {
			manifest["captured_at"] = dataset.CapturedAt.UTC().Format(time.RFC3339)
		}
		manifests = append(manifests, manifest)
	}
	sections, err := json.Marshal(map[string]json.RawMessage{
		"options": request.Options, "parameters": request.Parameters, "scenarios": request.Scenarios})
	if err != nil {
		return PreparedScenario{}, err
	}
	sum := sha256.Sum256(sections)
	manifests = append(manifests, map[string]any{"name": "Request planning assumptions",
		"role": "planning_assumptions", "kind": "assumed",
		"source": "user-submitted equipment, parameters and uncertainty scenarios",
		"sha256": hex.EncodeToString(sum[:])})
	spec["datasets"] = manifests
	raw, err := json.Marshal(spec)
	if err != nil {
		return PreparedScenario{}, err
	}
	if len(raw) > 4<<20 {
		return PreparedScenario{}, invalidDataset("assembled scenario exceeds 4 MiB")
	}
	if err := b.Validator.Validate(ctx, raw); err != nil {
		return PreparedScenario{}, err
	}
	return PreparedScenario{Spec: raw, DataQuality: quality}, nil
}

func (b DatasetBuilder) Create(ctx context.Context, request DatasetBuildRequest) (Scenario, DataQuality, error) {
	prepared, err := b.Prepare(ctx, request)
	if err != nil {
		return Scenario{}, DataQuality{}, err
	}
	saved, err := b.Repository.CreateScenario(ctx, strings.TrimSpace(request.Name), prepared.Spec)
	return saved, prepared.DataQuality, err
}

func mapPlanningFeature(dataset PlanningDataset, feature PlanningFeature, selected selectedDataset, timeZone string) (map[string]any, error) {
	label := fmt.Sprintf("dataset %s feature %q", dataset.ID, feature.ExternalID)
	if feature.FeatureType != selected.featureType {
		return nil, invalidDataset(label + ": expected feature_type " + selected.featureType)
	}
	if selected.point && (feature.GeometryType != "POINT" || feature.Latitude == nil || feature.Longitude == nil) {
		return nil, invalidDataset(label + ": Point geometry required")
	}
	if selected.featureType != "travel_edge" && strings.TrimSpace(feature.ExternalID) == "" {
		return nil, invalidDataset(label + ": GeoJSON feature id required")
	}
	var properties map[string]json.RawMessage
	if err := json.Unmarshal(feature.Properties, &properties); err != nil || properties == nil {
		return nil, invalidDataset(label + ": properties must be an object")
	}
	for key := range properties {
		if !selected.allowed[key] {
			return nil, invalidDataset(label + ": unsupported property " + key)
		}
	}
	for _, key := range selected.required {
		value, ok := properties[key]
		if !ok || len(value) == 0 || string(value) == "null" {
			return nil, invalidDataset(label + ": missing " + key)
		}
	}
	if selected.hourly {
		var actualZone string
		if err := json.Unmarshal(properties["time_zone"], &actualZone); err != nil || actualZone != timeZone {
			return nil, invalidDataset(label + ": time_zone differs from requested planning time_zone")
		}
	}
	delete(properties, "feature_type")
	delete(properties, "time_zone")
	row := make(map[string]any, len(properties)+4)
	for key, value := range properties {
		row[key] = value
	}
	if selected.featureType != "travel_edge" {
		row["id"] = feature.ExternalID
	}
	if selected.point && selected.featureType != "grid_node" {
		row["latitude"] = *feature.Latitude
		row["longitude"] = *feature.Longitude
	}
	if selected.featureType != "travel_edge" {
		source := fmt.Sprintf("dataset_version=%s; source=%s; sha256=%s", dataset.ID, dataset.Source, dataset.Checksum)
		provenance := map[string]any{"kind": dataset.Kind, "source": source}
		if dataset.CapturedAt != nil {
			provenance["captured_at"] = dataset.CapturedAt.UTC().Format(time.RFC3339)
		}
		row["provenance"] = provenance
	}
	return row, nil
}
