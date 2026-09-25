package artifact

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
)

// MaxBytes bounds a single immutable input artifact. The API applies the same
// bound before buffering uploads; the reader applies it again on replay.
const MaxBytes = 64 << 20

var (
	ErrInvalid   = errors.New("invalid artifact")
	ErrIntegrity = errors.New("artifact integrity failure")
	ErrNotFound  = errors.New("artifact not found")
	hexSHA       = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// Manifest contains no path or external URL supplied by a client. The only
// accepted artifact ID is the content address derived from the SHA-256 bytes.
type Manifest struct {
	SchemaVersion string `json:"schema_version"`
	ArtifactID    string `json:"artifact_id"`
	SHA256        string `json:"sha256"`
	ByteSize      int64  `json:"byte_size"`
}

func (m Manifest) Validate() error {
	if m.SchemaVersion != "demand-dataset-v1" || !hexSHA.MatchString(m.SHA256) ||
		m.ArtifactID != "sha256:"+m.SHA256 || m.ByteSize < 1 || m.ByteSize > MaxBytes {
		return ErrInvalid
	}
	return nil
}

type Reader interface {
	Read(context.Context, Manifest) ([]byte, error)
}

type Store interface {
	Reader
	Put(context.Context, []byte) (Manifest, error)
}

type Local struct{ Root string }

func (s Local) path(hash string) string {
	return filepath.Join(s.Root, hash[:2], hash+".json")
}

func (s Local) Put(ctx context.Context, content []byte) (Manifest, error) {
	if err := ctx.Err(); err != nil {
		return Manifest{}, err
	}
	if s.Root == "" || len(content) < 1 || len(content) > MaxBytes {
		return Manifest{}, ErrInvalid
	}
	sum := sha256.Sum256(content)
	hash := hex.EncodeToString(sum[:])
	m := Manifest{SchemaVersion: "demand-dataset-v1", ArtifactID: "sha256:" + hash,
		SHA256: hash, ByteSize: int64(len(content))}
	path := s.path(hash)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return Manifest{}, err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".upload-*")
	if err != nil {
		return Manifest{}, err
	}
	defer os.Remove(temp.Name())
	if err := temp.Chmod(0600); err != nil {
		temp.Close()
		return Manifest{}, err
	}
	if _, err := temp.Write(content); err != nil {
		temp.Close()
		return Manifest{}, err
	}
	if err := temp.Sync(); err != nil {
		temp.Close()
		return Manifest{}, err
	}
	if err := temp.Close(); err != nil {
		return Manifest{}, err
	}
	// A hard link is atomic and refuses to overwrite an existing content
	// address. A racing writer either publishes identical bytes or verifies
	// the already published file below.
	if err := os.Link(temp.Name(), path); err != nil && !errors.Is(err, os.ErrExist) {
		return Manifest{}, err
	}
	if _, err := s.Read(ctx, m); err != nil {
		return Manifest{}, err
	}
	return m, nil
}

func (s Local) Read(ctx context.Context, m Manifest) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if s.Root == "" || m.Validate() != nil {
		return nil, ErrInvalid
	}
	path := s.path(m.SHA256)
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() != m.ByteSize {
		return nil, ErrIntegrity
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	content, err := io.ReadAll(io.LimitReader(file, MaxBytes+1))
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(content)
	if len(content) != int(m.ByteSize) || fmt.Sprintf("%x", sum) != m.SHA256 {
		return nil, ErrIntegrity
	}
	return content, nil
}

func ParseManifest(raw json.RawMessage) (Manifest, error) {
	var m Manifest
	if err := strictObject(raw, &m); err != nil || m.Validate() != nil {
		return Manifest{}, ErrInvalid
	}
	return m, nil
}
