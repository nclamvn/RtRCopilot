// TIP-012 Task 5 (Builder 5) — shared k6 helpers for the RtR Copilot V2 load
// suite. All scenarios drive traffic THROUGH THE INGRESS (https://rtr.local),
// i.e. the full Caddy -> app path (TLS, security headers, request-id, the
// Redis rate limiter and the body-size guard). See load/README.md.

import http from 'k6/http';
import { Trend, Rate, Counter } from 'k6/metrics';

export const BASE = __ENV.BASE_URL || 'https://rtr.local';
export const COOKIE = __ENV.SESSION_COOKIE_NAME || 'rtr_session';

// Custom metrics keyed by the SLO evaluation script (scripts/evaluate-slo.sh).
export const readDuration = new Trend('read_duration', true);
export const askDuration = new Trend('ask_duration', true);
export const uploadDuration = new Trend('upload_duration', true);
export const readRecovery = new Trend('read_duration_recovery', true);
export const errors = new Rate('errors');
export const availOk = new Rate('avail_ok');
export const s200 = new Counter('status_200');
export const s429 = new Counter('status_429');
export const s5xx = new Counter('status_5xx');

// Trend stats that MUST appear in --summary-export so evaluate-slo.sh can read
// p(95). Re-declared in each scenario's options too (k6 reads it from options).
export const SUMMARY_TREND_STATS = [
  'avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max',
];

// Obtain a real dev-OIDC session through the ingress. The login endpoint is the
// web-proxied /api/auth/login; k6's per-VU cookie jar carries the PKCE/state
// cookies across the login -> dev/authorize -> callback redirect chain, and the
// callback sets the HttpOnly+Secure `rtr_session` cookie. We return it as a
// header string so every VU can attach it explicitly (setup's jar is not shared
// with VU jars). This mirrors Builder 1's through-ingress auth probe.
export function login() {
  const res = http.get(`${BASE}/api/auth/login`, {
    redirects: 10,
    tags: { name: 'auth_login' },
  });
  const jar = http.cookieJar();
  const cookies = jar.cookiesForURL(`${BASE}/`);
  const values = cookies[COOKIE];
  if (!values || values.length === 0) {
    throw new Error(
      `login failed: no ${COOKIE} cookie after auth chain (final status ${res.status})`,
    );
  }
  return `${COOKIE}=${values[0]}`;
}

// Discover a valid upload parent (a `source` the subject may upload into).
// Returns the first target id, or null if none exist.
export function firstUploadTarget(cookie) {
  const res = http.get(`${BASE}/api/v1/files/upload-targets`, {
    headers: { Cookie: cookie },
    tags: { name: 'upload_targets' },
  });
  if (res.status !== 200) return null;
  const body = res.json();
  if (!body || !body.items || body.items.length === 0) return null;
  return body.items[0].target_id;
}
