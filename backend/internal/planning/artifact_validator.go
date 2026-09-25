package planning

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/Elmar006/energy_web/backend/internal/artifact"
)

// ArtifactValidator resolves only server-controlled content addresses. It
// validates the complete dated input while the persisted scenario remains an
// immutable, compact reference to the same bytes.
type ArtifactValidator struct {
	Next   InputValidator
	Reader artifact.Reader
}

func (v ArtifactValidator) Validate(ctx context.Context, spec json.RawMessage) error {
	if v.Next == nil {
		return ErrValidatorUnavailable
	}
	hydrated, _, err := artifact.HydrateDemand(ctx, spec, v.Reader)
	if err != nil {
		if errors.Is(err, artifact.ErrInvalid) || errors.Is(err, artifact.ErrNotFound) {
			return InvalidInputError{Detail: "demand_dataset must identify an uploaded, valid immutable artifact"}
		}
		return ErrValidatorUnavailable
	}
	return v.Next.Validate(ctx, hydrated)
}
