// TIP-012 Task 5 — S2 ask burst against the FAKE/offline provider.
// Concurrent POST /api/v1/ask through the ingress. Questions rotate over the
// synthetic corpus so most asks are grounded (exercise the offline extractive
// provider + grounding-verify + citation persistence); the rest are honest-null
// (also a valid, timed ask outcome). No external network / no provider spend.
//
// Tunables (env): VUS (default 8), DURATION (default 30s).

import http from 'k6/http';
import { check, sleep } from 'k6';
import {
  BASE, login, askDuration, errors, SUMMARY_TREND_STATS,
} from './lib/common.js';

const VUS = Number(__ENV.VUS || 8);
const DURATION = __ENV.DURATION || '30s';

export const options = {
  insecureSkipTLSVerify: true,
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    ask_burst: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
};

const QUESTIONS = [
  'What are the drone safety requirements?',
  'Describe the zephyr harmonic docking controller.',
  'What does the lexical calibration protocol cover?',
  'Summarize the synthetic calibration protocol.',
  'What is the docking controller specification?',
];

export function setup() {
  return { cookie: login() };
}

export default function (data) {
  const q = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const res = http.post(
    `${BASE}/api/v1/ask`,
    JSON.stringify({ question: q, filters: {} }),
    {
      headers: { Cookie: data.cookie, 'Content-Type': 'application/json' },
      tags: { name: 'ask' },
    },
  );
  askDuration.add(res.timings.duration);
  const ok = check(res, {
    'ask 200': (r) => r.status === 200,
    'ask has state': (r) => {
      try { return ['grounded', 'honest_null'].includes(r.json().state); }
      catch (e) { return false; }
    },
  });
  errors.add(!ok);
  sleep(0.1 + Math.random() * 0.3);
}
