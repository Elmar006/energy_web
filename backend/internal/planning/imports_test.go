package planning

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"testing"
)

type importRepositoryStub struct {
	parent Scenario
	gets   int
	saves  int
	spec   json.RawMessage
	err    error
}

func (r *importRepositoryStub) GetScenario(context.Context, string) (Scenario, error) {
	r.gets++
	if r.err != nil {
		return Scenario{}, r.err
	}
	return r.parent, nil
}

func (r *importRepositoryStub) SaveScenarioImport(_ context.Context, _ ImportInput,
	spec json.RawMessage, versionID, fileSHA, _, _ string) (ImportResult, error) {
	r.saves++
	r.spec = spec
	return ImportResult{Scenario: Scenario{ID: "saved", Spec: spec},
		DatasetID: versionID, SHA256: fileSHA}, nil
}

type deriverStub struct {
	calls     int
	badSHA    bool
	badID     bool
	lastInput ImportInput
}

func (d *deriverStub) Derive(_ context.Context, _ json.RawMessage, in ImportInput, versionID string) (DerivedInput, error) {
	d.calls++
	d.lastInput = in
	fileHash := sha256.Sum256(in.CSV)
	sha := hex.EncodeToString(fileHash[:])
	if d.badSHA {
		sha = "wrong"
	}
	if d.badID {
		versionID = "wrong"
	}
	role := in.Role
	if role == "grid_headroom" {
		role = "grid"
	}
	spec, _ := json.Marshal(map[string]any{"datasets": []map[string]string{{
		"version_id": versionID, "sha256": hex.EncodeToString(fileHash[:]),
		"role": role, "kind": in.Kind, "name": in.DatasetName,
		"transform_version": "test-transform-v1",
	}}})
	return DerivedInput{Spec: spec, SHA256: sha, TransformVersion: "test-transform-v1"}, nil
}

func validSessionImport() ImportInput {
	return ImportInput{ParentScenarioID: "01234567-89ab-4cde-8fab-0123456789ab",
		Role: "demand_sessions", ScenarioName: "Observed plan", DatasetName: "April sessions",
		FileName: "sessions.csv", Source: "operator export", Kind: "observed",
		TimeZone: "Europe/Moscow", StartDate: "2027-04-01", EndDate: "2027-04-02",
		CSV: []byte("session_id,zone_id,started_at,ended_at,energy_kwh\n")}
}

func TestImportServiceValidatesBeforeDerivingAndPersistsExactSnapshot(t *testing.T) {
	repo := &importRepositoryStub{parent: Scenario{Spec: []byte(`{"id":"base"}`)}}
	deriver := &deriverStub{}
	validator := &fakeValidator{}
	service := ImportService{Repository: repo, Deriver: deriver, Validator: validator}
	in := validSessionImport()
	for _, mutate := range []func(*ImportInput){
		func(in *ImportInput) { in.TimeZone = "Wrong/Zone" },
		func(in *ImportInput) { in.EndDate = "2027-03-31" },
		func(in *ImportInput) { in.Kind = "derived" },
		func(in *ImportInput) { in.CSV = nil },
		func(in *ImportInput) { in.ScenarioName = "" },
	} {
		bad := in
		mutate(&bad)
		if _, err := service.Import(context.Background(), bad); !errors.Is(err, ErrInvalidImport) {
			t.Fatalf("bad input accepted: %v", err)
		}
	}
	if repo.gets != 0 || deriver.calls != 0 || repo.saves != 0 {
		t.Fatal("invalid upload reached an external dependency")
	}
	result, err := service.Import(context.Background(), in)
	if err != nil || result.DatasetID == "" || result.SHA256 == "" ||
		result.Scenario.ID != "saved" || repo.gets != 1 || deriver.calls != 1 ||
		validator.calls != 1 || repo.saves != 1 || string(repo.spec) != string(result.Scenario.Spec) {
		t.Fatalf("valid import not persisted: %+v, %v", result, err)
	}
	validator.err = InvalidInputError{Detail: "broken derived spec"}
	if _, err := service.Import(context.Background(), in); !errors.Is(err, ErrInvalidScenario) || repo.saves != 1 {
		t.Fatalf("validator failure persisted: %v", err)
	}
}

func TestImportServiceRejectsMissingParentAndEngineMismatch(t *testing.T) {
	repo := &importRepositoryStub{err: ErrNotFound}
	deriver := &deriverStub{}
	service := ImportService{Repository: repo, Deriver: deriver, Validator: &fakeValidator{}}
	if _, err := service.Import(context.Background(), validSessionImport()); !errors.Is(err, ErrNotFound) || deriver.calls != 0 {
		t.Fatalf("missing parent reached engine: %v", err)
	}
	repo.err = nil
	for _, bad := range []struct{ hash, id bool }{{hash: true}, {id: true}} {
		deriver.badSHA, deriver.badID = bad.hash, bad.id
		if _, err := service.Import(context.Background(), validSessionImport()); !errors.Is(err, ErrDeriverUnavailable) || repo.saves != 0 {
			t.Fatalf("untrusted engine output persisted: %v", err)
		}
	}
}

func TestGridImportRequiresProfileDateAndHasSeparateSizeLimit(t *testing.T) {
	in := validSessionImport()
	in.Role = "grid_headroom"
	in.StartDate, in.EndDate = "", ""
	if err := in.normalize(); !errors.Is(err, ErrInvalidImport) {
		t.Fatalf("missing profile date accepted: %v", err)
	}
	in.ProfileDate = "2026-09-01"
	if err := in.normalize(); err != nil {
		t.Fatal(err)
	}
	in.CoverageComplete = true
	if err := in.normalize(); !errors.Is(err, ErrInvalidImport) {
		t.Fatalf("grid import accepted session-only coverage flag: %v", err)
	}
	in.CoverageComplete = false
	in.CSV = make([]byte, MaxGridCSV+1)
	if err := in.normalize(); !errors.Is(err, ErrImportTooLarge) {
		t.Fatalf("oversize grid file accepted: %v", err)
	}
}

func TestImportIdentityIncludesTransformVersionAndObservationWindow(t *testing.T) {
	in := validSessionImport()
	first, err := importDigest(in, "sha", "metered-sessions-v2")
	if err != nil {
		t.Fatal(err)
	}
	changedModel, _ := importDigest(in, "sha", "metered-sessions-v3")
	in.EndDate = "2027-04-03"
	changedWindow, _ := importDigest(in, "sha", "metered-sessions-v2")
	in.EndDate = "2027-04-02"
	in.CoverageComplete = true
	changedCoverage, _ := importDigest(in, "sha", "metered-sessions-v2")
	if first == changedModel || first == changedWindow || first == changedCoverage {
		t.Fatal("a changed transformation or observation window reused the old scenario")
	}
}
