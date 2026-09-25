package planning

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"
)

const maxPersistedMobilityBytes = 4 << 20

// MobilityPersist is the complete immutable provenance of a compiled scenario.
// The pre-transformation input is retained because the compiled input alone
// cannot reconstruct overwritten demand zones.
type MobilityPersist struct {
	Name                    string
	Spec                    json.RawMessage
	BaseInput               json.RawMessage
	CanonicalMobility       []byte
	SourceSHA256            string
	SourceKind              string
	SourceName              string
	License                 string
	DatasetVersionID        string
	AccessTokenSHA256       string
	CompilerVersion         string
	CompilerSourceSHA256    string
	CompilerPydanticVersion string
}

type MobilitySaveResult struct {
	Scenario          Scenario `json:"scenario"`
	DatasetVersionID  string   `json:"dataset_version_id"`
	SourceSHA256      string   `json:"source_sha256"`
	BaseSHA256        string   `json:"base_sha256"`
	SourceAccessToken string   `json:"source_access_token"`
}

type MobilityOrigin struct {
	ScenarioID              string          `json:"scenario_id"`
	DatasetVersionID        string          `json:"dataset_version_id"`
	BaseInput               json.RawMessage `json:"base_input"`
	BaseSHA256              string          `json:"base_sha256"`
	SourceCanonicalJSON     string          `json:"source_canonical_json"`
	SourceSHA256            string          `json:"source_sha256"`
	CompilerVersion         string          `json:"compiler_version"`
	CompilerSourceSHA256    string          `json:"compiler_source_sha256"`
	CompilerPydanticVersion string          `json:"compiler_pydantic_version"`
}

type MobilityRepository interface {
	SaveMobility(context.Context, MobilityPersist) (MobilitySaveResult, error)
	GetMobilityOrigin(context.Context, string, string) (MobilityOrigin, error)
}

type MobilitySaveService struct {
	PreviewService MobilityPreviewService
	Repository     MobilityRepository
}

func (s MobilitySaveService) Save(ctx context.Context, name string, input MobilityPreviewRequest) (MobilitySaveResult, error) {
	name = strings.TrimSpace(name)
	if name == "" || utf8.RuneCountInString(name) > 120 {
		return MobilitySaveResult{}, InvalidInputError{Detail: "name is required and must contain at most 120 characters"}
	}
	if s.Repository == nil {
		return MobilitySaveResult{}, errors.New("mobility repository unavailable")
	}
	preview, err := s.PreviewService.Preview(ctx, input)
	if err != nil {
		return MobilitySaveResult{}, err
	}
	source := []byte(preview.SourceCanonicalJSON)
	if len(source) == 0 || len(source) > maxPersistedMobilityBytes || !jsonIsObject(source) ||
		len(preview.Spec) > maxPersistedMobilityBytes {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	sum := sha256.Sum256(source)
	if hex.EncodeToString(sum[:]) != preview.SourceSHA256 {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	if len(preview.CompilerSourceSHA256) != 64 || preview.CompilerPydanticVersion == "" ||
		len(preview.CompilerPydanticVersion) > 80 {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	if _, err := hex.DecodeString(preview.CompilerSourceSHA256); err != nil {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	var canonical struct {
		SchemaVersion string  `json:"schema_version"`
		Source        string  `json:"source"`
		SourceKind    string  `json:"source_kind"`
		License       *string `json:"license"`
	}
	if json.Unmarshal(source, &canonical) != nil || canonical.SchemaVersion != "mobility-v1" ||
		(canonical.SourceKind != "observed" && canonical.SourceKind != "assumed") ||
		canonical.Source == "" || len(canonical.Source) > 2048 ||
		(canonical.License != nil && len(*canonical.License) > 2048) {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	var snapshot struct {
		Datasets []map[string]json.RawMessage `json:"datasets"`
	}
	if json.Unmarshal(preview.Spec, &snapshot) != nil || len(snapshot.Datasets) == 0 {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	last := snapshot.Datasets[len(snapshot.Datasets)-1]
	var manifest struct {
		Name             string  `json:"name"`
		Role             string  `json:"role"`
		Kind             string  `json:"kind"`
		SourceKind       string  `json:"source_kind"`
		Source           string  `json:"source"`
		License          *string `json:"license"`
		SHA256           string  `json:"sha256"`
		TransformVersion string  `json:"transform_version"`
		VersionID        string  `json:"version_id"`
	}
	manifestRaw, _ := json.Marshal(last)
	if json.Unmarshal(manifestRaw, &manifest) != nil ||
		manifest.Name != "mobility-v1 potential public requests" ||
		manifest.Role != "planning_assumptions" ||
		manifest.Kind != "derived" || manifest.SourceKind != canonical.SourceKind ||
		manifest.Source != canonical.Source ||
		manifest.SHA256 != preview.SourceSHA256 || manifest.TransformVersion != "mobility-v1" ||
		manifest.VersionID != "" {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	if (manifest.License == nil) != (canonical.License == nil) ||
		(manifest.License != nil && *manifest.License != *canonical.License) {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	versionID, err := newUUID()
	if err != nil {
		return MobilitySaveResult{}, err
	}
	// Bind the artifact to the immutable scenario manifest before validation.
	var spec map[string]json.RawMessage
	if json.Unmarshal(preview.Spec, &spec) != nil {
		return MobilitySaveResult{}, ErrMobilityInvalidResponse
	}
	last["version_id"], _ = json.Marshal(versionID)
	spec["datasets"], err = json.Marshal(snapshot.Datasets)
	if err != nil {
		return MobilitySaveResult{}, err
	}
	boundSpec, err := json.Marshal(spec)
	if err != nil {
		return MobilitySaveResult{}, err
	}
	if err := s.PreviewService.Validator.Validate(ctx, boundSpec); err != nil {
		if errors.Is(err, ErrInvalidScenario) {
			return MobilitySaveResult{}, ErrMobilityInvalidResponse
		}
		return MobilitySaveResult{}, err
	}
	var token [32]byte
	if _, err := rand.Read(token[:]); err != nil {
		return MobilitySaveResult{}, err
	}
	tokenHash := sha256.Sum256(token[:])
	license := ""
	if canonical.License != nil {
		license = *canonical.License
	}
	result, err := s.Repository.SaveMobility(ctx, MobilityPersist{
		Name: name, Spec: boundSpec, BaseInput: input.Input,
		CanonicalMobility: source, SourceSHA256: preview.SourceSHA256,
		SourceKind: canonical.SourceKind, SourceName: canonical.Source,
		License: license, DatasetVersionID: versionID,
		AccessTokenSHA256: hex.EncodeToString(tokenHash[:]), CompilerVersion: "mobility-v1",
		CompilerSourceSHA256:    preview.CompilerSourceSHA256,
		CompilerPydanticVersion: preview.CompilerPydanticVersion,
	})
	if err != nil {
		return MobilitySaveResult{}, err
	}
	result.SourceAccessToken = hex.EncodeToString(token[:])
	return result, nil
}

// Origin is deliberately capability-gated in addition to the API bearer token.
// A shared bearer token alone does not provide per-project authorization.
func (s MobilitySaveService) Origin(ctx context.Context, scenarioID, tokenHex string) (MobilityOrigin, error) {
	if s.Repository == nil || len(tokenHex) != 64 {
		return MobilityOrigin{}, ErrNotFound
	}
	token, err := hex.DecodeString(tokenHex)
	if err != nil || len(token) != 32 {
		return MobilityOrigin{}, ErrNotFound
	}
	sum := sha256.Sum256(token)
	return s.Repository.GetMobilityOrigin(ctx, scenarioID, hex.EncodeToString(sum[:]))
}
