package artifact

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"strings"
	"sync"
	"testing"
)

const testDemand = `{"schema_version":"demand-dataset-v1","service_calendar":{"schema_version":"service-calendar-v1","time_zone":"Europe/Moscow","covered_dates":["2027-05-03"],"request_zone_ids":["z1"],"days":[{"date":"2027-05-03","day_type":"weekday","season":"spring"}]},"charging_requests":[]}`

func TestLocalArtifactImmutabilityAndIntegrity(t *testing.T) {
	ctx := context.Background()
	local := Local{Root: t.TempDir()}
	if _, err := ParseDemandDocument([]byte(testDemand)); err != nil {
		t.Fatal(err)
	}
	m, err := local.Put(ctx, []byte(testDemand))
	if err != nil {
		t.Fatal(err)
	}
	if m.ArtifactID != "sha256:"+m.SHA256 || m.ByteSize != int64(len(testDemand)) {
		t.Fatalf("wrong content address: %+v", m)
	}
	content, err := local.Read(ctx, m)
	if err != nil || string(content) != testDemand {
		t.Fatalf("wrong artifact bytes: %v", err)
	}
	const writers = 12
	var wg sync.WaitGroup
	for range writers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			got, err := local.Put(ctx, []byte(testDemand))
			if err != nil || got != m {
				t.Errorf("concurrent put = %+v %v", got, err)
			}
		}()
	}
	wg.Wait()
	// Even equal-sized replacement bytes are detected on replay.
	corrupt := []byte(testDemand)
	corrupt[len(corrupt)-2] = ' '
	if err := os.WriteFile(local.path(m.SHA256), corrupt, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := local.Read(ctx, m); !errors.Is(err, ErrIntegrity) {
		t.Fatalf("corruption accepted: %v", err)
	}
	if _, err := local.Put(ctx, []byte(testDemand)); !errors.Is(err, ErrIntegrity) {
		t.Fatalf("corrupt existing content address overwritten: %v", err)
	}
}

func TestManifestAndDocumentRejectMalformedInputs(t *testing.T) {
	m := Manifest{SchemaVersion: "demand-dataset-v1", SHA256: strings.Repeat("a", 64),
		ArtifactID: "sha256:" + strings.Repeat("a", 64), ByteSize: 10}
	for _, edit := range []func(*Manifest){
		func(x *Manifest) { x.SHA256 = "../../etc/passwd" },
		func(x *Manifest) { x.ArtifactID = "file:///etc/passwd" },
		func(x *Manifest) { x.ByteSize = MaxBytes + 1 },
		func(x *Manifest) { x.SchemaVersion = "demand-dataset-v2" },
	} {
		bad := m
		edit(&bad)
		if bad.Validate() == nil {
			t.Errorf("accepted invalid manifest: %+v", bad)
		}
	}
	for _, raw := range []string{
		`null`, `[]`, `{}`, `{"schema_version":"demand-dataset-v1","service_calendar":{},"charging_requests":null}`,
		`{"schema_version":"demand-dataset-v1","service_calendar":{},"charging_requests":[],"extra":1}`,
		`{"schema_version":"demand-dataset-v1","schema_version":"demand-dataset-v1","service_calendar":{},"charging_requests":[]}`,
		`{"schema_version":"demand-dataset-v1","service_calendar":{"time_zone":"UTC","time_zone":"Europe/Moscow"},"charging_requests":[]}`,
	} {
		if _, err := ParseDemandDocument([]byte(raw)); !errors.Is(err, ErrInvalid) {
			t.Errorf("accepted invalid document %s: %v", raw, err)
		}
	}
	raw, _ := json.Marshal(m)
	if _, err := ParseManifest(append(raw[:len(raw)-1], []byte(`,"sha256":"`+strings.Repeat("b", 64)+`"}`)...)); !errors.Is(err, ErrInvalid) {
		t.Fatalf("duplicate checksum accepted: %v", err)
	}
}

func TestHydrateDemandPreservesLegacyAndBindsVerifiedBytes(t *testing.T) {
	ctx := context.Background()
	local := Local{Root: t.TempDir()}
	legacy := json.RawMessage(`{"id":"legacy"}`)
	got, manifest, err := HydrateDemand(ctx, legacy, nil)
	if err != nil || manifest != nil || string(got) != string(legacy) {
		t.Fatalf("legacy input changed: %s %+v %v", got, manifest, err)
	}
	m, err := local.Put(ctx, []byte(testDemand))
	if err != nil {
		t.Fatal(err)
	}
	ref, _ := json.Marshal(map[string]any{"id": "test", "demand_dataset": m})
	hydrated, used, err := HydrateDemand(ctx, ref, local)
	if err != nil || used == nil || *used != m {
		t.Fatalf("unable to hydrate: %v %+v", err, used)
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(hydrated, &fields) != nil || string(fields["charging_requests"]) != "[]" ||
		len(fields["service_calendar"]) == 0 || len(fields["demand_dataset"]) == 0 {
		t.Fatalf("hydrated payload lost source or dated fields: %s", hydrated)
	}
	if _, _, err := HydrateDemand(ctx, ref, nil); !errors.Is(err, ErrNotFound) {
		t.Fatalf("unconfigured storage accepted: %v", err)
	}
	var conflicted map[string]any
	if err := json.Unmarshal(ref, &conflicted); err != nil {
		t.Fatal(err)
	}
	conflicted["charging_requests"] = []any{}
	bad, _ := json.Marshal(conflicted)
	if _, _, err := HydrateDemand(ctx, bad, local); !errors.Is(err, ErrInvalid) {
		t.Fatalf("inline and referenced demand both accepted: %v", err)
	}
	// The hash, not a client-controlled path or metadata label, decides bytes.
	other := m
	other.SHA256 = strings.Repeat("0", 64)
	other.ArtifactID = "sha256:" + other.SHA256
	conflicted = map[string]any{"demand_dataset": other}
	bad, _ = json.Marshal(conflicted)
	if _, _, err := HydrateDemand(ctx, bad, local); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing content accepted: %v", err)
	}
	sum := sha256.Sum256([]byte(testDemand))
	if m.SHA256 != hex.EncodeToString(sum[:]) {
		t.Fatal("incorrect SHA-256")
	}
}
