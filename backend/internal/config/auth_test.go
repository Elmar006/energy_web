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
		{"unset environment strong secret", strings.Repeat("x", 32), "", "", false},
		{"unknown environment", strings.Repeat("x", 40), "staging-ish", "", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateAPIToken(tc.token, tc.environment, tc.demoFlag)
			if (err == nil) != tc.valid {
				t.Fatalf("unexpected credential decision: %v", err)
			}
			if !tc.valid && tc.environment != "staging-ish" && tc.environment != "" && !errors.Is(err, ErrInsecureAPIToken) {
				t.Fatalf("missing actionable token error: %v", err)
			}
		})
	}
}

func TestValidateEnvironment(t *testing.T) {
	for _, env := range []string{"", "prod", "Production"} {
		if ValidateEnvironment(env) == nil {
			t.Fatalf("invalid environment accepted: %q", env)
		}
	}
	for _, env := range []string{"development", "test", "production"} {
		if err := ValidateEnvironment(env); err != nil {
			t.Fatal(err)
		}
	}
}
