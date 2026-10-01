import { createHash, createHmac, timingSafeEqual } from 'node:crypto';

const placeholders = /replace[-_]|change[-_]?me|example|demo-local-password|local-development-token/i;
const lifespan = 12 * 60 * 60 * 1000;

/** @param {NodeJS.ProcessEnv} env */
export function validateRuntime(env) {
  const production = env.APP_ENV === 'production';
  if (!['development', 'test', 'production'].includes(env.APP_ENV ?? '')) throw new Error('APP_ENV must be explicit');
  const token = env.API_TOKEN ?? '';
  const localDemo = env.APP_ENV === 'development' && env.ALLOW_INSECURE_DEMO_TOKEN === '1';
  if (token.length < (production ? 32 : 24) || (!localDemo && placeholders.test(token))) throw new Error('Configure a strong API_TOKEN');
  const password = env.APP_ACCESS_PASSWORD ?? (!production ? env.APP_DEMO_PASSWORD : undefined);
  if (!password || (production && (password.length < 24 || placeholders.test(password)))) throw new Error('Configure APP_ACCESS_PASSWORD');
  const secret = env.SESSION_SECRET || (!production ? token : undefined);
  if (!secret || secret.length < (production ? 32 : 24) || (production && (placeholders.test(secret) || secret === token || secret === password || password === token))) throw new Error('Configure an independent SESSION_SECRET');
  if (production) {
    if (env.APP_AUTH_MODE !== 'private-single-tenant') throw new Error('Production requires explicit private-single-tenant mode; multi-user RBAC is not implemented');
    if (env.APP_COOKIE_SECURE !== 'true') throw new Error('Production requires secure cookies');
    const origin = new URL(env.APP_PUBLIC_ORIGIN ?? '');
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('APP_PUBLIC_ORIGIN must be a canonical HTTPS origin');
    if (!env.ENERGY_API_URL) throw new Error('ENERGY_API_URL is required');
  }
  return { password, secret, production };
}

/** @param {string} a @param {string} b */
export function passwordsEqual(a, b) {
  return timingSafeEqual(createHash('sha256').update(a).digest(), createHash('sha256').update(b).digest());
}

/** @param {string} secret @param {number} now */
export function issueSession(secret, now = Date.now()) {
  const expiry = String(now + lifespan);
  return `${expiry}.${createHmac('sha256', secret).update(expiry).digest('hex')}`;
}

/** @param {string | undefined} value @param {string} secret @param {number} now */
export function verifySession(value, secret, now = Date.now()) {
  if (!value || !/^\d{13}\.[0-9a-f]{64}$/.test(value)) return false;
  const [expiry, mac] = value.split('.');
  if (Number(expiry) <= now || Number(expiry) > now + lifespan) return false;
  return timingSafeEqual(Buffer.from(mac, 'hex'), createHmac('sha256', secret).update(expiry).digest());
}

/** @param {string | null} origin @param {string} requestUrl @param {NodeJS.ProcessEnv} env @param {string | null} host */
export function trustedMutation(origin, requestUrl, env, host = null) {
  // The configured origin is authoritative behind a reverse proxy; forwarded headers are not.
  const url = new URL(requestUrl);
  // Docker rewrites the internal request URL port. Only local development may
  // use the real Host, and only loopback hosts; no forwarded header is trusted.
  const localHost = env.APP_ENV !== 'production' && host && /^(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?$/.test(host)
    ? new URL(`${url.protocol}//${host}`).origin : url.origin;
  const expected = env.APP_PUBLIC_ORIGIN || (env.APP_ENV !== 'production' ? localHost : '');
  return Boolean(origin && expected && origin === expected);
}

// Per-process backstop. A public deployment also needs a shared ingress limit.
export class LoginLimiter {
  attempts = 0;
  resetsAt = 0;
  /** @param {number} now */
  consume(now = Date.now()) {
    if (now >= this.resetsAt) { this.attempts = 0; this.resetsAt = now + 60_000; }
    if (this.attempts >= 10) return false;
    this.attempts++;
    return true;
  }
}
