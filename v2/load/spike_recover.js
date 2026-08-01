// TIP-012 Task 5 — S6 spike-and-recover on the read path.
// Ramps read load from a baseline up to a spike and back down, then holds a
// recovery tail. read_duration is recorded for the whole run; a separate
// read_duration_recovery Trend records ONLY the recovery tail so the SLO check
// can assert p95 returns to the steady-state target after the spike drains.
//
// Tunables (env): BASE_VUS (5), SPIKE_VUS (40), RECOVERY_AFTER_MS (auto).

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import {
  BASE, login, readDuration, readRecovery, errors, SUMMARY_TREND_STATS,
} from './lib/common.js';

const BASE_VUS = Number(__ENV.BASE_VUS || 5);
const SPIKE_VUS = Number(__ENV.SPIKE_VUS || 40);

// Stage plan (ms boundaries used to mark the recovery window):
//  0-10s ramp to spike, 10-20s hold spike, 20-25s ramp down, 25-45s recovery.
const RECOVERY_AFTER_MS = Number(__ENV.RECOVERY_AFTER_MS || 27000);

export const options = {
  insecureSkipTLSVerify: true,
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    spike: {
      executor: 'ramping-vus',
      startVUs: BASE_VUS,
      stages: [
        { duration: '10s', target: SPIKE_VUS },
        { duration: '10s', target: SPIKE_VUS },
        { duration: '5s', target: BASE_VUS },
        { duration: '20s', target: BASE_VUS },
      ],
      gracefulRampDown: '2s',
    },
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
  readDuration.add(res.timings.duration);
  if (exec.instance.currentTestRunDuration > RECOVERY_AFTER_MS) {
    readRecovery.add(res.timings.duration);
  }
  const ok = check(res, { 'read 200': (r) => r.status === 200 });
  errors.add(!ok);
}
