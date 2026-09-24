package geography

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"
)

type importRepositoryFake struct{ calls int }

func (f *importRepositoryFake) ImportDataset(_ context.Context, _ io.Reader, _ ImportMetadata) (ImportResult, error) {
	f.calls++
	return ImportResult{DatasetID: "saved", Features: 1, SHA256: "abc"}, nil
}

func TestImportRequiresExplicitProvenance(t *testing.T) {
	provider := &importRepositoryFake{}
	service := ImportService{Repository: provider}
	for _, meta := range []ImportMetadata{
		{Name: "", Kind: "assumed", Source: "supplier"},
		{Name: "zones", Kind: "observed", Source: "supplier"},
		{Name: "zones", Kind: "unknown", Source: "supplier"},
		{Name: "zones", Kind: "assumed", Source: ""},
	} {
		_, err := service.Import(context.Background(), strings.NewReader("{}"), meta)
		if !errors.Is(err, ErrInvalidImport) || provider.calls != 0 {
			t.Fatalf("invalid metadata passed to importer: %+v %v", meta, err)
		}
	}
	stamp := time.Now().UTC()
	result, err := service.Import(context.Background(), strings.NewReader("{}"), ImportMetadata{
		Name: " zones ", Kind: "observed", Source: " supplier ", CapturedAt: &stamp})
	if err != nil || result.DatasetID != "saved" || provider.calls != 1 {
		t.Fatalf("valid metadata rejected: %+v %v", result, err)
	}
}
