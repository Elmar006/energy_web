package artifact

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
)

type DemandDocument struct {
	SchemaVersion    string          `json:"schema_version"`
	ServiceCalendar  json.RawMessage `json:"service_calendar"`
	ChargingRequests json.RawMessage `json:"charging_requests"`
}

// ParseDemandDocument checks the artifact envelope. The planning engine owns
// the domain validation of dates, zones, energy, SoC and provenance when the
// complete input is validated or calculated.
func ParseDemandDocument(content []byte) (DemandDocument, error) {
	var document DemandDocument
	if len(content) == 0 || len(content) > MaxBytes || strictObject(content, &document) != nil ||
		document.SchemaVersion != "demand-dataset-v1" ||
		!jsonObject(document.ServiceCalendar) || !jsonArray(document.ChargingRequests) {
		return DemandDocument{}, ErrInvalid
	}
	return document, nil
}

func jsonObject(raw json.RawMessage) bool {
	raw = bytes.TrimSpace(raw)
	return len(raw) > 0 && raw[0] == '{' && json.Valid(raw)
}

func jsonArray(raw json.RawMessage) bool {
	raw = bytes.TrimSpace(raw)
	return len(raw) > 0 && raw[0] == '[' && json.Valid(raw)
}

func strictObject(raw []byte, target any) error {
	if !jsonObject(raw) {
		return ErrInvalid
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := uniqueJSONValue(decoder); err != nil ||
		!errors.Is(decoder.Decode(new(any)), io.EOF) {
		return ErrInvalid
	}
	decoder = json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil {
		return ErrInvalid
	}
	return nil
}

func uniqueJSONValue(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	switch token {
	case json.Delim('{'):
		seen := make(map[string]bool)
		for decoder.More() {
			name, err := decoder.Token()
			key, ok := name.(string)
			if err != nil || !ok || seen[key] {
				return ErrInvalid
			}
			seen[key] = true
			if err := uniqueJSONValue(decoder); err != nil {
				return err
			}
		}
		_, err := decoder.Token()
		return err
	case json.Delim('['):
		for decoder.More() {
			if err := uniqueJSONValue(decoder); err != nil {
				return err
			}
		}
		_, err := decoder.Token()
		return err
	}
	return nil
}

// HydrateDemand verifies a content-addressed artifact and inserts its exact
// calendar and request arrays before the input reaches the Python engine.
// The persisted scenario keeps only the manifest and therefore remains small.
func HydrateDemand(ctx context.Context, spec json.RawMessage, reader Reader) (json.RawMessage, *Manifest, error) {
	if !jsonObject(spec) {
		return nil, nil, ErrInvalid
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(spec, &fields); err != nil {
		return nil, nil, ErrInvalid
	}
	raw, hasRef := fields["demand_dataset"]
	if !hasRef {
		return spec, nil, nil
	}
	decoder := json.NewDecoder(bytes.NewReader(spec))
	if uniqueJSONValue(decoder) != nil || !errors.Is(decoder.Decode(new(any)), io.EOF) {
		return nil, nil, ErrInvalid
	}
	if _, exists := fields["service_calendar"]; exists {
		return nil, nil, ErrInvalid
	}
	if _, exists := fields["charging_requests"]; exists {
		return nil, nil, ErrInvalid
	}
	m, err := ParseManifest(raw)
	if err != nil {
		return nil, nil, err
	}
	if reader == nil {
		return nil, nil, ErrNotFound
	}
	content, err := reader.Read(ctx, m)
	if err != nil {
		return nil, nil, err
	}
	document, err := ParseDemandDocument(content)
	if err != nil {
		return nil, nil, err
	}
	fields["service_calendar"] = document.ServiceCalendar
	fields["charging_requests"] = document.ChargingRequests
	hydrated, err := json.Marshal(fields)
	if err != nil {
		return nil, nil, err
	}
	return hydrated, &m, nil
}
