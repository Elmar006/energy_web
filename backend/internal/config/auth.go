package config

import (
	"errors"
	"strings"
)

const LocalDemoToken = "local-development-token-change-before-deploy"

var ErrInsecureAPIToken = errors.New("API_TOKEN is missing, a placeholder, or unsafe for this environment")

// ValidateAPIToken refuses the Compose demo credential unless the operator
// explicitly opts into local development mode. The environment is mandatory:
// an omitted APP_ENV must not bypass production database checks.
func ValidateEnvironment(appEnv string) error {
	if appEnv != "development" && appEnv != "test" && appEnv != "production" {
		return errors.New("APP_ENV must be development, test, or production")
	}
	return nil
}

func ValidateAPIToken(token, appEnv, allowInsecureDemo string) error {
	if err := ValidateEnvironment(appEnv); err != nil {
		return err
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
