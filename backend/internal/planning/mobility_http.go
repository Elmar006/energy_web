package planning

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const maxMobilityResponseBytes = 16 << 20

type HTTPMobilityCompiler struct {
	URL    string
	Client *http.Client
}

func (c HTTPMobilityCompiler) Compile(ctx context.Context, input MobilityPreviewRequest) (MobilityPreview, error) {
	base, err := url.Parse(c.URL)
	if err != nil || base == nil || (base.Scheme != "http" && base.Scheme != "https") ||
		base.Host == "" || base.User != nil || base.RawQuery != "" || base.Fragment != "" {
		return MobilityPreview{}, ErrMobilityCompilerUnavailable
	}
	body, err := json.Marshal(input)
	if err != nil {
		return MobilityPreview{}, ErrMobilityCompilerUnavailable
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(c.URL, "/")+"/v1/mobility/compile", bytes.NewReader(body))
	if err != nil {
		return MobilityPreview{}, ErrMobilityCompilerUnavailable
	}
	request.Header.Set("Content-Type", "application/json")
	client := c.Client
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	}
	response, err := client.Do(request)
	if err != nil {
		return MobilityPreview{}, ErrMobilityCompilerUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusUnprocessableEntity {
		return MobilityPreview{}, InvalidInputError{Detail: mobilityValidationDetail(response.Body)}
	}
	if response.StatusCode != http.StatusOK {
		return MobilityPreview{}, ErrMobilityCompilerUnavailable
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, maxMobilityResponseBytes+1))
	if err != nil || len(raw) > maxMobilityResponseBytes {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	var preview MobilityPreview
	if err := json.Unmarshal(raw, &preview); err != nil {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	return preview, nil
}

func mobilityValidationDetail(body io.Reader) string {
	const fallback = "mobility itinerary does not match the planning input"
	var payload struct {
		Detail json.RawMessage `json:"detail"`
	}
	if json.NewDecoder(io.LimitReader(body, 1<<16)).Decode(&payload) != nil {
		return fallback
	}
	var detail string
	if json.Unmarshal(payload.Detail, &detail) == nil && detail != "" {
		return truncateMobilityError(detail)
	}
	var entries []struct {
		Msg string `json:"msg"`
	}
	if json.Unmarshal(payload.Detail, &entries) == nil && len(entries) > 0 && entries[0].Msg != "" {
		return truncateMobilityError(entries[0].Msg)
	}
	return fallback
}

func truncateMobilityError(value string) string {
	if len(value) > 512 {
		return value[:512]
	}
	return value
}
