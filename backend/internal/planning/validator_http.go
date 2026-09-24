package planning

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type HTTPValidator struct {
	URL    string
	Client *http.Client
}

func (v HTTPValidator) Validate(ctx context.Context, spec json.RawMessage) error {
	if v.URL == "" {
		return ErrValidatorUnavailable
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(v.URL, "/")+"/v1/validate", bytes.NewReader(spec))
	if err != nil {
		return ErrValidatorUnavailable
	}
	request.Header.Set("Content-Type", "application/json")
	client := v.Client
	if client == nil {
		client = &http.Client{Timeout: 15 * time.Second}
	}
	response, err := client.Do(request)
	if err != nil {
		return ErrValidatorUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusOK {
		var result struct {
			Valid bool `json:"valid"`
		}
		if err := json.NewDecoder(io.LimitReader(response.Body, 1<<16)).Decode(&result); err != nil || !result.Valid {
			return ErrValidatorUnavailable
		}
		return nil
	}
	if response.StatusCode != http.StatusUnprocessableEntity {
		return ErrValidatorUnavailable
	}
	var validation struct {
		Detail []struct {
			Loc []any  `json:"loc"`
			Msg string `json:"msg"`
		} `json:"detail"`
	}
	_ = json.NewDecoder(io.LimitReader(response.Body, 1<<16)).Decode(&validation)
	detail := "scenario does not match the planning input contract"
	if len(validation.Detail) > 0 {
		parts := make([]string, 0, len(validation.Detail[0].Loc))
		for _, part := range validation.Detail[0].Loc {
			parts = append(parts, fmt.Sprint(part))
		}
		detail = strings.Join(parts, ".") + ": " + validation.Detail[0].Msg
	}
	return InvalidInputError{Detail: detail}
}
