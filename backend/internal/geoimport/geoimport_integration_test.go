package geoimport

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestImportValidAndAtomicFailure(t *testing.T) {
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	db, err := pgxpool.New(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	good := `{"type":"FeatureCollection","features":[{"type":"Feature","id":"one","geometry":{"type":"Point","coordinates":[37.6,55.7]},"properties":{"feature_type":"charger"}}]}`
	result, err := Import(context.Background(), db, strings.NewReader(good), Metadata{Name: "geo test", Source: "test", Kind: "assumed"})
	if err != nil {
		t.Fatal(err)
	}
	if result.Features != 1 || result.DatasetID == "" {
		t.Fatalf("bad result: %+v", result)
	}
	var count int
	err = db.QueryRow(context.Background(), `SELECT count(*) FROM geographic_features WHERE dataset_version_id::text=$1`, result.DatasetID).Scan(&count)
	if err != nil || count != 1 {
		t.Fatalf("count=%d error=%v", count, err)
	}
	bad := `{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[37.6,55.7]}},{"type":"Feature","geometry":{"type":"Point","coordinates":[200,55.7]}}]}`
	_, err = Import(context.Background(), db, strings.NewReader(bad), Metadata{Name: "bad geo test", Source: "test", Kind: "assumed"})
	if err == nil {
		t.Fatal("invalid coordinate accepted")
	}
	err = db.QueryRow(context.Background(), `SELECT count(*) FROM dataset_versions WHERE name='bad geo test'`).Scan(&count)
	if err != nil || count != 0 {
		t.Fatalf("failed import was not atomic: %d %v", count, err)
	}
}
