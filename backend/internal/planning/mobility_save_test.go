package planning

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

type mobilitySaveRepositoryStub struct {
	writes int
	input  MobilityPersist
	origin MobilityOrigin
	token  string
}

func (r *mobilitySaveRepositoryStub) SaveMobility(_ context.Context, input MobilityPersist) (MobilitySaveResult, error) {
	r.writes++
	r.input = input
	return MobilitySaveResult{Scenario: Scenario{ID: "saved", Spec: input.Spec},
		DatasetVersionID: input.DatasetVersionID, SourceSHA256: input.SourceSHA256}, nil
}

func (r *mobilitySaveRepositoryStub) GetMobilityOrigin(_ context.Context, _, tokenHash string) (MobilityOrigin, error) {
	r.token = tokenHash
	if tokenHash != r.input.AccessTokenSHA256 {
		return MobilityOrigin{}, ErrNotFound
	}
	return r.origin, nil
}

func savedMobilityPreview() MobilityPreview {
	source := `{"schema_version":"mobility-v1","source":"local survey","source_kind":"assumed","license":null}`
	sum := sha256.Sum256([]byte(source))
	sha := hex.EncodeToString(sum[:])
	return MobilityPreview{Spec: json.RawMessage(`{"id":"compiled","datasets":[{"name":"mobility-v1 potential public requests","role":"planning_assumptions","kind":"derived","source_kind":"assumed","source":"local survey","license":null,"sha256":"` + sha + `","transform_version":"mobility-v1"}]}`),
		Requests: json.RawMessage(`[]`), CalendarProfiles: json.RawMessage(`[]`),
		Audit: json.RawMessage(`{}`), SourceSHA256: sha, SourceCanonicalJSON: source,
		CompilerSourceSHA256: strings.Repeat("a", 64), CompilerPydanticVersion: "2.12.0"}
}

func TestMobilitySaveBindsArtifactAndKeepsUntransformedInput(t *testing.T) {
	compiler := &mobilityCompilerStub{result: savedMobilityPreview()}
	validator := &mobilityValidatorStub{}
	repo := &mobilitySaveRepositoryStub{}
	service := MobilitySaveService{PreviewService: MobilityPreviewService{Compiler: compiler, Validator: validator}, Repository: repo}
	base := json.RawMessage(`{"id":"original","zones":[{"id":"a","hourly_kwh":[1]}]}`)
	result, err := service.Save(context.Background(), "  mobility plan  ", MobilityPreviewRequest{
		Input: base, Mobility: json.RawMessage(`{"schema_version":"mobility-v1"}`)})
	if err != nil {
		t.Fatal(err)
	}
	if repo.writes != 1 || repo.input.Name != "mobility plan" ||
		string(repo.input.BaseInput) != string(base) ||
		string(repo.input.CanonicalMobility) != compiler.result.SourceCanonicalJSON ||
		validator.calls != 2 || len(result.SourceAccessToken) != 64 {
		t.Fatalf("provenance was not saved and revalidated: %+v %+v", result, repo.input)
	}
	var bound struct {
		Datasets []struct {
			VersionID string `json:"version_id"`
			SHA256    string `json:"sha256"`
		} `json:"datasets"`
	}
	if json.Unmarshal(repo.input.Spec, &bound) != nil || len(bound.Datasets) != 1 ||
		bound.Datasets[0].VersionID != result.DatasetVersionID ||
		bound.Datasets[0].SHA256 != result.SourceSHA256 {
		t.Fatalf("saved scenario manifest does not identify the source version: %s", repo.input.Spec)
	}
	if _, err := service.Origin(context.Background(), "saved", "wrong"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("bad capability was accepted: %v", err)
	}
	_, err = service.Origin(context.Background(), "saved", result.SourceAccessToken)
	if err != nil || repo.token != repo.input.AccessTokenSHA256 {
		t.Fatalf("valid capability did not address hashed token: %v", err)
	}
}

func TestMobilitySaveRejectsInconsistentCompilerWithoutWriting(t *testing.T) {
	for name, mutate := range map[string]func(*MobilityPreview){
		"missing canonical source": func(p *MobilityPreview) { p.SourceCanonicalJSON = "" },
		"missing compiler digest":  func(p *MobilityPreview) { p.CompilerSourceSHA256 = "" },
		"hash mismatch":            func(p *MobilityPreview) { p.SourceCanonicalJSON += " " },
		"wrong source kind": func(p *MobilityPreview) {
			p.Spec = json.RawMessage(strings.ReplaceAll(string(p.Spec), `"source_kind":"assumed"`, `"source_kind":"observed"`))
		},
		"wrong manifest sha": func(p *MobilityPreview) {
			p.Spec = json.RawMessage(strings.ReplaceAll(string(p.Spec), p.SourceSHA256, strings.Repeat("0", 64)))
		},
		"injected version": func(p *MobilityPreview) {
			p.Spec = json.RawMessage(strings.ReplaceAll(string(p.Spec), `"transform_version":"mobility-v1"`,
				`"transform_version":"mobility-v1","version_id":"01234567-89ab-4cde-8fab-0123456789ab"`))
		},
	} {
		t.Run(name, func(t *testing.T) {
			compiler := &mobilityCompilerStub{result: savedMobilityPreview()}
			mutate(&compiler.result)
			repo := &mobilitySaveRepositoryStub{}
			service := MobilitySaveService{PreviewService: MobilityPreviewService{
				Compiler: compiler, Validator: &mobilityValidatorStub{}}, Repository: repo}
			_, err := service.Save(context.Background(), "plan", MobilityPreviewRequest{
				Input: json.RawMessage(`{}`), Mobility: json.RawMessage(`{}`)})
			if !errors.Is(err, ErrMobilityInvalidResponse) || repo.writes != 0 {
				t.Fatalf("invalid compiler response persisted: %v, writes=%d", err, repo.writes)
			}
		})
	}
}
