package planning

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
)

// MobilityPreviewRequest keeps the validated planning input and the mobility
// itinerary separate. The compiler must not mutate or persist the input.
type MobilityPreviewRequest struct {
	Input    json.RawMessage `json:"input"`
	Mobility json.RawMessage `json:"mobility"`
}

type MobilityPreview struct {
	Spec             json.RawMessage `json:"spec"`
	Requests         json.RawMessage `json:"requests"`
	CalendarProfiles json.RawMessage `json:"calendar_profiles"`
	Audit            json.RawMessage `json:"audit"`
	SourceSHA256     string          `json:"source_sha256"`
	// Exactly the UTF-8 bytes hashed by the compiler. Optional for previews,
	// mandatory for durable saves and their independent checksum verification.
	SourceCanonicalJSON     string `json:"source_canonical_json,omitempty"`
	CompilerSourceSHA256    string `json:"compiler_source_sha256,omitempty"`
	CompilerPydanticVersion string `json:"compiler_pydantic_version,omitempty"`
}

type MobilityCompiler interface {
	Compile(context.Context, MobilityPreviewRequest) (MobilityPreview, error)
}

type MobilityPreviewService struct {
	Compiler  MobilityCompiler
	Validator InputValidator
}

var ErrMobilityCompilerUnavailable = errors.New("mobility compiler unavailable")
var ErrMobilityInvalidResponse = errors.New("invalid mobility compiler response")

func jsonIsObject(value json.RawMessage) bool {
	value = bytes.TrimSpace(value)
	return len(value) > 0 && value[0] == '{' && json.Valid(value)
}

func (s MobilityPreviewService) Preview(ctx context.Context, input MobilityPreviewRequest) (MobilityPreview, error) {
	if !jsonIsObject(input.Input) || !jsonIsObject(input.Mobility) {
		return MobilityPreview{}, InvalidInputError{Detail: "input and mobility must be JSON objects"}
	}
	if s.Compiler == nil || s.Validator == nil {
		return MobilityPreview{}, ErrMobilityCompilerUnavailable
	}
	preview, err := s.Compiler.Compile(ctx, input)
	if err != nil {
		return MobilityPreview{}, err
	}
	if !jsonIsObject(preview.Spec) || !jsonIsObject(preview.Audit) ||
		!jsonIsArray(preview.Requests) || !jsonIsArray(preview.CalendarProfiles) ||
		len(preview.SourceSHA256) != 64 {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	if _, err := hex.DecodeString(preview.SourceSHA256); err != nil {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	canonical := []byte(preview.SourceCanonicalJSON)
	if len(canonical) == 0 || len(canonical) > maxPersistedMobilityBytes || !jsonIsObject(canonical) ||
		len(preview.CompilerSourceSHA256) != 64 ||
		strings.ToLower(preview.CompilerSourceSHA256) != preview.CompilerSourceSHA256 ||
		preview.CompilerPydanticVersion == "" || len(preview.CompilerPydanticVersion) > 80 {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	if _, err := hex.DecodeString(preview.CompilerSourceSHA256); err != nil {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	sum := sha256.Sum256(canonical)
	if hex.EncodeToString(sum[:]) != preview.SourceSHA256 {
		return MobilityPreview{}, ErrMobilityInvalidResponse
	}
	if err := s.Validator.Validate(ctx, preview.Spec); err != nil {
		if errors.Is(err, ErrInvalidScenario) {
			return MobilityPreview{}, ErrMobilityInvalidResponse
		}
		return MobilityPreview{}, err
	}
	return preview, nil
}

func jsonIsArray(value json.RawMessage) bool {
	value = bytes.TrimSpace(value)
	return len(value) > 0 && value[0] == '[' && json.Valid(value)
}
