package config

import (
	"errors"
	"strings"
)

const LocalDemoToken = "local-development-token-change-before-deploy"

var ErrInsecureAPIToken = errors.New("API_TOKEN is missing, a placeholder, or unsafe for this environment")

// ValidateAPIToken refuses the Compose demo credential unless the operator
// explicitly opts into local development mode. APP_ENV empty follows the
// stricter deployment path; it cannot silently permit a default credential.
func ValidateAPIToken(token, appEnv, allowInsecureDemo string) error {
	if appEnv != "" && appEnv != "development" && appEnv != "test" && appEnv != "production" {
		return errors.New("APP_ENV must be development, test, or production")
	}
	if token == LocalDemoToken {
		if appEnv == "development" && allowInsecureDemo == "1" {
			return nil
		}
		return ErrInsecureAPIToken
	}
	if strings.Contains(strings.ToLower(token), "replace-") ||
		strings.Contains(strings.ToLower(token), "change-me") ||
		strings.Contains(strings.ToLower(token), "example") {
		return ErrInsecureAPIToken
	}
	minimum := 32
	if appEnv == "development" || appEnv == "test" {
		minimum = 24
	}
	if len(token) < minimum {
		return ErrInsecureAPIToken
	}
	return nil
}
