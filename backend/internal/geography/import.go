package geography

import (
	"context"
	"errors"
	"io"
	"strings"
	"time"
	"unicode/utf8"
)

type ImportMetadata struct {
	Name       string
	Kind       string
	Source     string
	License    string
	CapturedAt *time.Time
}

type ImportResult struct {
	DatasetID string `json:"dataset_id"`
	Features  int    `json:"features"`
	SHA256    string `json:"sha256"`
}

type DatasetImporter interface {
	ImportDataset(context.Context, io.Reader, ImportMetadata) (ImportResult, error)
}

type ImportService struct{ Repository DatasetImporter }

var ErrInvalidImport = errors.New("invalid dataset import")

func (s ImportService) Import(ctx context.Context, input io.Reader, meta ImportMetadata) (ImportResult, error) {
	meta.Name = strings.TrimSpace(meta.Name)
	meta.Source = strings.TrimSpace(meta.Source)
	meta.License = strings.TrimSpace(meta.License)
	if meta.Name == "" || utf8.RuneCountInString(meta.Name) > 120 || meta.Source == "" ||
		utf8.RuneCountInString(meta.Source) > 2048 || utf8.RuneCountInString(meta.License) > 2048 ||
		(meta.Kind != "observed" && meta.Kind != "derived" && meta.Kind != "assumed") ||
		(meta.Kind == "observed" && meta.CapturedAt == nil) {
		return ImportResult{}, ErrInvalidImport
	}
	return s.Repository.ImportDataset(ctx, input, meta)
}
