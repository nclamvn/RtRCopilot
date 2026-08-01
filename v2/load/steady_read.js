// TIP-012 Task 5 — S1 steady-state mixed authenticated read + S5 availability.
// Mixed GET load across files / gaps / dashboard through the ingress, plus a
// 1 rps unauthenticated /api/status availability probe running concurrently.
//
// Tunables (env): VUS (default 10), DURATION (default 60s), AVAIL_RATE (1/s).

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import {
  BASE, login, readDuration, errors, availOk, SUMMARY_TREND_STATS,
} from './lib/common.js';

// Representative interactive load, modelled as a fixed authenticated-read
// arrival rate (constant-arrival-rate). RATE reads/s ≈ a busy moment for an
// internal VPN/LAN tool (tens of users, human think time), NOT a robot hammering
// with zero think time. The DB engine pools 5+5 connections (db/engine.py); the
// arrival-rate model pins the offered load precisely so the p95 is reproducible.
const RATE = Number(__ENV.RATE || 8);
const DURATION = __ENV.DURATION || '60s';
const PREALLOC_VUS = Number(__ENV.PREALLOC_VUS || 20);
const MAX_VUS = Number(__ENV.MAX_VUS || 60);
const AVAIL_RATE = Number(__ENV.AVAIL_RATE || 1);

// Per-endpoint sub-trends: files/gaps are point reads; the governance dashboard
// is a live multi-query aggregate (materially heavier). Split out so the SLO
// evaluation can hold point reads and the aggregate to different bars.
const pointRead = new Trend('point_read_duration', true);
const dashboardRead = new Trend('dashboard_read_duration', true);

export const options = {
  insecureSkipTLSVerify: true,
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    steady_read: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: PREALLOC_VUS,
      maxVUs: MAX_VUS,
      exec: 'read',
    },
    availability: {
      executor: 'constant-arrival-rate',
      rate: AVAIL_RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: 2,
      exec: 'avail',
    },
  },
};

const READS = [
  { name: 'files', path: '/api/v1/files?limit=25' },
  { name: 'gaps', path: '/api/v1/gaps' },
  { name: 'dashboard', path: '/api/v1/governance/dashboard' },
];

export function setup() {
  return { cookie: login() };
}

export function read(data) {
  const target = READS[Math.floor(Math.random() * READS.length)];
  const res = http.get(`${BASE}${target.path}`, {
    headers: { Cookie: data.cookie },
    tags: { name: target.name },
  });
  readDuration.add(res.timings.duration);
  if (target.name === 'dashboard') {
    dashboardRead.add(res.timings.duration);
  } else {
    pointRead.add(res.timings.duration);
  }
  const ok = check(res, { 'read 200': (r) => r.status === 200 });
  errors.add(!ok);
}

export function avail() {
  const res = http.get(`${BASE}/api/status`, { tags: { name: 'status_probe' } });
  availOk.add(res.status === 200 && res.timings.duration < 1000);
}
