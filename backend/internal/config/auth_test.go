package config

import (
	"errors"
	"strings"
	"testing"
)

func TestValidateAPITokenRejectsDemoOutsideExplicitDevelopment(t *testing.T) {
	for _, tc := range []struct {
		name, token, environment, demoFlag string
		valid                              bool
	}{
		{"explicit local demo", LocalDemoToken, "development", "1", true},
		{"demo with no opt-in", LocalDemoToken, "development", "", false},
		{"demo in unset environment", LocalDemoToken, "", "1", false},
		{"demo in production", LocalDemoToken, "production", "1", false},
		{"demo in tests", LocalDemoToken, "test", "1", false},
		{"copied example value", "replace-with-long-random-token", "development", "1", false},
		{"short local secret", strings.Repeat("x", 23), "development", "", false},
		{"local custom secret", strings.Repeat("x", 24), "development", "", true},
		{"short production secret", strings.Repeat("x", 31), "production", "", false},
		{"production secret", strings.Repeat("x", 32), "production", "", true},
		{"unset environment strong secret", strings.Repeat("x", 32), "", "", true},
		{"unknown environment", strings.Repeat("x", 40), "staging-ish", "", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateAPIToken(tc.token, tc.environment, tc.demoFlag)
			if (err == nil) != tc.valid {
				t.Fatalf("unexpected credential decision: %v", err)
			}
			if !tc.valid && tc.environment != "staging-ish" && !errors.Is(err, ErrInsecureAPIToken) {
				t.Fatalf("missing actionable token error: %v", err)
			}
		})
	}
}
