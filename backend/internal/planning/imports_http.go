package planning

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
)

type HTTPDeriver struct {
	URL    string
	Client *http.Client
}

func (d HTTPDeriver) Derive(ctx context.Context, spec json.RawMessage, in ImportInput, versionID string) (DerivedInput, error) {
	if d.URL == "" {
		return DerivedInput{}, ErrDeriverUnavailable
	}
	body, err := json.Marshal(struct {
		Input            json.RawMessage `json:"input"`
		DatasetVersionID string          `json:"dataset_version_id"`
		DatasetName      string          `json:"dataset_name"`
		CSVBase64        string          `json:"csv_base64"`
		Role             string          `json:"role"`
		Source           string          `json:"source"`
		Kind             string          `json:"kind"`
		TimeZone         string          `json:"time_zone"`
		License          *string         `json:"license,omitempty"`
		StartDate        *string         `json:"start_date,omitempty"`
		EndDate          *string         `json:"end_date,omitempty"`
		ProfileDate      *string         `json:"profile_date,omitempty"`
	}{
		Input: spec, DatasetVersionID: versionID, DatasetName: in.DatasetName,
		CSVBase64: base64.StdEncoding.EncodeToString(in.CSV), Role: in.Role,
		Source: in.Source, Kind: in.Kind, TimeZone: in.TimeZone,
		License: optionalString(in.License), StartDate: optionalString(in.StartDate),
		EndDate: optionalString(in.EndDate), ProfileDate: optionalString(in.ProfileDate),
	})
	if err != nil {
		return DerivedInput{}, ErrDeriverUnavailable
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(d.URL, "/")+"/v1/derive", bytes.NewReader(body))
	if err != nil {
		return DerivedInput{}, ErrDeriverUnavailable
	}
	request.Header.Set("Content-Type", "application/json")
	client := d.Client
	if client == nil {
		client = &http.Client{Timeout: 90 * time.Second}
	}
	response, err := client.Do(request)
	if err != nil {
		return DerivedInput{}, ErrDeriverUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusUnprocessableEntity || response.StatusCode == http.StatusRequestEntityTooLarge {
		var payload struct {
			Detail json.RawMessage `json:"detail"`
		}
		_ = json.NewDecoder(io.LimitReader(response.Body, 1<<16)).Decode(&payload)
		if response.StatusCode == http.StatusRequestEntityTooLarge {
			return DerivedInput{}, ErrImportTooLarge
		}
		detail := "CSV cannot be applied to this scenario"
		if len(payload.Detail) > 0 {
			if payload.Detail[0] == '"' {
				_ = json.Unmarshal(payload.Detail, &detail)
			} else {
				var entries []struct {
					Msg string `json:"msg"`
				}
				if json.Unmarshal(payload.Detail, &entries) == nil && len(entries) > 0 {
					detail = entries[0].Msg
				}
			}
		}
		return DerivedInput{}, invalidImport(detail)
	}
	if response.StatusCode != http.StatusOK {
		return DerivedInput{}, ErrDeriverUnavailable
	}
	var output DerivedInput
	if err := json.NewDecoder(io.LimitReader(response.Body, (4<<20)+4096)).Decode(&output); err != nil ||
		len(output.Spec) == 0 || output.SHA256 == "" || output.TransformVersion == "" {
		return DerivedInput{}, ErrDeriverUnavailable
	}
	return output, nil
}

func optionalString(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}
