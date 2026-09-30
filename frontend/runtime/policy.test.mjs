import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateRuntime, passwordsEqual, issueSession, verifySession, trustedMutation, LoginLimiter } from './policy.mjs';

const valid = { APP_ENV: 'production', API_TOKEN: 'a'.repeat(40), SESSION_SECRET: 'b'.repeat(40), APP_ACCESS_PASSWORD: 'c'.repeat(30), APP_AUTH_MODE: 'private-single-tenant', APP_COOKIE_SECURE: 'true', APP_PUBLIC_ORIGIN: 'https://planner.test', ENERGY_API_URL: 'http://api:8080' };
test('production fails closed for missing secrets, insecure cookies and unimplemented auth modes', () => {
  assert.doesNotThrow(() => validateRuntime(valid));
  for (const key of Object.keys(valid)) assert.throws(() => validateRuntime({ ...valid, [key]: '' }), key);
  for (const patch of [{ SESSION_SECRET: valid.API_TOKEN }, { APP_ACCESS_PASSWORD: valid.API_TOKEN }, { API_TOKEN: 'replace-with-long-random-tokenxxxxxxxx' }, { APP_AUTH_MODE: 'multi-user' }, { APP_PUBLIC_ORIGIN: 'http://planner.test' }, { APP_PUBLIC_ORIGIN: 'https://planner.test/path' }, { APP_PUBLIC_ORIGIN: 'https://user:password@planner.test' }]) assert.throws(() => validateRuntime({ ...valid, ...patch }));
});
test('legacy demo password cannot enable production', () => {
  assert.throws(() => validateRuntime({ ...valid, APP_ACCESS_PASSWORD: undefined, APP_DEMO_PASSWORD: 'd'.repeat(30) }));
  assert.doesNotThrow(() => validateRuntime({ ...valid, APP_ENV: 'development', APP_ACCESS_PASSWORD: undefined, APP_DEMO_PASSWORD: 'local-pass' }));
});
test('sessions reject tampering, malformed expiry, trailing data, expiry and wrong keys', () => {
  const now = 1_800_000_000_000;
  const value = issueSession(valid.SESSION_SECRET, now);
  assert.equal(verifySession(value, valid.SESSION_SECRET, now), true);
  for (const invalid of [undefined, 'NaN.' + value.split('.')[1], value + '.extra', value.slice(0, -1) + 'z', '9999999999999.' + value.split('.')[1]]) assert.equal(verifySession(invalid, valid.SESSION_SECRET, now), false);
  assert.equal(verifySession(value, valid.SESSION_SECRET, now + 43_200_000), false);
  assert.equal(verifySession(value, valid.API_TOKEN, now), false);
  assert.equal(passwordsEqual('abc', 'abc'), true);
  assert.equal(passwordsEqual('abc', 'abcd'), false);
});
test('cross-origin and originless mutations are rejected behind a proxy', () => {
  assert.equal(trustedMutation('https://planner.test', 'http://frontend:3000/api/runs', valid), true);
  for (const origin of [null, 'null', 'https://evil.test', 'https://planner.test.evil.test']) assert.equal(trustedMutation(origin, 'http://frontend:3000/api/runs', valid), false);
});
test('loopback development works through Docker port mapping without trusting arbitrary hosts', () => {
  const dev = { APP_ENV: 'development' };
  assert.equal(trustedMutation('http://127.0.0.1:53001', 'http://localhost:3000/api/session', dev, '127.0.0.1:53001'), true);
  assert.equal(trustedMutation('https://evil.test', 'http://localhost:3000/api/session', dev, 'evil.test'), false);
  assert.equal(trustedMutation('http://127.0.0.1:53001', 'http://localhost:3000/api/session', valid, '127.0.0.1:53001'), false);
});
test('login limiter is bounded and resets only after the window', () => {
  const limiter = new LoginLimiter();
  for (let i = 0; i < 10; i++) assert.equal(limiter.consume(1000), true);
  assert.equal(limiter.consume(1001), false);
  assert.equal(limiter.consume(61_000), true);
});
