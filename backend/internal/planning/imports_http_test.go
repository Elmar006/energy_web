package planning

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestHTTPDeriverTransmitsExactCSVAndClassifiesFailures(t *testing.T) {
	in := validSessionImport()
	versionID := "01234567-89ab-4cde-8fab-0123456789ab"
	var status atomic.Int32
	status.Store(200)
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/derive" ||
			r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		var body struct {
			Input            json.RawMessage `json:"input"`
			CSVBase64        string          `json:"csv_base64"`
			DatasetVersionID string          `json:"dataset_version_id"`
			StartDate        string          `json:"start_date"`
			EndDate          string          `json:"end_date"`
		}
		if json.NewDecoder(r.Body).Decode(&body) != nil ||
			body.DatasetVersionID != versionID || body.StartDate != in.StartDate ||
			body.EndDate != in.EndDate || string(body.Input) != `{"id":"base"}` {
			t.Errorf("wrong derivation request: %+v", body)
		}
		decoded, err := base64.StdEncoding.DecodeString(body.CSVBase64)
		if err != nil || string(decoded) != string(in.CSV) {
			t.Errorf("CSV bytes changed in transport: %v", err)
		}
		code := int(status.Load())
		w.WriteHeader(code)
		if code == 422 {
			_, _ = w.Write([]byte(`{"detail":"row 2: unknown zone_id"}`))
			return
		}
		if code == 200 {
			sum := sha256.Sum256(in.CSV)
			_ = json.NewEncoder(w).Encode(DerivedInput{Spec: json.RawMessage(`{"id":"derived"}`),
				SHA256: hex.EncodeToString(sum[:]), TransformVersion: "test-transform-v1"})
		}
	}))
	defer engine.Close()
	deriver := HTTPDeriver{URL: engine.URL}
	derived, err := deriver.Derive(context.Background(), json.RawMessage(`{"id":"base"}`), in, versionID)
	if err != nil || string(derived.Spec) != `{"id":"derived"}` {
		t.Fatalf("good response not preserved: %+v %v", derived, err)
	}
	status.Store(422)
	_, err = deriver.Derive(context.Background(), json.RawMessage(`{"id":"base"}`), in, versionID)
	if !errors.Is(err, ErrInvalidImport) || !strings.Contains(err.Error(), "unknown zone_id") {
		t.Fatalf("bad CSV misclassified: %v", err)
	}
	status.Store(500)
	_, err = deriver.Derive(context.Background(), json.RawMessage(`{"id":"base"}`), in, versionID)
	if !errors.Is(err, ErrDeriverUnavailable) {
		t.Fatalf("engine failure misclassified: %v", err)
	}
}
