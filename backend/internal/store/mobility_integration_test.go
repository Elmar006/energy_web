package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/migrate"
	"github.com/Elmar006/energy_web/backend/internal/planning"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestMobilitySaveRollsBackAllRowsIfSourceFailsConstraint(t *testing.T) {
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	ctx := context.Background()
	db, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := migrate.Apply(ctx, db, os.DirFS("../../migrations")); err != nil {
		t.Fatal(err)
	}
	var versionID string
	if err := db.QueryRow(ctx, `SELECT gen_random_uuid()::text`).Scan(&versionID); err != nil {
		t.Fatal(err)
	}
	source := []byte(`{"schema_version":"mobility-v1","source":"rollback test","source_kind":"assumed"}`)
	sourceSum := sha256.Sum256(source)
	sourceSHA := hex.EncodeToString(sourceSum[:])
	spec := json.RawMessage(fmt.Sprintf(`{"id":"compiled","datasets":[{"version_id":%q,"sha256":%q}]}`, versionID, sourceSHA))
	name := fmt.Sprintf("mobility-rollback-%d", time.Now().UnixNano())
	_, err = (&Store{DB: db}).SaveMobility(ctx, planning.MobilityPersist{
		Name: name, Spec: spec, BaseInput: json.RawMessage(`{"id":"original"}`),
		CanonicalMobility: source, SourceSHA256: sourceSHA,
		SourceKind: "assumed", SourceName: "rollback test", DatasetVersionID: versionID,
		AccessTokenSHA256: "invalid", CompilerVersion: "mobility-v1",
		CompilerSourceSHA256: strings.Repeat("a", 64), CompilerPydanticVersion: "2.12.0",
	})
	if err == nil {
		t.Fatal("source constraint unexpectedly accepted invalid capability digest")
	}
	var scenarios, versions int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM scenarios WHERE name=$1`, name).Scan(&scenarios); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(ctx, `SELECT count(*) FROM dataset_versions WHERE id=$1::uuid`, versionID).Scan(&versions); err != nil {
		t.Fatal(err)
	}
	if scenarios != 0 || versions != 0 {
		t.Fatalf("partial save after source constraint failure: scenarios=%d versions=%d", scenarios, versions)
	}
}
