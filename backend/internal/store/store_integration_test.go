package store

import (
	"context"
	"encoding/json"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	pool, err := pgxpool.New(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return &Store{DB: pool}
}

func TestRunLifecycle(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "test", json.RawMessage(`{"id":"test"}`))
	if err != nil {
		t.Fatal(err)
	}
	run, err := s.CreateRun(ctx, scenario.ID, "same-request-123")
	if err != nil {
		t.Fatal(err)
	}
	again, err := s.CreateRun(ctx, scenario.ID, "same-request-123")
	if err != nil {
		t.Fatal(err)
	}
	if run.ID != again.ID {
		t.Fatal("idempotency failed")
	}
	job, err := s.Claim(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if job == nil || job.RunID != run.ID {
		t.Fatalf("unexpected job: %+v", job)
	}
	second, err := s.Claim(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if second != nil {
		t.Fatal("job claimed twice")
	}
	alive, err := s.Heartbeat(ctx, job.RunID, job.AttemptID)
	if err != nil || !alive {
		t.Fatalf("heartbeat: %v %v", alive, err)
	}
	finished, err := s.Finish(ctx, *job, json.RawMessage(`{"ok":true}`), "", "")
	if err != nil || !finished {
		t.Fatalf("finish: %v %v", finished, err)
	}
	finished, err = s.Finish(ctx, *job, nil, "failure", "late")
	if err != nil || finished {
		t.Fatalf("stale finish accepted: %v %v", finished, err)
	}
	result, err := s.Result(ctx, run.ID)
	var parsed map[string]bool
	if err != nil || json.Unmarshal(result, &parsed) != nil || !parsed["ok"] {
		t.Fatalf("result: %s %v", result, err)
	}
	events, err := s.Events(ctx, run.ID, 0)
	if err != nil || len(events) != 2 {
		t.Fatalf("events: %+v %v", events, err)
	}
}

func TestCancellationRejectsFinish(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "cancel", json.RawMessage(`{"id":"cancel"}`))
	if err != nil {
		t.Fatal(err)
	}
	run, err := s.CreateRun(ctx, scenario.ID, "cancel-request-123")
	if err != nil {
		t.Fatal(err)
	}
	job, err := s.Claim(ctx)
	if err != nil || job == nil {
		t.Fatalf("claim: %+v %v", job, err)
	}
	ok, err := s.Cancel(ctx, run.ID)
	if err != nil || !ok {
		t.Fatalf("cancel: %v %v", ok, err)
	}
	finished, err := s.Finish(ctx, *job, json.RawMessage(`{"ok":true}`), "", "")
	if err != nil || finished {
		t.Fatalf("cancelled finish accepted: %v %v", finished, err)
	}
	current, err := s.GetRun(ctx, run.ID)
	if err != nil || current.State != "cancelled" {
		t.Fatalf("state: %+v %v", current, err)
	}
}

func TestExpiredLeaseReclaimsWithNewAttemptAndRejectsStaleResult(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	scenario, err := s.CreateScenario(ctx, "expired lease", json.RawMessage(`{"id":"lease"}`))
	if err != nil {
		t.Fatal(err)
	}
	run, err := s.CreateRun(ctx, scenario.ID, "expired-lease-request")
	if err != nil {
		t.Fatal(err)
	}
	first, err := s.Claim(ctx)
	if err != nil || first == nil || first.RunID != run.ID {
		t.Fatalf("first claim: %+v %v", first, err)
	}
	_, err = s.DB.Exec(ctx, `UPDATE runs SET lease_until=now()-interval '1 second' WHERE id::text=$1`, run.ID)
	if err != nil {
		t.Fatal(err)
	}
	second, err := s.Claim(ctx)
	if err != nil || second == nil || second.RunID != run.ID || second.AttemptID == first.AttemptID {
		t.Fatalf("reclaim: %+v %v", second, err)
	}
	accepted, err := s.Finish(ctx, *first, json.RawMessage(`{"stale":true}`), "", "")
	if err != nil || accepted {
		t.Fatalf("stale result accepted: %v %v", accepted, err)
	}
	accepted, err = s.Finish(ctx, *second, json.RawMessage(`{"fresh":true}`), "", "")
	if err != nil || !accepted {
		t.Fatalf("current result rejected: %v %v", accepted, err)
	}
	current, err := s.GetRun(ctx, run.ID)
	if err != nil || current.Attempts != 2 || current.State != "succeeded" {
		t.Fatalf("bad current run: %+v %v", current, err)
	}
}
