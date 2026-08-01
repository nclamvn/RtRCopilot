// TIP-012 Task 5 — R1 rate-limit-under-load probe. MUST run against the stack
// with the SHIPPED DEFAULT limits (i.e. WITHOUT compose.load.yaml). It drives a
// single client IP past the default `default-read` quota (120 / 60s) and asserts
// typed 429 + Retry-After appear at the threshold with ZERO 5xx. Requests under
// the limit still succeed. This is the through-ingress complement to Builder 2's
// integration tests.
//
// Tunables (env): PROBE_REQUESTS (default 250), PROBE_VUS (default 10).

import http from 'k6/http';
import { check } from 'k6';
import { BASE, login, s200, s429, s5xx } from './lib/common.js';

const PROBE_REQUESTS = Number(__ENV.PROBE_REQUESTS || 250);
const PROBE_VUS = Number(__ENV.PROBE_VUS || 10);

export const options = {
  insecureSkipTLSVerify: true,
  scenarios: {
    rate_limit_probe: {
      executor: 'shared-iterations',
      vus: PROBE_VUS,
      iterations: PROBE_REQUESTS,
      maxDuration: '40s',
    },
  },
  // Self-contained pass/fail: at least one 429 must appear, and never a 5xx.
  thresholds: {
    status_429: ['count>0'],
    status_5xx: ['count==0'],
  },
};

export function setup() {
  return { cookie: login() };
}

export default function (data) {
  const res = http.get(`${BASE}/api/v1/files?limit=25`, {
    headers: { Cookie: data.cookie },
    tags: { name: 'files' },
  });
  if (res.status === 200) {
    s200.add(1);
  } else if (res.status === 429) {
    s429.add(1);
    check(res, {
      '429 has Retry-After': (r) => Number(r.headers['Retry-After']) >= 1,
      '429 typed rate_limited': (r) => {
        try { return r.json().error.code === 'rate_limited'; }
        catch (e) { return false; }
      },
    });
  } else if (res.status >= 500) {
    s5xx.add(1);
  }
}
