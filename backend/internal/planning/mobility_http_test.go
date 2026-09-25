package planning

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHTTPMobilityCompilerProtocol(t *testing.T) {
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/mobility/compile" ||
			r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("unexpected engine request: %s %s %s", r.Method, r.URL.Path, r.Header.Get("Content-Type"))
		}
		var request MobilityPreviewRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil ||
			string(request.Input) != `{"id":"base"}` || string(request.Mobility) != `{"schema_version":"mobility-v1"}` {
			t.Errorf("request changed at adapter: %s, %v", request.Input, err)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(validMobilityPreview())
	}))
	defer engine.Close()
	compiler := HTTPMobilityCompiler{URL: engine.URL}
	output, err := compiler.Compile(context.Background(), MobilityPreviewRequest{
		Input: json.RawMessage(`{"id":"base"}`), Mobility: json.RawMessage(`{"schema_version":"mobility-v1"}`)})
	if err != nil || string(output.Spec) != `{"id":"compiled"}` {
		t.Fatalf("compiler response lost: %+v %v", output, err)
	}
	for _, malformed := range []string{"", "ftp://example.test", "http://", "http://user:secret@example.test", "http://example.test/?token=x"} {
		if _, err := (HTTPMobilityCompiler{URL: malformed}).Compile(context.Background(), MobilityPreviewRequest{}); !errors.Is(err, ErrMobilityCompilerUnavailable) {
			t.Errorf("malformed engine URL accepted: %q %v", malformed, err)
		}
	}
}

func TestHTTPMobilityCompilerDistinguishesInvalidDataFromEngineFailure(t *testing.T) {
	for _, tc := range []struct {
		name, body string
		status     int
		want       error
	}{
		{"domain error", `{"detail":"impossible SoC"}`, 422, ErrInvalidScenario},
		{"schema error", `{"detail":[{"msg":"missing battery_kwh"}]}`, 422, ErrInvalidScenario},
		{"engine failure", `{"detail":"internal"}`, 500, ErrMobilityCompilerUnavailable},
		{"invalid JSON", `{"spec":`, 200, ErrMobilityInvalidResponse},
		{"oversized output", strings.Repeat(" ", maxMobilityResponseBytes+1), 200, ErrMobilityInvalidResponse},
	} {
		t.Run(tc.name, func(t *testing.T) {
			engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer engine.Close()
			_, err := (HTTPMobilityCompiler{URL: engine.URL}).Compile(context.Background(), MobilityPreviewRequest{})
			if !errors.Is(err, tc.want) {
				t.Fatalf("wrong error: %v", err)
			}
		})
	}
}

func TestHTTPMobilityCompilerHonorsContextCancellation(t *testing.T) {
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}))
	defer engine.Close()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := (HTTPMobilityCompiler{URL: engine.URL}).Compile(ctx, MobilityPreviewRequest{})
	if !errors.Is(err, ErrMobilityCompilerUnavailable) {
		t.Fatalf("canceled request did not stop compiler call: %v", err)
	}
}
