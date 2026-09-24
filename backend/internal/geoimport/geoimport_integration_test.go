package geoimport

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

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
	t.Cleanup(db.Close)
	good := `{"type":"FeatureCollection","features":[{"type":"Feature","id":"one","geometry":{"type":"Point","coordinates":[37.6,55.7]},"properties":{"feature_type":"charger"}}]}`
	name := fmt.Sprintf("geo test %d", time.Now().UnixNano())
	capturedAt := time.Date(2026, time.September, 24, 12, 0, 0, 123456789, time.UTC)
	meta := Metadata{Name: name, Source: "test", Kind: "assumed", CapturedAt: &capturedAt}
	result, err := Import(context.Background(), db, strings.NewReader(good), meta)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = db.Exec(context.Background(), `DELETE FROM geographic_features WHERE dataset_version_id=$1::uuid`, result.DatasetID)
		_, _ = db.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, result.DatasetID)
	})
	if result.Features != 1 || result.DatasetID == "" {
		t.Fatalf("bad result: %+v", result)
	}
	repeated, err := Import(context.Background(), db, strings.NewReader(good), meta)
	if err != nil || repeated.DatasetID != result.DatasetID || repeated.Features != 1 {
		t.Fatalf("reimport created duplicate: %+v %v", repeated, err)
	}
	licensed := meta
	licensed.License = "different license"
	separate, err := Import(context.Background(), db, strings.NewReader(good), licensed)
	if err != nil || separate.DatasetID == result.DatasetID || separate.DatasetID == "" {
		t.Fatalf("changed provenance was collapsed: %+v %v", separate, err)
	}
	t.Cleanup(func() {
		_, _ = db.Exec(context.Background(), `DELETE FROM geographic_features WHERE dataset_version_id=$1::uuid`, separate.DatasetID)
		_, _ = db.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, separate.DatasetID)
	})
	concurrentMeta := meta
	concurrentMeta.Name += " concurrent"
	var concurrent [2]Result
	var concurrentErr [2]error
	var wg sync.WaitGroup
	for i := range concurrent {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			concurrent[index], concurrentErr[index] = Import(context.Background(), db, strings.NewReader(good), concurrentMeta)
		}(i)
	}
	wg.Wait()
	for _, item := range concurrent {
		if item.DatasetID != "" {
			id := item.DatasetID
			t.Cleanup(func() {
				_, _ = db.Exec(context.Background(), `DELETE FROM geographic_features WHERE dataset_version_id=$1::uuid`, id)
				_, _ = db.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, id)
			})
		}
	}
	if concurrentErr[0] != nil || concurrentErr[1] != nil || concurrent[0].DatasetID == "" || concurrent[0].DatasetID != concurrent[1].DatasetID {
		t.Fatalf("concurrent reimport created duplicates: %+v, errors=%v", concurrent, concurrentErr)
	}
	var count int
	err = db.QueryRow(context.Background(), `SELECT count(*) FROM geographic_features WHERE dataset_version_id::text=$1`, result.DatasetID).Scan(&count)
	if err != nil || count != 1 {
		t.Fatalf("count=%d error=%v", count, err)
	}
	bad := `{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[37.6,55.7]}},{"type":"Feature","geometry":{"type":"Point","coordinates":[200,55.7]}}]}`
	badName := name + " bad"
	_, err = Import(context.Background(), db, strings.NewReader(bad), Metadata{Name: badName, Source: "test", Kind: "assumed"})
	if err == nil {
		t.Fatal("invalid coordinate accepted")
	}
	err = db.QueryRow(context.Background(), `SELECT count(*) FROM dataset_versions WHERE name=$1`, badName).Scan(&count)
	if err != nil || count != 0 {
		t.Fatalf("failed import was not atomic: %d %v", count, err)
	}
}
