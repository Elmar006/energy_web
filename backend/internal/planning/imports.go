package planning

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"
)

const MaxSessionCSV = 50 << 20
const MaxGridCSV = 10 << 20

var ErrInvalidImport = errors.New("invalid planning data import")
var ErrImportTooLarge = errors.New("planning data file too large")
var ErrDeriverUnavailable = errors.New("data derivation engine unavailable")

type ImportInput struct {
	ParentScenarioID string
	Role             string
	ScenarioName     string
	DatasetName      string
	FileName         string
	Source           string
	License          string
	Kind             string
	TimeZone         string
	StartDate        string
	EndDate          string
	ProfileDate      string
	CoverageComplete bool
	CSV              []byte
}

type DerivedInput struct {
	Spec             json.RawMessage `json:"spec"`
	SHA256           string          `json:"sha256"`
	TransformVersion string          `json:"transform_version"`
}

type ImportResult struct {
	Scenario  Scenario `json:"scenario"`
	DatasetID string   `json:"dataset_id"`
	Role      string   `json:"role"`
	SHA256    string   `json:"sha256"`
	Reused    bool     `json:"reused"`
}

type UploadedFile struct {
	Content  []byte
	FileName string
	SHA256   string
	Role     string
}

type UploadRepository interface {
	GetUploadedFile(context.Context, string) (UploadedFile, error)
}

type UploadQueries struct{ Repository UploadRepository }

func (q UploadQueries) Download(ctx context.Context, datasetID string) (UploadedFile, error) {
	return q.Repository.GetUploadedFile(ctx, datasetID)
}

type ImportRepository interface {
	GetScenario(context.Context, string) (Scenario, error)
	SaveScenarioImport(context.Context, ImportInput, json.RawMessage, string, string, string, string) (ImportResult, error)
}

type InputDeriver interface {
	Derive(context.Context, json.RawMessage, ImportInput, string) (DerivedInput, error)
}

type ImportService struct {
	Repository ImportRepository
	Deriver    InputDeriver
	Validator  InputValidator
}

func invalidImport(detail string) error { return fmt.Errorf("%w: %s", ErrInvalidImport, detail) }

func (in *ImportInput) normalize() error {
	in.ScenarioName = strings.TrimSpace(in.ScenarioName)
	in.DatasetName = strings.TrimSpace(in.DatasetName)
	in.Source = strings.TrimSpace(in.Source)
	in.License = strings.TrimSpace(in.License)
	in.TimeZone = strings.TrimSpace(in.TimeZone)
	in.FileName = strings.TrimSpace(in.FileName)
	if in.Role != "demand_sessions" && in.Role != "grid_headroom" {
		return invalidImport("role must be demand_sessions or grid_headroom")
	}
	if in.Kind != "observed" && in.Kind != "assumed" {
		return invalidImport("kind must be observed or assumed")
	}
	if in.ScenarioName == "" || utf8.RuneCountInString(in.ScenarioName) > 120 ||
		in.DatasetName == "" || utf8.RuneCountInString(in.DatasetName) > 120 ||
		in.Source == "" || utf8.RuneCountInString(in.Source) > 2048 ||
		utf8.RuneCountInString(in.License) > 2048 || len(in.FileName) > 255 {
		return invalidImport("scenario_name, dataset_name and source are required and must fit length limits")
	}
	if in.TimeZone == "" || len(in.TimeZone) > 128 {
		return invalidImport("time_zone must be an IANA time zone")
	}
	if _, err := time.LoadLocation(in.TimeZone); err != nil {
		return invalidImport("unknown IANA time_zone")
	}
	if len(in.CSV) == 0 {
		return invalidImport("CSV file is empty")
	}
	limit := MaxSessionCSV
	if in.Role == "grid_headroom" {
		limit = MaxGridCSV
	}
	if len(in.CSV) > limit {
		return ErrImportTooLarge
	}
	if in.Role == "demand_sessions" {
		start, first := time.Parse("2006-01-02", in.StartDate)
		end, second := time.Parse("2006-01-02", in.EndDate)
		if first != nil || second != nil || end.Before(start) || end.Sub(start) > 366*24*time.Hour || in.ProfileDate != "" {
			return invalidImport("start_date and end_date must span 1..367 calendar days; profile_date must be empty")
		}
	} else {
		if in.CoverageComplete {
			return invalidImport("coverage_complete applies only to demand_sessions")
		}
		if _, err := time.Parse("2006-01-02", in.ProfileDate); err != nil || in.StartDate != "" || in.EndDate != "" {
			return invalidImport("profile_date must be YYYY-MM-DD; start_date and end_date must be empty")
		}
	}
	return nil
}

func newUUID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:]), nil
}

func importDigest(in ImportInput, fileSHA, transformVersion string) (string, error) {
	// A length-delimited JSON array prevents ambiguous concatenations. Filename
	// is display metadata; it does not alter the derived scenario or import key.
	raw, err := json.Marshal([]string{in.ParentScenarioID, in.Role, in.ScenarioName,
		in.DatasetName, in.Source, in.License, in.Kind, in.TimeZone,
		in.StartDate, in.EndDate, in.ProfileDate, fmt.Sprint(in.CoverageComplete), fileSHA, transformVersion})
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

func (s ImportService) Import(ctx context.Context, in ImportInput) (ImportResult, error) {
	if err := in.normalize(); err != nil {
		return ImportResult{}, err
	}
	if s.Repository == nil || s.Deriver == nil || s.Validator == nil {
		return ImportResult{}, ErrDeriverUnavailable
	}
	parent, err := s.Repository.GetScenario(ctx, in.ParentScenarioID)
	if err != nil {
		return ImportResult{}, err
	}
	versionID, err := newUUID()
	if err != nil {
		return ImportResult{}, err
	}
	fileHash := sha256.Sum256(in.CSV)
	fileSHA := hex.EncodeToString(fileHash[:])
	derived, err := s.Deriver.Derive(ctx, parent.Spec, in, versionID)
	if err != nil {
		return ImportResult{}, err
	}
	if derived.SHA256 != fileSHA || !json.Valid(derived.Spec) || len(derived.Spec) > 4<<20 ||
		derived.TransformVersion == "" || len(derived.TransformVersion) > 80 {
		return ImportResult{}, ErrDeriverUnavailable
	}
	var manifest struct {
		Datasets []struct {
			VersionID string `json:"version_id"`
			SHA256    string `json:"sha256"`
			Role      string `json:"role"`
			Kind      string `json:"kind"`
			Name      string `json:"name"`
			Version   string `json:"transform_version"`
		} `json:"datasets"`
	}
	if json.Unmarshal(derived.Spec, &manifest) != nil || len(manifest.Datasets) == 0 {
		return ImportResult{}, ErrDeriverUnavailable
	}
	last := manifest.Datasets[len(manifest.Datasets)-1]
	wantRole := in.Role
	if wantRole == "grid_headroom" {
		wantRole = "grid"
	}
	if last.VersionID != versionID || last.SHA256 != fileSHA || last.Kind != in.Kind ||
		last.Role != wantRole || last.Name != in.DatasetName || last.Version != derived.TransformVersion {
		return ImportResult{}, ErrDeriverUnavailable
	}
	if err := s.Validator.Validate(ctx, derived.Spec); err != nil {
		return ImportResult{}, err
	}
	key, err := importDigest(in, fileSHA, derived.TransformVersion)
	if err != nil {
		return ImportResult{}, err
	}
	return s.Repository.SaveScenarioImport(ctx, in, derived.Spec, versionID, fileSHA,
		derived.TransformVersion, key)
}
