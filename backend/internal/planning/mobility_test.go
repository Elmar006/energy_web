package planning

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"testing"
)

type mobilityCompilerStub struct {
	result MobilityPreview
	err    error
	calls  int
}

func (c *mobilityCompilerStub) Compile(context.Context, MobilityPreviewRequest) (MobilityPreview, error) {
	c.calls++
	return c.result, c.err
}

type mobilityValidatorStub struct {
	err   error
	calls int
}

func (v *mobilityValidatorStub) Validate(context.Context, json.RawMessage) error {
	v.calls++
	return v.err
}

func validMobilityPreview() MobilityPreview {
	source := `{"schema_version":"mobility-v1","source":"survey","source_kind":"assumed"}`
	sum := sha256.Sum256([]byte(source))
	return MobilityPreview{
		Spec:                    json.RawMessage(`{"id":"compiled"}`),
		Requests:                json.RawMessage(`[]`),
		CalendarProfiles:        json.RawMessage(`[{"date":"2027-01-01"}]`),
		Audit:                   json.RawMessage(`{"request_count":0}`),
		SourceSHA256:            hex.EncodeToString(sum[:]),
		SourceCanonicalJSON:     source,
		CompilerSourceSHA256:    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		CompilerPydanticVersion: "2.12.0",
	}
}

func TestMobilityPreviewServiceValidatesInputAndCompilerOutput(t *testing.T) {
	compiler := &mobilityCompilerStub{result: validMobilityPreview()}
	validator := &mobilityValidatorStub{}
	service := MobilityPreviewService{Compiler: compiler, Validator: validator}
	for _, input := range []MobilityPreviewRequest{
		{Input: json.RawMessage(`null`), Mobility: json.RawMessage(`{}`)},
		{Input: json.RawMessage(`[]`), Mobility: json.RawMessage(`{}`)},
		{Input: json.RawMessage(`{}`), Mobility: json.RawMessage(`false`)},
	} {
		if _, err := service.Preview(context.Background(), input); !errors.Is(err, ErrInvalidScenario) {
			t.Fatalf("bad input was accepted: %v", err)
		}
	}
	if compiler.calls != 0 || validator.calls != 0 {
		t.Fatal("invalid input reached the compiler or validator")
	}
	request := MobilityPreviewRequest{Input: json.RawMessage(`{}`), Mobility: json.RawMessage(`{}`)}
	if _, err := service.Preview(context.Background(), request); err != nil {
		t.Fatalf("valid compiler response rejected: %v", err)
	}
	if compiler.calls != 1 || validator.calls != 1 {
		t.Fatal("compiler output was not validated")
	}
	compiler.result.SourceSHA256 = "bad"
	if _, err := service.Preview(context.Background(), request); !errors.Is(err, ErrMobilityInvalidResponse) {
		t.Fatalf("invalid source hash passed: %v", err)
	}
	if validator.calls != 1 {
		t.Fatal("invalid compiler output reached validator")
	}
	compiler.result = validMobilityPreview()
	validator.err = InvalidInputError{Detail: "bad compiled planning input"}
	if _, err := service.Preview(context.Background(), request); !errors.Is(err, ErrMobilityInvalidResponse) {
		t.Fatalf("invalid compiled spec was treated as client error: %v", err)
	}
}

func TestMobilityPreviewServiceRejectsIncompleteCompilerResponse(t *testing.T) {
	request := MobilityPreviewRequest{Input: json.RawMessage(`{}`), Mobility: json.RawMessage(`{}`)}
	for name, mutate := range map[string]func(*MobilityPreview){
		"missing spec":       func(p *MobilityPreview) { p.Spec = nil },
		"requests not array": func(p *MobilityPreview) { p.Requests = json.RawMessage(`{}`) },
		"missing calendar":   func(p *MobilityPreview) { p.CalendarProfiles = nil },
		"audit not object":   func(p *MobilityPreview) { p.Audit = json.RawMessage(`[]`) },
		"nonhex hash": func(p *MobilityPreview) {
			p.SourceSHA256 = "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
		},
		"missing canonical source":   func(p *MobilityPreview) { p.SourceCanonicalJSON = "" },
		"canonical hash mismatch":    func(p *MobilityPreview) { p.SourceCanonicalJSON += " " },
		"missing compiler digest":    func(p *MobilityPreview) { p.CompilerSourceSHA256 = "" },
		"missing dependency version": func(p *MobilityPreview) { p.CompilerPydanticVersion = "" },
	} {
		t.Run(name, func(t *testing.T) {
			compiler := &mobilityCompilerStub{result: validMobilityPreview()}
			mutate(&compiler.result)
			validator := &mobilityValidatorStub{}
			_, err := (MobilityPreviewService{Compiler: compiler, Validator: validator}).Preview(context.Background(), request)
			if !errors.Is(err, ErrMobilityInvalidResponse) || validator.calls != 0 {
				t.Fatalf("malformed compiler output accepted or validated: %v, calls=%d", err, validator.calls)
			}
		})
	}
}
